"""Replay the three Phase 1 loops against 2026-10-08. Observe mode only."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

FLEET_KG = Path(__file__).resolve().parents[1] / "resources" / "fleet-kg"
sys.path.insert(0, str(FLEET_KG))

from pipelines.capacity_loop import build_graph as capacity_graph  # noqa: E402
from pipelines.capability_growth import NO_SI_SCHEDULE, build_graph as growth_graph  # noqa: E402
from pipelines.capability_growth import rotation_for  # noqa: E402
from pipelines.run_lifecycle import build_graph as lifecycle_graph  # noqa: E402

# The 16 trigger-loop executions from 2026-10-08. Causes are the measured ones.
RUNS = [
    {
        "execution_id": "7t5YnCjTf9hBfvqG-OxoIw",
        "agent": "aegis-ceo",
        "manager": "aegis-ceo",
        "status": "failed",
        "error": "Subscription usage limit: session limit",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": False,
        "real_closeout": False,
        "expect": "escalate",
    },
    {
        "execution_id": "gBSqHfxhHvSJv9xdHtetHA",
        "agent": "aegis-infra",
        "manager": "aegis-ceo",
        "status": "success",
        "error": "",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": True,
        "real_closeout": True,
        "expect": "verified",
    },
    {
        "execution_id": "latuarr8_GiLGtAMEURDBQ",
        "agent": "aegis-threat-intel",
        "manager": "aegis-ceo",
        "status": "success",
        "error": "",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": True,
        "real_closeout": True,
        "expect": "verified",
    },
    {
        "execution_id": "6z0QRSmpPbZKC8_SufeC4w",
        "agent": "aegis-analyst",
        "manager": "aegis-ceo",
        "status": "pending_retry",
        "error": "Task execution timed out after 900 seconds",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": True,
        "real_closeout": True,
        "expect": "timeout_after_verified",
    },
    {
        "execution_id": "k3_2ji5O-nGjTqlBJcN7-w",
        "agent": "aegis-core-infra",
        "manager": "aegis-ceo",
        "status": "pending_retry",
        "error": "Task execution timed out after 1800 seconds",
        "process_registered": True,
        "upstream_5xx": True,
        "work_finished": False,
        "real_closeout": False,
        "expect": "upstream_5xx",
    },
    {
        "execution_id": "MYQe-i4sx7mwZrJ9cIQzjg",
        "agent": "aegis-data-quality",
        "manager": "aegis-ceo",
        "status": "pending_retry",
        "error": "Task execution timed out after 3600 seconds",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": False,
        "real_closeout": False,
        "expect": "escalate",
    },
    {
        "execution_id": "PmC0vsGwloTXHOvZ8ySdTw",
        "agent": "the-brain",
        "manager": "aegis-ceo",
        "status": "pending_retry",
        "error": "Task execution timed out after 900 seconds",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": True,
        "real_closeout": False,
        "expect": "post_closeout",
    },
    {
        "execution_id": "gY-taUxr_j6LEnvX8tUQFw",
        "agent": "aegis-growth",
        "manager": "aegis-ceo",
        "status": "pending_retry",
        "error": "Task execution timed out after 900 seconds",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": False,
        "real_closeout": False,
        "expect": "escalate",
    },
    {
        "execution_id": "rxlxIV3Q4tU4enYb_cZqMw",
        "agent": "aegis-scout",
        "manager": "aegis-ceo",
        "status": "failed",
        "error": "Task execution timed out after 3600 seconds",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": False,
        "real_closeout": False,
        "expect": "escalate",
    },
    {
        "execution_id": "qCuVeONc2LWeCIaqcu84Fw",
        "agent": "aegis-product-eng",
        "manager": "aegis-ceo",
        "status": "failed",
        "error": "Task execution timed out after 3600 seconds",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": False,
        "real_closeout": False,
        "expect": "escalate",
    },
    {
        "execution_id": "ecR9fO7fM0VDdJii9cZLrw",
        "agent": "aegis-gateway",
        "manager": "aegis-product-eng",
        "status": "failed",
        "error": "Task execution timed out after 3600 seconds",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": False,
        "real_closeout": False,
        "expect": "escalate",
    },
    {
        "execution_id": "ToC_aDkyzp5qQEOCqDw3Xw",
        "agent": "aegis-policy-engine",
        "manager": "aegis-product-eng",
        "status": "failed",
        "error": "Execution auto-terminated after 60 minutes by watchdog (exceeded timeout of 3600s)",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": False,
        "real_closeout": False,
        "expect": "escalate",
    },
    {
        "execution_id": "aQ1Ktp5V3Ajoj6AfcERwjg",
        "agent": "aegis-model-router",
        "manager": "aegis-product-eng",
        "status": "failed",
        "error": "Task execution timed out after 3600 seconds",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": False,
        "real_closeout": False,
        "expect": "escalate",
    },
    {
        "execution_id": "Ky1WX8YO-4pzh5KF2TqBWA",
        "agent": "aegis-agent-gate",
        "manager": "aegis-product-eng",
        "status": "failed",
        "error": "Task execution timed out after 3600 seconds",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": False,
        "real_closeout": False,
        "expect": "escalate",
    },
    {
        "execution_id": "mPL26QJ61o-WRHgAaZToiQ",
        "agent": "aegis-audit",
        "manager": "aegis-product-eng",
        "status": "failed",
        "error": "Execution completed on agent but status not reported — recovered by watchdog",
        "process_registered": False,
        "upstream_5xx": False,
        "work_finished": False,
        "real_closeout": False,
        "expect": "never_registered",
    },
    {
        "execution_id": "IsTqzxpAkSKHV861a9JTRQ",
        "agent": "aegis-redteam",
        "manager": "aegis-ceo",
        "status": "success",
        "error": "",
        "process_registered": True,
        "upstream_5xx": False,
        "work_finished": True,
        "real_closeout": True,
        "expect": "verified",
    },
]


class LifecycleReplayTest(unittest.TestCase):
    def test_sixteen_runs_follow_their_measured_cause(self):
        self.assertEqual(len(RUNS), 16)
        self.assertNotEqual(os.environ.get("AEGIS_FLEET_GRAPH_LIVE"), "1")
        graph = lifecycle_graph()
        with tempfile.TemporaryDirectory() as tmp:
            for rec in RUNS:
                final = graph.invoke(
                    {k: v for k, v in rec.items() if k != "expect"}
                    | {"store_path": str(Path(tmp) / "fleet.sqlite"), "retries_used": 0},
                    {"configurable": {"thread_id": rec["execution_id"]}},
                )
                self.assertEqual(final["cause"], rec["expect"], rec["agent"])
                self.assertFalse(final["applied"])
                self.assertEqual(final["route_log"][:3], ["start", "running", "classify"])


class GrowthReplayTest(unittest.TestCase):
    def test_next_seven_days_cover_agents_with_no_slot(self):
        plan = rotation_for("2026-10-09", 7)
        self.assertEqual(
            [row["agent"] for row in plan],
            [
                "aegis-agent-gate",
                "aegis-audit",
                "aegis-ceo",
                "aegis-core-infra",
                "aegis-gateway",
                "aegis-model-router",
                "aegis-policy-engine",
            ],
        )
        self.assertEqual([row["date"] for row in plan][0], "2026-10-09")
        self.assertEqual([row["date"] for row in plan][-1], "2026-10-15")
        for name in NO_SI_SCHEDULE:
            self.assertIn(name, [row["agent"] for row in rotation_for("2026-10-09", 16)])

    def test_hold_defers_and_does_not_enable(self):
        graph = growth_graph()
        with tempfile.TemporaryDirectory() as tmp:
            final = graph.invoke(
                {"store_path": str(Path(tmp) / "fleet.sqlite"), "hold_active": True, "start_day": "2026-10-09"},
                {"configurable": {"thread_id": "growth-hold"}},
            )
        self.assertEqual(final["route_log"], ["set-budget", "deferred"])
        self.assertEqual(final["si_budget"], 0)
        self.assertFalse(final["applied"])
        self.assertEqual(len(final["plan"]), 7)

    def test_paid_batch_runs_only_when_guards_pass(self):
        from pipelines.capability_growth import guards_ok

        blocked = {
            "live_requested": True,
            "working_hours": True,
            "paid_slots": 6,
            "hold_active": True,
            "start_day": "2026-10-09",
        }
        self.assertFalse(guards_ok(blocked))
        graph = growth_graph()
        with tempfile.TemporaryDirectory() as tmp:
            closed = graph.invoke(
                blocked | {"store_path": str(Path(tmp) / "fleet.sqlite")},
                {"configurable": {"thread_id": "growth-closed"}},
            )
            open_window = graph.invoke(
                {
                    "store_path": str(Path(tmp) / "fleet.sqlite"),
                    "live_requested": True,
                    "working_hours": False,
                    "subscription_limited": False,
                    "priority_running": False,
                    "track_a": False,
                    "paid_slots": 6,
                    "hold_active": True,
                    "start_day": "2026-10-09",
                },
                {"configurable": {"thread_id": "growth-open"}},
            )
        self.assertEqual(closed["si_budget"], 0)
        self.assertFalse(closed["applied"])
        self.assertEqual(closed["route_log"], ["set-budget", "deferred"])
        self.assertEqual(open_window["si_budget"], 6)
        self.assertTrue(open_window["applied"])
        self.assertEqual(open_window["route_log"][0], "set-budget")
        self.assertIn("pick-skill", open_window["route_log"])


class CapacityReplayTest(unittest.TestCase):
    def test_today_stays_held_and_september_exhaustion_holds(self):
        graph = capacity_graph()
        with tempfile.TemporaryDirectory() as tmp:
            today = graph.invoke(
                {
                    "store_path": str(Path(tmp) / "fleet.sqlite"),
                    "day": "2026-10-08",
                    "tripped": True,
                    "reason": "47 errors in 10 minutes, mostly 503; daily 429 was 4 at the trip",
                    "daily_429": 35,
                    "errors_2h": 47,
                },
                {"configurable": {"thread_id": "cap-today"}},
            )
            sept = graph.invoke(
                {
                    "store_path": str(Path(tmp) / "fleet.sqlite"),
                    "day": "2026-09-25",
                    "tripped": True,
                    "reason": "recorded daily rate-limit count 1315; raw call_logs were rotated",
                    "daily_429": 1315,
                    "errors_2h": 1315,
                },
                {"configurable": {"thread_id": "cap-sept"}},
            )
        self.assertEqual(today["route_log"], ["detect", "hold", "report", "lift-check", "remain"])
        self.assertTrue(today["hold"])
        self.assertFalse(today["lift"])
        self.assertFalse(today["applied"])
        self.assertEqual(sept["route_log"][:2], ["detect", "hold"])
        self.assertFalse(sept["lift"])
        self.assertFalse(sept["applied"])


if __name__ == "__main__":
    unittest.main()
