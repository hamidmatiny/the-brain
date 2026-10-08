"""Capability-growth loop.

aegis-infra sets the budget (free-pool floor, plus paid headroom when the
guards pass) → aegis-scout picks the skill → the nightly session writes the
change → aegis-ceo approves with before/after evidence → the-brain records it.

A free-pool hold zeros the free slot. Paid headroom still runs only when
Hamid is not in working hours, the Claude subscription is not limited, and
aegis-ceo / aegis-redteam are not using that subscription. Track A is never
a target. With live_requested unset, the graph stays observe-only.
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

from schema import agent_id, event_id
from store import FleetGraphStore

# Agents whose live schedule list had no self-improvement row on 2026-10-08.
NO_SI_SCHEDULE = (
    "aegis-agent-gate",
    "aegis-audit",
    "aegis-ceo",
    "aegis-core-infra",
    "aegis-gateway",
    "aegis-model-router",
    "aegis-policy-engine",
    "aegis-product-eng",
    "aegis-redteam",
    "aegis-scout",
    "the-brain",
)

# Agents that already have an SI schedule. They follow the eleven above.
HAS_SI_SCHEDULE = (
    "aegis-analyst",
    "aegis-data-quality",
    "aegis-growth",
    "aegis-infra",
    "aegis-threat-intel",
)


def rotation() -> list[str]:
    """No-schedule agents first, then agents that already have a slot. Alphabetical inside each group."""
    return list(NO_SI_SCHEDULE) + list(HAS_SI_SCHEDULE)


def rotation_for(start_day: str, days: int = 7) -> list[dict[str, str]]:
    names = rotation()
    year, month, day = (int(p) for p in start_day.split("-"))
    from datetime import date, timedelta

    cursor = date(year, month, day)
    out = []
    for i in range(days):
        out.append({"date": (cursor + timedelta(days=i)).isoformat(), "agent": names[i % len(names)]})
    return out


def _add(left: list[str] | None, right: list[str] | None) -> list[str]:
    return (left or []) + (right or [])


class GrowthState(TypedDict, total=False):
    store_path: str
    hold_active: bool
    si_budget: int
    start_day: str
    plan: list[dict[str, str]]
    due_agent: str
    skill: str
    approval: str
    live_requested: bool
    working_hours: bool
    subscription_limited: bool
    priority_running: bool
    track_a: bool
    paid_slots: int
    applied: bool
    recommendation: str
    route_log: Annotated[list[str], _add]


def _note(state: GrowthState, step: str, props: dict[str, Any]) -> None:
    path = state.get("store_path")
    if not path:
        return
    store = FleetGraphStore(path)
    try:
        store.upsert_node(event_id(f"growth:{step}:{state.get('start_day')}"), "event", step, props)
        store.upsert_node(agent_id("aegis-infra"), "agent", "aegis-infra", {"owns": "whether improvement runs"})
    finally:
        store.close()


def guards_ok(state: GrowthState) -> bool:
    """Live writes only in the measured idle window, and only off the priority path.

    Hamid's working hours, a subscription-limit signal, and a running
    aegis-ceo or aegis-redteam task all keep the graph in observe mode.
    Track A paths are never a growth target.
    """
    if not state.get("live_requested"):
        return False
    if state.get("working_hours") or state.get("subscription_limited") or state.get("priority_running"):
        return False
    if state.get("track_a"):
        return False
    return True


def set_budget(state: GrowthState) -> dict[str, Any]:
    """Free-pool floor is one slot, and zero during a hold.

    Paid headroom is a separate batch. It can run while the free-pool hold
    is active, because it does not draw on OmniRoute. It still obeys the guards.
    """
    free = 0 if state.get("hold_active") else 1
    paid = int(state.get("paid_slots") or 0) if guards_ok(state) else 0
    budget = paid if paid else free
    if state.get("hold_active") and paid == 0:
        budget = 0
    plan = rotation_for(state.get("start_day") or "2026-10-09", 7)
    applied = guards_ok(state) and paid > 0
    _note(state, "set-budget", {"si_budget": budget, "paid_slots": paid, "plan": plan, "applied": applied})
    return {
        "si_budget": budget,
        "plan": plan,
        "due_agent": plan[0]["agent"] if plan else "",
        "applied": applied,
        "route_log": ["set-budget"],
    }


def pick_skill(state: GrowthState) -> dict[str, Any]:
    """Scout's job. Observe mode does not call list_agents or choose a skill body."""
    agent = state.get("due_agent") or ""
    _note(state, "pick-skill", {"agent": agent, "picker": "aegis-scout"})
    return {
        "skill": "",
        "recommendation": f"aegis-scout picks one skill from the live roster for {agent}.",
        "route_log": ["pick-skill"],
    }


def deferred(state: GrowthState) -> dict[str, Any]:
    _note(state, "deferred", {"reason": "capacity hold", "plan": state.get("plan")})
    return {
        "recommendation": "Capacity hold is active. SI budget is 0. The rotation is the plan for after the lift. Do not enable schedules.",
        "applied": False,
        "route_log": ["deferred"],
    }


def run_slot(state: GrowthState) -> dict[str, Any]:
    if state.get("applied"):
        text = (
            f"Nightly session writes Track B skill or script changes for {state.get('due_agent')} "
            "and the rest of the paid batch. It does not touch Track A."
        )
    else:
        text = f"{state.get('due_agent')} would run its SI slot. Guards are closed, so nothing is triggered."
    return {"recommendation": text, "applied": bool(state.get("applied")), "route_log": ["run-slot"]}


def approve(state: GrowthState) -> dict[str, Any]:
    return {
        "recommendation": "aegis-ceo approves or rejects the skill change with before/after evidence.",
        "route_log": ["approve"],
    }


def record(state: GrowthState) -> dict[str, Any]:
    path = state.get("store_path")
    if path:
        store = FleetGraphStore(path)
        try:
            store.upsert_node(agent_id("the-brain"), "agent", "the-brain", {"records": "levels"})
        finally:
            store.close()
    return {
        "recommendation": "the-brain records the skill result and any level change.",
        "route_log": ["record"],
    }


def after_budget(state: GrowthState) -> str:
    if int(state.get("si_budget") or 0) < 1:
        return "deferred"
    return "pick-skill"


def build_graph(checkpointer: MemorySaver | None = None):
    graph = StateGraph(GrowthState)
    graph.add_node("set-budget", set_budget)
    graph.add_node("pick-skill", pick_skill)
    graph.add_node("deferred", deferred)
    graph.add_node("run-slot", run_slot)
    graph.add_node("approve", approve)
    graph.add_node("record", record)
    graph.set_entry_point("set-budget")
    graph.add_conditional_edges(
        "set-budget",
        after_budget,
        {"deferred": "deferred", "pick-skill": "pick-skill"},
    )
    graph.add_edge("deferred", END)
    graph.add_edge("pick-skill", "run-slot")
    graph.add_edge("run-slot", "approve")
    graph.add_edge("approve", "record")
    graph.add_edge("record", END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())
