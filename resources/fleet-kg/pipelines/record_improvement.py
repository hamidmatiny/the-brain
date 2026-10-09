"""Record a merged nightly improvement in the fleet knowledge graph.

The host nightly runner (aegis-infra scripts/nightly_runner.py) calls this
after aegis-ceo merges an improvement PR, and again when the next real run
holds or reverts it. One decision node per PR; re-recording updates it.

  echo '{"agent": ..., "pr": ..., "status": "deployed", ...}' | \
    python3 resources/fleet-kg/pipelines/record_improvement.py --store memory/fleet-kg.sqlite
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_FLEET_KG = Path(__file__).resolve().parents[1]
if str(_FLEET_KG) not in sys.path:
    sys.path.insert(0, str(_FLEET_KG))

from schema import agent_id  # noqa: E402
from store import FleetGraphStore  # noqa: E402

KEEP = ("agent", "pr", "night", "status", "summary", "merge_commit", "merged_at", "deployed_at",
        "files", "lines", "next_run", "revert_reason", "session_minutes", "session_tokens")


def improvement_id(pr_url: str) -> str:
    # https://github.com/<owner>/<repo>/pull/<n> -> decision:improvement:<repo>#<n>
    parts = pr_url.rstrip("/").split("/")
    return f"decision:improvement:{parts[-3]}#{parts[-1]}"


def record(store: FleetGraphStore, entry: dict) -> str:
    if not entry.get("agent") or not entry.get("pr"):
        raise ValueError("entry needs agent and pr")
    nid = improvement_id(entry["pr"])
    props = {k: entry[k] for k in KEEP if k in entry}
    props["kind"] = "nightly_improvement"
    source = [{"kind": "github_pr", "uri": entry["pr"], "excerpt": entry.get("summary", "")}]
    store.upsert_node(agent_id(entry["agent"]), "agent", entry["agent"], {})
    store.upsert_node(nid, "decision", f"{entry['agent']} improvement {entry['pr'].rsplit('/', 1)[-1]}", props, source)
    store.upsert_edge(f"edge:{nid}:resulted_in", agent_id(entry["agent"]), "resulted_in", nid,
                      {"status": entry.get("status")}, source)
    return nid


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--store", required=True)
    args = p.parse_args(argv)
    entries = json.load(sys.stdin)
    entries = entries if isinstance(entries, list) else [entries]
    store = FleetGraphStore(args.store)
    try:
        ids = [record(store, e) for e in entries]
    finally:
        store.close()
    print(json.dumps({"recorded": ids}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
