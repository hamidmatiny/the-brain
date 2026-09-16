"""LangGraph query pipeline with fail-closed answers."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

from schema import agent_id
from store import FleetGraphStore


class QueryState(TypedDict, total=False):
    question: str
    store_path: str
    intent: str
    evidence: list[dict[str, Any]]
    answer: str
    sources: list[dict[str, Any]]
    status: str  # ok | insufficient_data


def _classify(state: QueryState) -> QueryState:
    q = (state.get("question") or "").lower()
    if any(k in q for k in ("report to", "reports to", "who reports", "org chart", "manager")):
        intent = "org_chart"
    elif any(k in q for k in ("career", "level", "promotion", "ladder")):
        intent = "career"
    elif any(k in q for k in ("asked to do", "requested", "what have i", "tasks for", "assigned")):
        intent = "tasks"
    elif any(k in q for k in ("protocol b", "escalat", "what happened", "mrr", "slack close", "stripe")):
        intent = "history"
    else:
        intent = "search"
    return {**state, "intent": intent}


def _agent_mentioned(q: str) -> str | None:
    for name in (
        "aegis-ceo",
        "aegis-infra",
        "aegis-threat-intel",
        "aegis-analyst",
        "aegis-core-infra",
        "aegis-data-quality",
        "aegis-growth",
        "the-brain",
        "hamid",
    ):
        if name in q.lower():
            return name
    return None


def _gather(state: QueryState) -> QueryState:
    store = FleetGraphStore(state.get("store_path") or None)
    intent = state.get("intent") or "search"
    q = state.get("question") or ""
    evidence: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

    if intent == "org_chart":
        for edge_row in store.conn.execute(
            "SELECT * FROM edges WHERE rel='reports_to'"
        ).fetchall():
            evidence.append(
                {
                    "kind": "edge",
                    "src": edge_row["src"],
                    "rel": edge_row["rel"],
                    "dst": edge_row["dst"],
                }
            )
            sources.extend(store.sources_for(edge_row["id"]))

    elif intent == "career":
        agent = _agent_mentioned(q)
        nodes = store.by_type("promotion")
        if agent:
            nodes = [n for n in nodes if n["props"].get("agent") == agent or agent in n["name"]]
        for n in nodes:
            evidence.append(n)
            sources.extend(n.get("sources") or [])
            for e in store.neighbors(n["id"], "blocked_by"):
                evidence.append({"kind": "blocked_by", "edge": e, "blocker": store.get_node(e["dst"])})
                sources.extend(e.get("sources") or [])

    elif intent == "tasks":
        agent = _agent_mentioned(q)
        if not agent:
            store.close()
            return {
                **state,
                "evidence": [],
                "sources": [],
                "status": "insufficient_data",
                "answer": "INSUFFICIENT_DATA: name which agent (e.g. aegis-analyst) when asking what was requested.",
            }
        aid = agent_id(agent)
        for e in store.neighbors(aid, "occurred_in"):
            # task -> occurred_in -> agent  (edge may be either direction depending on ingest)
            other = e["src"] if e["dst"] == aid else e["dst"]
            node = store.get_node(other)
            if node and node["type"] == "task":
                evidence.append(node)
                sources.extend(node.get("sources") or [])
                for req in store.neighbors(node["id"], "requested_by"):
                    evidence.append({"kind": "requested_by", "edge": req, "who": store.get_node(req["dst"] if req["src"] == node["id"] else req["src"])})
                    sources.extend(req.get("sources") or [])

    elif intent == "history":
        # Prefer structured events/escalations + FTS
        for t in ("escalation", "event", "decision"):
            for n in store.by_type(t):
                blob = (n["name"] + " " + str(n.get("props"))).lower()
                if any(tok in blob for tok in re.findall(r"[a-z0-9$-]+", q.lower()) if len(tok) > 3):
                    evidence.append(n)
                    sources.extend(n.get("sources") or [])
        if not evidence:
            evidence.extend(store.search(q, limit=15))
            for n in evidence:
                sources.extend(n.get("sources") or [])

    else:
        evidence.extend(store.search(q, limit=20))
        for n in evidence:
            sources.extend(n.get("sources") or [])

    store.close()
    # Dedup sources by uri
    seen = set()
    uniq_sources = []
    for s in sources:
        key = (s.get("source_kind"), s.get("source_uri"))
        if key in seen:
            continue
        seen.add(key)
        uniq_sources.append(s)

    return {**state, "evidence": evidence, "sources": uniq_sources}


def _answer(state: QueryState) -> QueryState:
    if state.get("status") == "insufficient_data":
        return state
    evidence = state.get("evidence") or []
    sources = state.get("sources") or []
    intent = state.get("intent")
    q = state.get("question") or ""

    if not evidence:
        return {
            **state,
            "status": "insufficient_data",
            "answer": (
                "INSUFFICIENT_DATA: the fleet knowledge graph does not contain grounded evidence "
                f"for this question ({q!r}). I will not invent an answer."
            ),
            "sources": sources,
        }

    lines: list[str] = []
    if intent == "org_chart":
        lines.append("Org / reports-to (from graph edges):")
        for e in evidence:
            if e.get("kind") == "edge" or ("src" in e and "dst" in e and "rel" in e):
                lines.append(f"- {e['src']} —reports_to→ {e['dst']}")
    elif intent == "career":
        lines.append("Career placements found:")
        for n in evidence:
            if n.get("type") == "promotion":
                p = n.get("props") or {}
                lines.append(f"- {p.get('agent')}: {p.get('level')} (since {p.get('since')})")
            elif n.get("kind") == "blocked_by":
                blocker = n.get("blocker") or {}
                lines.append(f"  blocked_by: {blocker.get('name')} — {(blocker.get('props') or {}).get('rule')}")
    elif intent == "tasks":
        lines.append("Tasks / executions linked to this agent:")
        for n in evidence:
            if n.get("type") == "task":
                p = n.get("props") or {}
                lines.append(
                    f"- exec {p.get('execution_id')} status={p.get('status')} "
                    f"triggered_by={p.get('triggered_by')} excerpt={p.get('message_excerpt', '')[:120]!r}"
                )
            elif n.get("kind") == "requested_by":
                who = n.get("who") or {}
                lines.append(f"  requested_by: {who.get('name') or who.get('id')}")
    else:
        lines.append("Grounded hits:")
        for n in evidence[:12]:
            if "type" in n:
                lines.append(f"- [{n['type']}] {n['name']} props={n.get('props')}")
            else:
                lines.append(f"- {n}")

    if sources:
        lines.append("")
        lines.append("Sources:")
        for s in sources[:12]:
            lines.append(f"- ({s.get('source_kind')}) {s.get('source_uri')}")
            if s.get("excerpt"):
                lines.append(f"  excerpt: {s['excerpt'][:160]!r}")

    return {
        **state,
        "status": "ok",
        "answer": "\n".join(lines),
        "sources": sources,
    }


def build_query_graph():
    g = StateGraph(QueryState)
    g.add_node("classify", RunnableLambda(_classify))
    g.add_node("gather", RunnableLambda(_gather))
    g.add_node("answer", RunnableLambda(_answer))
    g.set_entry_point("classify")
    g.add_edge("classify", "gather")
    g.add_edge("gather", "answer")
    g.add_edge("answer", END)
    return g.compile()


def run_query(question: str, store_path: str | None = None) -> dict[str, Any]:
    app = build_query_graph()
    result = app.invoke({"question": question, "store_path": store_path or ""})
    return {
        "status": result.get("status"),
        "intent": result.get("intent"),
        "answer": result.get("answer"),
        "sources": result.get("sources") or [],
        "evidence_count": len(result.get("evidence") or []),
    }
