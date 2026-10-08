"""Agent-run lifecycle (Phase 1, observe only).

start → running → finished → verified real close-out.

On a failure the edge is the cause already on the execution record:
process never registered, upstream 5xx, timeout after the work finished,
or escalate to the agent's manager and then aegis-ceo.

The nodes do not retry, post, or trigger. They write the recommendation
into the fleet knowledge graph.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

_FLEET_KG = Path(__file__).resolve().parents[1]
if str(_FLEET_KG) not in sys.path:
    sys.path.insert(0, str(_FLEET_KG))

from pipelines.observe import apply_allowed
from schema import agent_id, event_id, task_id
from store import FleetGraphStore


def _add(left: list[str] | None, right: list[str] | None) -> list[str]:
    return (left or []) + (right or [])


class RunState(TypedDict, total=False):
    store_path: str
    execution_id: str
    agent: str
    manager: str
    status: str
    error: str
    process_registered: bool
    upstream_5xx: bool
    work_finished: bool
    real_closeout: bool
    retries_used: int
    cause: str
    recommendation: str
    applied: bool
    route_log: Annotated[list[str], _add]


def _store(state: RunState) -> FleetGraphStore | None:
    path = state.get("store_path")
    if not path:
        return None
    return FleetGraphStore(path)


def _note(state: RunState, step: str) -> None:
    store = _store(state)
    if store is None:
        return
    try:
        eid = state.get("execution_id") or "unknown"
        store.upsert_node(
            task_id(eid),
            "task",
            f"{state.get('agent')} {eid}",
            {"status": state.get("status"), "cause": state.get("cause"), "step": step},
        )
        store.upsert_node(
            event_id(f"lifecycle:{eid}:{step}"),
            "event",
            step,
            {"recommendation": state.get("recommendation"), "applied": False},
        )
    finally:
        store.close()


def start(state: RunState) -> dict[str, Any]:
    return {"route_log": ["start"], "applied": apply_allowed()}


def running(state: RunState) -> dict[str, Any]:
    _note(state, "running")
    return {"route_log": ["running"]}


def classify(state: RunState) -> dict[str, Any]:
    """Pick the edge from fields already on the execution. Does not infer a cause."""
    status = state.get("status") or ""
    error = state.get("error") or ""
    if status == "running":
        cause = "still_running"
    elif status == "success" and state.get("real_closeout"):
        cause = "verified"
    elif state.get("process_registered") is False or "status not reported" in error:
        cause = "never_registered"
    elif state.get("upstream_5xx"):
        cause = "upstream_5xx"
    elif "timed out" in error or "exceeded timeout" in error:
        if state.get("work_finished") and state.get("real_closeout"):
            cause = "timeout_after_verified"
        elif state.get("work_finished") and not state.get("real_closeout"):
            cause = "post_closeout"
        else:
            cause = "escalate"
    else:
        cause = "escalate"
    _note({**state, "cause": cause}, "classify")
    return {"cause": cause, "route_log": ["classify"]}


def _recommend(state: RunState, cause: str, text: str) -> dict[str, Any]:
    out = {
        "cause": cause,
        "recommendation": text,
        "applied": False,
        "route_log": [cause],
    }
    _note({**state, **out}, cause)
    return out


def verified(state: RunState) -> dict[str, Any]:
    return _recommend(state, "verified", "Real close-out is already on the execution. No retry.")


def diagnose_platform(state: RunState) -> dict[str, Any]:
    used = int(state.get("retries_used") or 0)
    text = (
        "Process never registered. Diagnose the platform dispatcher and retry once."
        if used < 1
        else "Process never registered and the one retry is already used. Escalate."
    )
    return _recommend(state, "never_registered", text)


def backoff_retry(state: RunState) -> dict[str, Any]:
    used = int(state.get("retries_used") or 0)
    text = (
        "Upstream 5xx. Back off and retry once."
        if used < 1
        else "Upstream 5xx and the one retry is already used. Escalate."
    )
    return _recommend(state, "upstream_5xx", text)


def post_closeout(state: RunState) -> dict[str, Any]:
    return _recommend(
        state,
        "post_closeout",
        "Work finished and the real Slack send is missing. Post the close-out from this state. Do not rerun the task.",
    )


def timeout_after_verified(state: RunState) -> dict[str, Any]:
    return _recommend(
        state,
        "timeout_after_verified",
        "Work finished and the real close-out is already posted. The timeout fired afterward. Lengthen the schedule timeout. Do not rerun the task.",
    )


def escalate(state: RunState) -> dict[str, Any]:
    manager = state.get("manager") or "aegis-ceo"
    store = _store(state)
    if store is not None:
        try:
            store.upsert_node(agent_id(manager), "agent", manager, {})
            store.upsert_node(agent_id("aegis-ceo"), "agent", "aegis-ceo", {})
            store.upsert_edge(
                f"edge:lifecycle:{state.get('execution_id')}:escalated_to",
                task_id(state.get("execution_id") or "unknown"),
                "escalated_to",
                agent_id(manager),
                {"then": "aegis-ceo"},
            )
        finally:
            store.close()
    return _recommend(
        state,
        "escalate",
        f"Escalate to {manager}, then aegis-ceo. No automatic retry.",
    )


def after_classify(state: RunState) -> str:
    cause = state.get("cause") or "escalate"
    if cause == "still_running":
        return END
    return {
        "verified": "verified",
        "never_registered": "diagnose-platform",
        "upstream_5xx": "backoff-retry",
        "post_closeout": "post-closeout",
        "timeout_after_verified": "timeout-after-verified",
        "escalate": "escalate",
    }.get(cause, "escalate")


def build_graph(checkpointer: MemorySaver | None = None):
    graph = StateGraph(RunState)
    graph.add_node("start", start)
    graph.add_node("running", running)
    graph.add_node("classify", classify)
    graph.add_node("verified", verified)
    graph.add_node("diagnose-platform", diagnose_platform)
    graph.add_node("backoff-retry", backoff_retry)
    graph.add_node("post-closeout", post_closeout)
    graph.add_node("timeout-after-verified", timeout_after_verified)
    graph.add_node("escalate", escalate)
    graph.set_entry_point("start")
    graph.add_edge("start", "running")
    graph.add_edge("running", "classify")
    graph.add_conditional_edges(
        "classify",
        after_classify,
        {
            "verified": "verified",
            "diagnose-platform": "diagnose-platform",
            "backoff-retry": "backoff-retry",
            "post-closeout": "post-closeout",
            "timeout-after-verified": "timeout-after-verified",
            "escalate": "escalate",
            END: END,
        },
    )
    for node in (
        "verified",
        "diagnose-platform",
        "backoff-retry",
        "post-closeout",
        "timeout-after-verified",
        "escalate",
    ):
        graph.add_edge(node, END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())
