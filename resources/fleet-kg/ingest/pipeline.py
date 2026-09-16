"""LangGraph ingest pipeline: repos + Trinity + Slack + historical facts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, TypedDict

# Allow running as script from resources/fleet-kg
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

from access import repos as repos_access
from access import slack as slack_access
from access import trinity as trinity_access
from schema import (
    agent_id,
    dept_id,
    document_id,
    escalation_id,
    event_id,
    promotion_id,
    skill_id,
    slack_msg_id,
    task_id,
)
from store import FleetGraphStore

# Org chart from a2a-routing.md (also ingested as document)
DEPARTMENTS = {
    "executive": ["aegis-ceo", "the-brain"],
    "infrastructure-compute": ["aegis-infra"],
    "cybersecurity": ["aegis-threat-intel"],
    "finance": ["aegis-analyst"],
    "engineering": ["aegis-core-infra"],
    "data-quality": ["aegis-data-quality"],
    "growth": ["aegis-growth"],
}

MANAGER = {
    "aegis-ceo": "hamid",  # founder-facing
    "the-brain": "aegis-ceo",
    "aegis-infra": "aegis-ceo",
    "aegis-threat-intel": "aegis-ceo",
    "aegis-analyst": "aegis-ceo",
    "aegis-core-infra": "aegis-ceo",
    "aegis-data-quality": "aegis-ceo",
    "aegis-growth": "aegis-ceo",
}


class IngestState(TypedDict, total=False):
    store_path: str
    summary: dict[str, Any]
    errors: list[str]
    pull: dict[str, Any]
    agents_seen: list[str]


def _src(kind: str, uri: str, excerpt: str = "") -> dict[str, str]:
    return {"kind": kind, "uri": uri, "excerpt": excerpt[:500]}


def node_pull_repos(state: IngestState) -> IngestState:
    errors = list(state.get("errors") or [])
    summary = dict(state.get("summary") or {})
    try:
        pull = repos_access.pull_all()
        summary["repo_pull"] = {
            "ok": pull["ok"],
            "shas": pull.get("shas"),
            "returncode": pull.get("returncode"),
            "stderr_tail": (pull.get("stderr") or "")[-500:],
        }
        if not pull["ok"]:
            errors.append("repo_pull_failed")
        return {**state, "pull": pull, "summary": summary, "errors": errors}
    except Exception as e:
        errors.append(f"repo_pull:{e}")
        summary["repo_pull"] = {"ok": False, "error": str(e)}
        return {**state, "summary": summary, "errors": errors}


def node_ingest_org(state: IngestState) -> IngestState:
    store = FleetGraphStore(state.get("store_path"))
    summary = dict(state.get("summary") or {})
    errors = list(state.get("errors") or [])
    agents_seen: list[str] = []

    # Hamid as human principal
    store.upsert_node(
        "agent:hamid",
        "agent",
        "Hamid",
        {"role": "founder", "human": True},
        [_src("manual", "fleet-kg:principal", "Founder / final authority")],
    )

    # Departments + agents from live Trinity when possible
    live_names: list[str] = []
    try:
        for a in trinity_access.list_agents():
            name = a.get("name")
            if name and name != "trinity-system":
                live_names.append(name)
    except Exception as e:
        errors.append(f"trinity_list_agents:{e}")
        live_names = list(MANAGER.keys())

    for dept, members in DEPARTMENTS.items():
        did = dept_id(dept)
        store.upsert_node(
            did,
            "department",
            dept,
            {},
            [_src("agent_repo", "repo://aegis-infra/docs/a2a-routing.md", f"branch {dept}")],
        )
        for m in members:
            if m not in live_names and m not in MANAGER:
                continue
            aid = agent_id(m)
            store.upsert_node(
                aid,
                "agent",
                m,
                {"status": "live" if m in live_names else "configured"},
                [_src("trinity", f"trinity://agents/{m}", "list_agents")],
            )
            store.upsert_edge(
                f"edge:{aid}:member_of:{did}",
                aid,
                "member_of",
                did,
                sources=[_src("agent_repo", "repo://aegis-infra/docs/a2a-routing.md", dept)],
            )
            mgr = MANAGER.get(m)
            if mgr:
                store.upsert_edge(
                    f"edge:{aid}:reports_to:{agent_id(mgr)}",
                    aid,
                    "reports_to",
                    agent_id(mgr),
                    sources=[_src("agent_repo", "repo://aegis-infra/docs/a2a-routing.md", f"{m}→{mgr}")],
                )
            agents_seen.append(m)

    # Skills from CLAUDE.md / skill dirs when repos present
    for repo in repos_access.FLEET_REPOS:
        claude = repos_access.read_text(repo, "CLAUDE.md")
        if claude.get("ok"):
            doc = document_id(repo, "CLAUDE.md")
            store.upsert_node(
                doc,
                "document",
                f"{repo}/CLAUDE.md",
                {"sha": claude.get("sha"), "chars": len(claude.get("text") or "")},
                [_src("agent_repo", claude["uri"], (claude.get("text") or "")[:240])],
            )
            store.upsert_edge(
                f"edge:{agent_id(repo)}:cites:{doc}",
                agent_id(repo),
                "cites",
                doc,
                sources=[_src("agent_repo", claude["uri"], "identity")],
            )
        # career ladder doc on ceo
        if repo == "aegis-ceo":
            ladder = repos_access.read_text(repo, "docs/career-ladder.md")
            if ladder.get("ok"):
                doc = document_id(repo, "docs/career-ladder.md")
                store.upsert_node(
                    doc,
                    "document",
                    "career-ladder.md",
                    {"sha": ladder.get("sha")},
                    [_src("agent_repo", ladder["uri"], (ladder.get("text") or "")[:300])],
                )
                _ingest_career_ladder(store, ladder["text"], ladder["uri"])

        for mem_path in repos_access.list_memory_files(repo):
            mem = repos_access.read_text(repo, mem_path)
            if not mem.get("ok"):
                continue
            doc = document_id(repo, mem_path)
            store.upsert_node(
                doc,
                "document",
                f"{repo}/{mem_path}",
                {"sha": mem.get("sha")},
                [_src("agent_repo", mem["uri"], (mem.get("text") or "")[:300])],
            )

        # skill directories
        skills_root = repos_access.KNOWLEDGE_ROOT / repo / ".claude" / "skills"
        if skills_root.is_dir():
            for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
                sid = skill_id(repo, skill_dir.name)
                store.upsert_node(
                    sid,
                    "skill",
                    f"/{skill_dir.name}",
                    {"agent": repo},
                    [_src("agent_repo", f"repo://{repo}/.claude/skills/{skill_dir.name}/SKILL.md", skill_dir.name)],
                )
                store.upsert_edge(
                    f"edge:{agent_id(repo)}:has_skill:{sid}",
                    agent_id(repo),
                    "has_skill",
                    sid,
                    sources=[_src("agent_repo", f"repo://{repo}/.claude/skills/{skill_dir.name}", "")],
                )

    summary["org_agents"] = sorted(set(agents_seen))
    store.close()
    return {**state, "summary": summary, "errors": errors, "agents_seen": sorted(set(agents_seen))}


def _ingest_career_ladder(store: FleetGraphStore, text: str, uri: str) -> None:
    # Parse table rows like: | aegis-ceo | SE II (interim) | 2026-09-15 | ...
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 4:
            continue
        agent, level, since = cols[0], cols[1], cols[2]
        if agent.startswith("Agent") or agent.startswith("---") or " " in agent and agent not in MANAGER:
            # skip header; allow known agents only
            pass
        if agent not in MANAGER and agent != "the-brain":
            continue
        pid = promotion_id(agent, since)
        store.upsert_node(
            pid,
            "promotion",
            f"{agent} @ {level}",
            {"agent": agent, "level": level, "since": since, "evidence": cols[3] if len(cols) > 3 else ""},
            [_src("agent_repo", uri, line[:240])],
        )
        store.upsert_edge(
            f"edge:{agent_id(agent)}:has_level:{pid}",
            agent_id(agent),
            "has_level",
            pid,
            sources=[_src("agent_repo", uri, f"{agent}={level}")],
        )
        # blocking next promotion — from ladder text: need ≥20 successful unattended executions
        store.upsert_edge(
            f"edge:{pid}:blocked_by:{event_id('promotion-sample-size')}",
            pid,
            "blocked_by",
            event_id("promotion-sample-size"),
            props={"reason": "First promotion evaluations after ≥20 successful unattended core-schedule executions"},
            sources=[_src("agent_repo", uri, "First promotion evaluations")],
        )
    store.upsert_node(
        event_id("promotion-sample-size"),
        "event",
        "Promotion sample-size gate",
        {"rule": "≥20 successful unattended core-schedule executions before first promotion eval"},
        [_src("agent_repo", uri, "First promotion evaluations")],
    )


def node_ingest_trinity(state: IngestState) -> IngestState:
    store = FleetGraphStore(state.get("store_path"))
    summary = dict(state.get("summary") or {})
    errors = list(state.get("errors") or [])
    count = 0
    agents = state.get("agents_seen") or list(MANAGER.keys())
    for name in agents:
        try:
            execs = trinity_access.list_executions(name, limit=40)
        except Exception as e:
            errors.append(f"executions:{name}:{e}")
            continue
        for ex in execs:
            eid = ex.get("id") or ex.get("execution_id")
            if not eid:
                continue
            tid = task_id(eid)
            msg = (ex.get("message") or "")[:500]
            store.upsert_node(
                tid,
                "task",
                f"{name}:{eid[:8]}",
                {
                    "execution_id": eid,
                    "agent": name,
                    "status": ex.get("status"),
                    "triggered_by": ex.get("triggered_by") or ex.get("schedule_id"),
                    "started_at": ex.get("started_at"),
                    "completed_at": ex.get("completed_at"),
                    "duration_ms": ex.get("duration_ms"),
                    "message_excerpt": msg,
                },
                [_src("trinity", f"trinity://agents/{name}/executions/{eid}", msg)],
            )
            store.upsert_edge(
                f"edge:{tid}:occurred_in:{agent_id(name)}",
                tid,
                "occurred_in",
                agent_id(name),
                sources=[_src("trinity", f"trinity://agents/{name}/executions/{eid}", "")],
            )
            # requested_by heuristic
            trig = (ex.get("triggered_by") or "")
            src_agent = ex.get("source_agent")
            if src_agent:
                store.upsert_edge(
                    f"edge:{tid}:requested_by:{agent_id(src_agent)}",
                    tid,
                    "requested_by",
                    agent_id(src_agent),
                    sources=[_src("trinity", f"trinity://agents/{name}/executions/{eid}", f"source_agent={src_agent}")],
                )
            elif trig == "manual" or (isinstance(msg, str) and msg.startswith("Hamid:")):
                store.upsert_edge(
                    f"edge:{tid}:requested_by:agent:hamid",
                    tid,
                    "requested_by",
                    "agent:hamid",
                    sources=[_src("trinity", f"trinity://agents/{name}/executions/{eid}", "manual/Hamid")],
                )
            count += 1
        try:
            schedules = trinity_access.list_schedules(name)
            for sch in schedules if isinstance(schedules, list) else []:
                sid = sch.get("id") or sch.get("schedule_id") or sch.get("name")
                if not sid:
                    continue
                nid = event_id(f"schedule:{name}:{sid}")
                store.upsert_node(
                    nid,
                    "event",
                    f"schedule:{name}:{sid}",
                    {
                        "agent": name,
                        "enabled": sch.get("enabled"),
                        "cron": sch.get("cron") or sch.get("schedule"),
                        "skill": sch.get("skill") or sch.get("command") or sch.get("message"),
                    },
                    [_src("trinity", f"trinity://agents/{name}/schedules/{sid}", json.dumps(sch)[:240])],
                )
        except Exception as e:
            errors.append(f"schedules:{name}:{e}")
    summary["trinity_tasks_ingested"] = count
    store.close()
    return {**state, "summary": summary, "errors": errors}


def node_ingest_slack(state: IngestState) -> IngestState:
    store = FleetGraphStore(state.get("store_path"))
    summary = dict(state.get("summary") or {})
    errors = list(state.get("errors") or [])
    try:
        hist = slack_access.load_history(prefer_live=True, limit=50)
    except Exception as e:
        errors.append(f"slack:{e}")
        summary["slack"] = {"ok": False, "error": str(e)}
        store.close()
        return {**state, "summary": summary, "errors": errors}

    n = 0
    for ch_name, payload in (hist.get("channels") or {}).items():
        if not payload.get("ok", True) and not payload.get("messages"):
            errors.append(f"slack_channel:{ch_name}:{payload.get('error')}")
            continue
        for m in payload.get("messages") or []:
            ts = m.get("ts")
            if not ts:
                continue
            mid = slack_msg_id(ch_name, ts)
            text = m.get("text") or ""
            store.upsert_node(
                mid,
                "event",
                f"slack:{ch_name}:{ts}",
                {
                    "channel": ch_name,
                    "channel_id": m.get("channel_id") or payload.get("channel_id"),
                    "ts": ts,
                    "thread_ts": m.get("thread_ts"),
                    "text": text[:2000],
                },
                [
                    _src(
                        "slack",
                        f"slack://{ch_name}/{ts}",
                        text[:300],
                    )
                ],
            )
            # Bind to agent channel owner when channel name matches agent
            if ch_name in MANAGER or ch_name == "the-brain":
                store.upsert_edge(
                    f"edge:{mid}:occurred_in:{agent_id(ch_name)}",
                    mid,
                    "occurred_in",
                    agent_id(ch_name),
                    sources=[_src("slack", f"slack://{ch_name}/{ts}", "")],
                )
            n += 1
            # Protocol B markers
            if "Protocol B" in text or "Uncertainty" in text:
                esc = escalation_id(f"protocol-b:{ch_name}:{ts}")
                store.upsert_node(
                    esc,
                    "escalation",
                    "Protocol B escalation signal",
                    {"channel": ch_name, "ts": ts},
                    [_src("slack", f"slack://{ch_name}/{ts}", text[:300])],
                )
                store.upsert_edge(
                    f"edge:{esc}:escalated_to:{agent_id('aegis-ceo') if ch_name != 'aegis-ceo' else 'agent:hamid'}",
                    esc,
                    "escalated_to",
                    agent_id("aegis-ceo") if ch_name != "aegis-ceo" else "agent:hamid",
                    sources=[_src("slack", f"slack://{ch_name}/{ts}", "Protocol B")],
                )
    summary["slack"] = {"ok": True, "mode": hist.get("mode"), "messages": n, "fetched_at": hist.get("fetched_at")}
    store.close()
    return {**state, "summary": summary, "errors": errors}


def node_ingest_historical(state: IngestState) -> IngestState:
    """Seed real historical events from known committed sources (not synthetic)."""
    store = FleetGraphStore(state.get("store_path"))
    summary = dict(state.get("summary") or {})

    # 1) Protocol B test — from aegis-infra memory
    proto = repos_access.read_text("aegis-infra", "memory/protocol-b-test-2026-09-16.md")
    if proto.get("ok"):
        eid = event_id("protocol-b-verification-2026-09-16")
        store.upsert_node(
            eid,
            "event",
            "Protocol B verification test",
            {
                "kind": "protocol_b_test",
                "verdict": "PASS",
                "ceo_exec": "bg7hC9TasPBEObSN68ItYQ",
                "analyst_exec": "OIk0DCvxusJKMiT-vKk3bw",
                "synthetic": True,
            },
            [_src("agent_repo", proto["uri"], (proto.get("text") or "")[:400])],
        )
        esc = escalation_id("protocol-b-test-2026-09-16")
        store.upsert_node(
            esc,
            "escalation",
            "Protocol B synthetic BEV$0 vs Stripe$29",
            {"synthetic": True, "slack_channel": "C0C10JBBETZ"},
            [_src("agent_repo", proto["uri"], "Ambiguous judgment call")],
        )
        store.upsert_edge(
            f"edge:{esc}:requested_by:{agent_id('aegis-analyst')}",
            esc,
            "requested_by",
            agent_id("aegis-analyst"),
            sources=[_src("agent_repo", proto["uri"], "Analyst → CEO")],
        )
        store.upsert_edge(
            f"edge:{esc}:escalated_to:{agent_id('aegis-ceo')}",
            esc,
            "escalated_to",
            agent_id("aegis-ceo"),
            sources=[_src("agent_repo", proto["uri"], "chat_with_agent")],
        )
        store.upsert_edge(
            f"edge:{esc}:escalated_to:agent:hamid",
            esc,
            "escalated_to",
            "agent:hamid",
            props={"via": "Slack #aegis-ceo"},
            sources=[_src("agent_repo", proto["uri"], "CEO → Hamid Slack")],
        )
        store.upsert_edge(
            f"edge:{esc}:resulted_in:{eid}",
            esc,
            "resulted_in",
            eid,
            sources=[_src("agent_repo", proto["uri"], "PASS")],
        )

    # 2) MRR corrected to $0 — from pm-board / career-ladder evidence
    for path in ("docs/pm-board.md", "docs/career-ladder.md"):
        doc = repos_access.read_text("aegis-ceo", path)
        if not doc.get("ok"):
            continue
        if "MRR" in (doc.get("text") or "") or "$0" in (doc.get("text") or ""):
            ev = event_id("mrr-narrative-corrected-2026-09-15")
            store.upsert_node(
                ev,
                "event",
                "MRR/signup narrative corrected to $0",
                {"kind": "mrr_fix", "mrr_cad": 0, "as_of": "2026-09-15"},
                [_src("agent_repo", doc["uri"], _excerpt_matching(doc["text"], "MRR", 280))],
            )
            store.upsert_edge(
                f"edge:{ev}:occurred_in:{agent_id('aegis-ceo')}",
                ev,
                "occurred_in",
                agent_id("aegis-ceo"),
                sources=[_src("agent_repo", doc["uri"], "")],
            )
            break

    # 3) Slack-reporting / close-out HARD GATE — from CLAUDE.md presence
    for repo in ("aegis-ceo", "aegis-infra", "aegis-analyst"):
        claude = repos_access.read_text(repo, "CLAUDE.md")
        if claude.get("ok") and "HARD GATE — Slack completed-task close-out" in (claude.get("text") or ""):
            ev = event_id("slack-closeout-hard-gate")
            store.upsert_node(
                ev,
                "decision",
                "Universal Slack completed-task close-out HARD GATE",
                {"kind": "slack_reporting_fix"},
                [_src("agent_repo", claude["uri"], "HARD GATE — Slack completed-task close-out")],
            )
            store.upsert_edge(
                f"edge:{ev}:occurred_in:{agent_id(repo)}",
                ev,
                "occurred_in",
                agent_id(repo),
                sources=[_src("agent_repo", claude["uri"], "")],
            )

    # 4) Fleet capability / foundation work pointer — skill proposals memory
    skills = repos_access.read_text("aegis-infra", "memory/skill-proposals.md")
    if skills.get("ok"):
        ev = event_id("fleet-capability-verification-loop")
        store.upsert_node(
            ev,
            "event",
            "Revenue claim independent verification loop",
            {"kind": "capability"},
            [_src("agent_repo", skills["uri"], _excerpt_matching(skills["text"], "verify-revenue", 280))],
        )

    summary["historical_seeded"] = True
    store.close()
    return {**state, "summary": summary}


def _excerpt_matching(text: str, needle: str, n: int) -> str:
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return text[:n]
    start = max(0, idx - 40)
    return text[start : start + n]


def node_finish(state: IngestState) -> IngestState:
    store = FleetGraphStore(state.get("store_path"))
    summary = dict(state.get("summary") or {})
    summary["graph_stats"] = store.stats()
    errors = state.get("errors") or []
    status = "ok" if not errors else "partial"
    # Partial is acceptable when some sources work; total failure only if nothing landed
    stats = summary["graph_stats"]
    if stats.get("nodes", 0) < 5:
        status = "failed"
    run_id = store.begin_ingest()
    store.finish_ingest(run_id, status, summary)
    store.close()
    summary["status"] = status
    summary["errors"] = errors
    return {**state, "summary": summary}


def build_ingest_graph():
    g = StateGraph(IngestState)
    g.add_node("pull_repos", RunnableLambda(node_pull_repos))
    g.add_node("ingest_org", RunnableLambda(node_ingest_org))
    g.add_node("ingest_trinity", RunnableLambda(node_ingest_trinity))
    g.add_node("ingest_slack", RunnableLambda(node_ingest_slack))
    g.add_node("ingest_historical", RunnableLambda(node_ingest_historical))
    g.add_node("finish", RunnableLambda(node_finish))
    g.set_entry_point("pull_repos")
    g.add_edge("pull_repos", "ingest_org")
    g.add_edge("ingest_org", "ingest_trinity")
    g.add_edge("ingest_trinity", "ingest_slack")
    g.add_edge("ingest_slack", "ingest_historical")
    g.add_edge("ingest_historical", "finish")
    g.add_edge("finish", END)
    return g.compile()


def run_ingest(store_path: str | None = None) -> dict[str, Any]:
    app = build_ingest_graph()
    result = app.invoke({"store_path": store_path or "", "summary": {}, "errors": []})
    return result.get("summary") or {}
