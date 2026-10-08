"""Capacity loop (Phase 1, observe only).

detect → hold non-critical schedules → report → check the lift condition → resume.

The detect node reads a signal dict the caller measured. It does not toggle
schedules. A hold stays until daily 429 is under 40 and the last two hours
have fewer than 20 errors.
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
from schema import event_id
from store import FleetGraphStore

LIFT_429 = 40
LIFT_2H_ERRORS = 20


def _add(left: list[str] | None, right: list[str] | None) -> list[str]:
    return (left or []) + (right or [])


class CapacityState(TypedDict, total=False):
    store_path: str
    day: str
    tripped: bool
    reason: str
    daily_429: int
    errors_2h: int
    hold: bool
    lift: bool
    applied: bool
    recommendation: str
    route_log: Annotated[list[str], _add]


def _note(state: CapacityState, step: str) -> None:
    path = state.get("store_path")
    if not path:
        return
    store = FleetGraphStore(path)
    try:
        store.upsert_node(
            event_id(f"capacity:{state.get('day')}:{step}"),
            "event",
            step,
            {
                "tripped": state.get("tripped"),
                "reason": state.get("reason"),
                "hold": state.get("hold"),
                "lift": state.get("lift"),
                "applied": False,
            },
        )
    finally:
        store.close()


def detect(state: CapacityState) -> dict[str, Any]:
    _note(state, "detect")
    return {"route_log": ["detect"], "applied": apply_allowed()}


def hold(state: CapacityState) -> dict[str, Any]:
    _note({**state, "hold": True}, "hold")
    return {
        "hold": True,
        "recommendation": "Hold non-critical schedules. Leave aegis-ceo, aegis-redteam, Daily token budget, and Daily allocation running.",
        "applied": False,
        "route_log": ["hold"],
    }


def report(state: CapacityState) -> dict[str, Any]:
    _note(state, "report")
    return {"route_log": ["report"]}


def lift_check(state: CapacityState) -> dict[str, Any]:
    lift = int(state.get("daily_429") or 0) < LIFT_429 and int(state.get("errors_2h") or 0) < LIFT_2H_ERRORS
    _note({**state, "lift": lift}, "lift-check")
    return {"lift": lift, "route_log": ["lift-check"]}


def resume(state: CapacityState) -> dict[str, Any]:
    return {
        "hold": False,
        "recommendation": "Lift condition met. The normal lift may re-enable the paused schedules.",
        "applied": False,
        "route_log": ["resume"],
    }


def remain(state: CapacityState) -> dict[str, Any]:
    return {
        "hold": True,
        "recommendation": "Lift condition is not met. Leave the hold in place. Do not force-lift.",
        "applied": False,
        "route_log": ["remain"],
    }


def clear(state: CapacityState) -> dict[str, Any]:
    return {
        "hold": False,
        "recommendation": "No trip. Do not hold.",
        "applied": False,
        "route_log": ["clear"],
    }


def after_detect(state: CapacityState) -> str:
    if state.get("tripped"):
        return "hold"
    return "clear"


def after_lift(state: CapacityState) -> str:
    if state.get("lift"):
        return "resume"
    return "remain"


def build_graph(checkpointer: MemorySaver | None = None):
    graph = StateGraph(CapacityState)
    graph.add_node("detect", detect)
    graph.add_node("hold", hold)
    graph.add_node("report", report)
    graph.add_node("lift-check", lift_check)
    graph.add_node("resume", resume)
    graph.add_node("remain", remain)
    graph.add_node("clear", clear)
    graph.set_entry_point("detect")
    graph.add_conditional_edges("detect", after_detect, {"hold": "hold", "clear": "clear"})
    graph.add_edge("hold", "report")
    graph.add_edge("report", "lift-check")
    graph.add_conditional_edges("lift-check", after_lift, {"resume": "resume", "remain": "remain"})
    graph.add_edge("resume", END)
    graph.add_edge("remain", END)
    graph.add_edge("clear", END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())
