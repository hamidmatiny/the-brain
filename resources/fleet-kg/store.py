"""SQLite typed property-graph store for fleet institutional memory."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from schema import ENTITY_TYPES, REL_TYPES

DEFAULT_DB = Path(os.path.expanduser("~/memory/fleet-kg.sqlite"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FleetGraphStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()
        self._ensure_source_dedupe_index()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS nodes (
              id TEXT PRIMARY KEY,
              type TEXT NOT NULL,
              name TEXT NOT NULL,
              props_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
            CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);

            CREATE TABLE IF NOT EXISTS edges (
              id TEXT PRIMARY KEY,
              src TEXT NOT NULL,
              rel TEXT NOT NULL,
              dst TEXT NOT NULL,
              props_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              FOREIGN KEY(src) REFERENCES nodes(id),
              FOREIGN KEY(dst) REFERENCES nodes(id)
            );
            CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
            CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
            CREATE INDEX IF NOT EXISTS idx_edges_rel ON edges(rel);

            CREATE TABLE IF NOT EXISTS source_refs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              node_or_edge_id TEXT NOT NULL,
              source_kind TEXT NOT NULL,
              source_uri TEXT NOT NULL,
              excerpt TEXT,
              fetched_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_src_target ON source_refs(node_or_edge_id);

            CREATE VIRTUAL TABLE IF NOT EXISTS node_fts USING fts5(
              id, name, body, content=''
            );

            CREATE TABLE IF NOT EXISTS ingest_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              status TEXT NOT NULL,
              summary_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        self.conn.commit()

    def _ensure_source_dedupe_index(self) -> None:
        """Idempotent migration: unique (target, kind, uri) so re-ingest is incremental on refs."""
        # Drop prior duplicates (keep lowest id) so CREATE UNIQUE INDEX can succeed on existing DBs.
        self.conn.execute(
            """
            DELETE FROM source_refs
             WHERE id NOT IN (
               SELECT MIN(id) FROM source_refs
                GROUP BY node_or_edge_id, source_kind, source_uri
             )
            """
        )
        self.conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_src_dedupe
              ON source_refs(node_or_edge_id, source_kind, source_uri)
            """
        )
        self.conn.commit()


    def close(self) -> None:
        self.conn.close()

    def upsert_node(
        self,
        node_id: str,
        type_: str,
        name: str,
        props: dict[str, Any] | None = None,
        sources: Iterable[dict[str, str]] | None = None,
    ) -> None:
        if type_ not in ENTITY_TYPES:
            raise ValueError(f"unknown entity type: {type_}")
        now = _utc_now()
        props = props or {}
        row = self.conn.execute("SELECT id FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row:
            self.conn.execute(
                "UPDATE nodes SET name=?, props_json=?, updated_at=? WHERE id=?",
                (name, json.dumps(props, ensure_ascii=False), now, node_id),
            )
        else:
            self.conn.execute(
                "INSERT INTO nodes(id, type, name, props_json, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (node_id, type_, name, json.dumps(props, ensure_ascii=False), now, now),
            )
        body = " ".join(
            [
                name,
                type_,
                json.dumps(props, ensure_ascii=False),
            ]
        )
        self.conn.execute("DELETE FROM node_fts WHERE id = ?", (node_id,))
        self.conn.execute(
            "INSERT INTO node_fts(id, name, body) VALUES (?,?,?)",
            (node_id, name, body),
        )
        if sources:
            for s in sources:
                self.add_source(node_id, s["kind"], s["uri"], s.get("excerpt", ""))
        self.conn.commit()

    def upsert_edge(
        self,
        edge_id: str,
        src: str,
        rel: str,
        dst: str,
        props: dict[str, Any] | None = None,
        sources: Iterable[dict[str, str]] | None = None,
    ) -> None:
        if rel not in REL_TYPES:
            raise ValueError(f"unknown rel type: {rel}")
        # Ensure endpoints exist (stub if needed)
        for nid, label in ((src, src), (dst, dst)):
            if not self.conn.execute("SELECT 1 FROM nodes WHERE id=?", (nid,)).fetchone():
                self.upsert_node(nid, "event" if nid.startswith("event:") else "document", label, {"stub": True})
        now = _utc_now()
        props = props or {}
        row = self.conn.execute("SELECT id FROM edges WHERE id = ?", (edge_id,)).fetchone()
        if row:
            self.conn.execute(
                "UPDATE edges SET src=?, rel=?, dst=?, props_json=? WHERE id=?",
                (src, rel, dst, json.dumps(props, ensure_ascii=False), edge_id),
            )
        else:
            self.conn.execute(
                "INSERT INTO edges(id, src, rel, dst, props_json, created_at) VALUES (?,?,?,?,?,?)",
                (edge_id, src, rel, dst, json.dumps(props, ensure_ascii=False), now),
            )
        if sources:
            for s in sources:
                self.add_source(edge_id, s["kind"], s["uri"], s.get("excerpt", ""))
        self.conn.commit()

    def add_source(self, target_id: str, kind: str, uri: str, excerpt: str = "") -> None:
        # Incremental: skip duplicate (target, kind, uri). Re-ingest must not inflate source_refs.
        row = self.conn.execute(
            """
            SELECT id FROM source_refs
             WHERE node_or_edge_id=? AND source_kind=? AND source_uri=?
             LIMIT 1
            """,
            (target_id, kind, uri),
        ).fetchone()
        if row:
            # Refresh excerpt/timestamp only when content changed
            self.conn.execute(
                """
                UPDATE source_refs
                   SET excerpt=?, fetched_at=?
                 WHERE id=? AND IFNULL(excerpt,'') != ?
                """,
                (excerpt[:2000], _utc_now(), row["id"], excerpt[:2000]),
            )
            self.conn.commit()
            return
        try:
            self.conn.execute(
                "INSERT INTO source_refs(node_or_edge_id, source_kind, source_uri, excerpt, fetched_at) VALUES (?,?,?,?,?)",
                (target_id, kind, uri, excerpt[:2000], _utc_now()),
            )
        except sqlite3.IntegrityError:
            # Race / pre-existing unique index
            pass
        self.conn.commit()

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if not row:
            return None
        return self._node_dict(row)

    def _node_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "type": row["type"],
            "name": row["name"],
            "props": json.loads(row["props_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "sources": self.sources_for(row["id"]),
        }

    def sources_for(self, target_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT source_kind, source_uri, excerpt, fetched_at FROM source_refs WHERE node_or_edge_id=? ORDER BY id DESC LIMIT 20",
            (target_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def neighbors(self, node_id: str, rel: str | None = None) -> list[dict[str, Any]]:
        if rel:
            rows = self.conn.execute(
                "SELECT * FROM edges WHERE (src=? OR dst=?) AND rel=?",
                (node_id, node_id, rel),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM edges WHERE src=? OR dst=?",
                (node_id, node_id),
            ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "src": r["src"],
                    "rel": r["rel"],
                    "dst": r["dst"],
                    "props": json.loads(r["props_json"] or "{}"),
                    "sources": self.sources_for(r["id"]),
                }
            )
        return out

    def search(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        # FTS with simple token fallback
        q = " ".join(t for t in query.replace("?", " ").split() if len(t) > 1)
        if not q:
            return []
        try:
            rows = self.conn.execute(
                "SELECT id FROM node_fts WHERE node_fts MATCH ? LIMIT ?",
                (q, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = self.conn.execute(
                "SELECT id FROM nodes WHERE name LIKE ? OR props_json LIKE ? LIMIT ?",
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()
        nodes = []
        for r in rows:
            n = self.get_node(r["id"])
            if n:
                nodes.append(n)
        return nodes

    def by_type(self, type_: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM nodes WHERE type=? ORDER BY name", (type_,)).fetchall()
        return [self._node_dict(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        n = self.conn.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"]
        e = self.conn.execute("SELECT COUNT(*) c FROM edges").fetchone()["c"]
        s = self.conn.execute("SELECT COUNT(*) c FROM source_refs").fetchone()["c"]
        by_type = {
            r["type"]: r["c"]
            for r in self.conn.execute(
                "SELECT type, COUNT(*) c FROM nodes GROUP BY type"
            ).fetchall()
        }
        by_kind = {
            r["source_kind"]: r["c"]
            for r in self.conn.execute(
                "SELECT source_kind, COUNT(*) c FROM source_refs GROUP BY source_kind"
            ).fetchall()
        }
        return {
            "db_path": str(self.db_path),
            "nodes": n,
            "edges": e,
            "source_refs": s,
            "nodes_by_type": by_type,
            "sources_by_kind": by_kind,
        }

    def last_successful_ingest(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, started_at, finished_at, status, summary_json
              FROM ingest_runs
             WHERE status IN ('ok','partial') AND finished_at IS NOT NULL
             ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "status": row["status"],
            "summary": json.loads(row["summary_json"] or "{}"),
        }

    def begin_ingest(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO ingest_runs(started_at, status) VALUES (?, ?)",
            (_utc_now(), "running"),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_ingest(self, run_id: int, status: str, summary: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE ingest_runs SET finished_at=?, status=?, summary_json=? WHERE id=?",
            (_utc_now(), status, json.dumps(summary), run_id),
        )
        self.conn.commit()
