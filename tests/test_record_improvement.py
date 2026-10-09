from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

FLEET_KG = Path(__file__).resolve().parents[1] / "resources" / "fleet-kg"
sys.path.insert(0, str(FLEET_KG))

from pipelines.record_improvement import improvement_id, record  # noqa: E402
from store import FleetGraphStore  # noqa: E402

PR = "https://github.com/hamidmatiny/aegis-analyst/pull/1"


class RecordImprovementTest(unittest.TestCase):
    def test_merged_improvement_is_a_decision_linked_to_the_agent(self):
        with tempfile.TemporaryDirectory() as d:
            store = FleetGraphStore(Path(d) / "kg.sqlite")
            nid = record(store, {"agent": "aegis-analyst", "pr": PR, "status": "deployed",
                                 "summary": "trial mode", "merge_commit": "abc"})
            self.assertEqual(nid, "decision:improvement:aegis-analyst#1")
            node = store.get_node(nid)
            self.assertEqual(node["type"], "decision")
            linked = store.neighbors("agent:aegis-analyst", "resulted_in")
            self.assertIn(nid, [e["dst"] for e in linked])
            self.assertEqual(store.sources_for(nid)[0]["source_uri"], PR)
            # Re-recording the outcome updates the same node, no duplicate.
            record(store, {"agent": "aegis-analyst", "pr": PR, "status": "held"})
            self.assertEqual(len(store.by_type("decision")), 1)
            store.close()

    def test_id_is_repo_and_pr_number(self):
        self.assertEqual(improvement_id(PR + "/"), "decision:improvement:aegis-analyst#1")


if __name__ == "__main__":
    unittest.main()
