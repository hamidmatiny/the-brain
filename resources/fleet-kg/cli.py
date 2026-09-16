#!/usr/bin/env python3
"""CLI for fleet knowledge graph ingest/query/stats."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Fleet knowledge graph")
    parser.add_argument("--db", default="", help="SQLite path (default ~/memory/fleet-kg.sqlite)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ingest", help="Pull sources and ingest into the graph")
    q = sub.add_parser("query", help="Ask a grounded question")
    q.add_argument("question", nargs="+", help="Question text")
    sub.add_parser("stats", help="Print graph stats")
    v = sub.add_parser("verify", help="Run Part D verification bundle")
    v.add_argument("--json", action="store_true")

    args = parser.parse_args()
    db = args.db or None

    if args.cmd == "ingest":
        from ingest.pipeline import run_ingest

        summary = run_ingest(db)
        print(json.dumps(summary, indent=2, default=str))
        return 0 if summary.get("status") in ("ok", "partial") else 1

    if args.cmd == "query":
        from query.pipeline import run_query

        question = " ".join(args.question)
        result = run_query(question, db)
        print(result.get("answer") or "")
        print("\n---")
        print(json.dumps({k: result[k] for k in ("status", "intent", "evidence_count")}, indent=2))
        return 0 if result.get("status") == "ok" else 2

    if args.cmd == "stats":
        from store import FleetGraphStore

        store = FleetGraphStore(db)
        print(json.dumps(store.stats(), indent=2))
        store.close()
        return 0

    if args.cmd == "verify":
        from ingest.pipeline import run_ingest
        from query.pipeline import run_query
        from store import FleetGraphStore

        summary = run_ingest(db)
        store = FleetGraphStore(db)
        stats = store.stats()
        # Sample real content from three source kinds
        samples = {}
        for kind in ("agent_repo", "trinity", "slack"):
            row = store.conn.execute(
                "SELECT source_uri, excerpt FROM source_refs WHERE source_kind=? ORDER BY id DESC LIMIT 1",
                (kind,),
            ).fetchone()
            samples[kind] = dict(row) if row else None
        store.close()

        q1 = run_query("who reports to whom", db)
        q2 = run_query("what is aegis-analyst career level and what is blocking promotion", db)
        q3 = run_query("what happened with Protocol B escalation", db)
        q_fail = run_query(
            "what was the Q3 2019 board compensation package for Acme Robotics in Zurich",
            db,
        )

        report = {
            "ingest_status": summary.get("status"),
            "ingest_summary_keys": list((summary or {}).keys()),
            "stats": stats,
            "source_samples": samples,
            "query_org": q1,
            "query_career": q2,
            "query_protocol_b": q3,
            "query_fail_closed": q_fail,
        }
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print("=== INGEST ===")
            print("status:", summary.get("status"))
            print("repo_pull:", json.dumps(summary.get("repo_pull"), indent=2))
            print("slack:", json.dumps(summary.get("slack"), indent=2))
            print("trinity_tasks_ingested:", summary.get("trinity_tasks_ingested"))
            print("stats:", json.dumps(stats, indent=2))
            print("\n=== SOURCE SAMPLES (3 kinds) ===")
            for k, v in samples.items():
                print(f"\n[{k}]")
                print(json.dumps(v, indent=2, default=str)[:800])
            print("\n=== QUERY: org ===\n", q1.get("answer"))
            print("\n=== QUERY: career ===\n", q2.get("answer"))
            print("\n=== QUERY: protocol B ===\n", q3.get("answer"))
            print("\n=== FAIL-CLOSED ===\n", q_fail.get("answer"))
            print("\nfail_closed_status:", q_fail.get("status"))
        ok = (
            summary.get("status") in ("ok", "partial")
            and all(samples.get(k) for k in ("agent_repo", "trinity", "slack"))
            and q1.get("status") == "ok"
            and q_fail.get("status") == "insufficient_data"
        )
        return 0 if ok else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
