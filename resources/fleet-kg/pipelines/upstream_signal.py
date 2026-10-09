"""Feed the upstream 5xx signal from OmniRoute call_logs into the run lifecycle.

Before this, nothing set `upstream_5xx` on a real execution, so a run that
failed during a provider outage fell through to `escalate`. This module reads
the call_logs rows inside the run's own time window and sets the flag from them.

OmniRoute rows carry no reliable per-agent key (api_key_name is mostly empty),
so the signal is fleet-wide density inside the window: at least MIN_5XX
responses in {500, 502, 503, 504} and at least MIN_SHARE of all calls in that
window. Subscription agents (aegis-ceo, aegis-redteam) do not route through
OmniRoute, so their runs never get the flag.

Input (stdin JSON), produced on the host from Trinity and OmniRoute:
  {"executions": [{execution_id, agent, manager, status, error, started_at,
                   completed_at, real_closeout, work_finished}],
   "call_logs": [[timestamp, status], ...]}

  python3 resources/fleet-kg/pipelines/upstream_signal.py --store memory/fleet-kg.sqlite < input.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_FLEET_KG = Path(__file__).resolve().parents[1]
if str(_FLEET_KG) not in sys.path:
    sys.path.insert(0, str(_FLEET_KG))

FIVE_XX = (500, 502, 503, 504)
MIN_5XX = 5
MIN_SHARE = 0.30
# A run's own last calls can land a little after the scheduler marks it finished.
SLACK = timedelta(minutes=2)
SUBSCRIPTION = ("aegis-ceo", "aegis-redteam")


def parse_ts(ts: str) -> datetime:
    ts = ts.replace("Z", "")[:19]
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def upstream_5xx_during(events: list[tuple[datetime, int]], start: datetime, end: datetime) -> dict:
    lo, hi = start - SLACK, end + SLACK
    window = [status for ts, status in events if lo <= ts <= hi]
    bad = sum(1 for s in window if s in FIVE_XX)
    share = bad / len(window) if window else 0.0
    return {
        "upstream_5xx": bad >= MIN_5XX and share >= MIN_SHARE,
        "calls": len(window),
        "count_5xx": bad,
        "share_5xx": round(share, 3),
    }


def run_state(execution: dict, events: list[tuple[datetime, int]], store_path: str | None = None) -> dict:
    start = parse_ts(execution["started_at"])
    end = parse_ts(execution["completed_at"]) if execution.get("completed_at") else start
    if execution.get("agent") in SUBSCRIPTION:
        signal = {"upstream_5xx": False, "calls": 0, "count_5xx": 0, "share_5xx": 0.0}
    else:
        signal = upstream_5xx_during(events, start, end)
    state = {
        "execution_id": execution["execution_id"],
        "agent": execution.get("agent", ""),
        "manager": execution.get("manager") or "aegis-ceo",
        "status": execution.get("status", ""),
        "error": execution.get("error") or "",
        "process_registered": execution.get("process_registered", True),
        "upstream_5xx": signal["upstream_5xx"],
        "work_finished": bool(execution.get("work_finished")),
        "real_closeout": bool(execution.get("real_closeout")),
        "retries_used": int(execution.get("retries_used") or 0),
        "route_log": [],
    }
    if store_path:
        state["store_path"] = store_path
    return {"state": state, "signal": signal}


def classify_all(payload: dict, store_path: str | None = None) -> list[dict]:
    from pipelines.run_lifecycle import build_graph

    events = [(parse_ts(ts), int(status)) for ts, status in payload.get("call_logs", [])]
    graph = build_graph()
    out = []
    for ex in payload.get("executions", []):
        built = run_state(ex, events, store_path)
        result = graph.invoke(built["state"], {"configurable": {"thread_id": ex["execution_id"]}})
        out.append({
            "execution_id": ex["execution_id"],
            "agent": ex.get("agent"),
            "cause": result.get("cause"),
            "recommendation": result.get("recommendation"),
            **built["signal"],
        })
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--store", help="fleet-kg sqlite path; omit to classify without writing")
    args = p.parse_args(argv)
    print(json.dumps(classify_all(json.load(sys.stdin), args.store), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
