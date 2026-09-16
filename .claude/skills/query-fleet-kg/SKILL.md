---
name: query-fleet-kg
description: Answer fleet questions from the-brain's knowledge graph with fail-closed discipline — cite sources; never invent.
disable-model-invocation: false
---

# Query fleet knowledge graph

## Purpose

Answer questions from Hamid or any agent about institutional memory: org chart, career levels / promotion blockers, task history, past escalations/events — grounded only in ingested graph evidence.

## Hard rules

- If evidence is missing or too thin, answer exactly with `INSUFFICIENT_DATA: ...` and stop. Do **not** fill gaps from general knowledge.
- Always list sources (`source_kind` + `source_uri`) that the CLI returns.
- Read-only. Do not mutate the graph during a query (use `/ingest-fleet-kg` to refresh).

## Steps

1. If the graph may be stale relative to the ask, run `/ingest-fleet-kg` first (or say you are answering from last ingest).
2. Run:
   ```bash
   python3 resources/fleet-kg/cli.py query "<question>"
   ```
3. Return the CLI answer verbatim (including `INSUFFICIENT_DATA` when status is not ok).
4. **Slack close-out** to `#the-brain`.

## Example questions

- "who reports to whom"
- "what is aegis-analyst career level and what is blocking promotion"
- "what have I been asked to do" (must name the agent)
- "what happened with Protocol B escalation"
