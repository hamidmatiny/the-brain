"""The lifecycle gets the upstream 5xx flag from OmniRoute call_logs, not from a hand label."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

FLEET_KG = Path(__file__).resolve().parents[1] / "resources" / "fleet-kg"
sys.path.insert(0, str(FLEET_KG))

from pipelines.upstream_signal import classify_all, upstream_5xx_during  # noqa: E402

T0 = datetime(2026, 10, 8, 16, 30, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def logs(start: datetime, minutes: int, statuses: list[int]) -> list[list]:
    step = timedelta(minutes=minutes) / max(len(statuses), 1)
    return [[iso(start + step * i), s] for i, s in enumerate(statuses)]


def execution(agent: str = "aegis-core-infra", **extra) -> dict:
    return {
        "execution_id": f"ex-{agent}",
        "agent": agent,
        "manager": "aegis-ceo",
        "status": "failed",
        "error": "Task execution timed out after 1800 seconds",
        "started_at": iso(T0),
        "completed_at": iso(T0 + timedelta(minutes=30)),
        "work_finished": False,
        "real_closeout": False,
        **extra,
    }


class UpstreamSignalTest(unittest.TestCase):
    def test_outage_window_classifies_upstream_5xx_not_escalate(self):
        payload = {
            "executions": [execution()],
            "call_logs": logs(T0, 30, [503] * 20 + [504] * 10 + [200] * 10),
        }
        [row] = classify_all(payload)
        self.assertTrue(row["upstream_5xx"])
        self.assertEqual(row["cause"], "upstream_5xx")

    def test_healthy_window_still_escalates(self):
        payload = {"executions": [execution()], "call_logs": logs(T0, 30, [200] * 40 + [503] * 2)}
        [row] = classify_all(payload)
        self.assertFalse(row["upstream_5xx"])
        self.assertEqual(row["cause"], "escalate")

    def test_5xx_outside_the_run_window_do_not_count(self):
        before = logs(T0 - timedelta(hours=2), 30, [503] * 50)
        during = logs(T0, 30, [200] * 20)
        self.assertFalse(upstream_5xx_during(
            [(datetime.strptime(t, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc), s) for t, s in before + during],
            T0, T0 + timedelta(minutes=30),
        )["upstream_5xx"])

    def test_subscription_agents_never_get_the_flag(self):
        payload = {"executions": [execution("aegis-ceo")], "call_logs": logs(T0, 30, [503] * 40)}
        [row] = classify_all(payload)
        self.assertFalse(row["upstream_5xx"])
        self.assertEqual(row["cause"], "escalate")


if __name__ == "__main__":
    unittest.main()
