---
name: ingest-fleet-kg
description: Pull fleet repos + Trinity executions/schedules + Slack history into the-brain's SQLite knowledge graph (LangGraph ingest). Fail closed on total source failure. Incremental — deduped source_refs; skips if a successful ingest finished in the last 90 minutes.
disable-model-invocation: false
---

# Ingest fleet knowledge graph

## Purpose

Refresh company-wide institutional memory for `the-brain` (VP): agents, tasks, decisions, skills, promotions, departments, escalations — with real source refs.

## Hard rules

- Read-only against sibling remotes, Trinity, and Slack.
- Never fabricate nodes. Every upsert must carry a `source_refs` row.
- If **all** primary sources fail, abort with `status: ingest-failed` — do not pretend the graph is current.
- **Incremental (mandatory):** do not treat every schedule fire as a full rebuild.
  - `source_refs` dedupe on `(node_or_edge_id, source_kind, source_uri)` — re-ingest must not inflate counts.
  - Nodes/edges upsert in place.
  - If a successful ingest finished within the last **90 minutes**, skip the CLI re-run and report `skipped: recent_successful_ingest` (unless the operator asked for `--force`).
  - Overlapping schedule + retry stampede is waste — prefer skip over a second full pull.

## Steps

1. Ensure deps: `pip install -r resources/fleet-kg/requirements.txt` (or already installed in the agent image).
2. Confirm access env:
   - `GITHUB_PAT` (or deploy keys) for `scripts/pull-sibling-repos.sh`
   - `TRINITY_MCP_API_KEY` + `TRINITY_BACKEND_URL` for executions/schedules
   - `FLEET_KG_SLACK_BOT_TOKEN` or `~/memory/secrets/slack_bot_token` (else Slack cache at `knowledge/_sources/slack/history.json`)
3. Run:
   ```bash
   python3 resources/fleet-kg/cli.py ingest
   # force full pass only when explicitly needed:
   # python3 resources/fleet-kg/cli.py ingest --force
   ```
4. Print `python3 resources/fleet-kg/cli.py stats`. Confirm `sources_by_kind` includes at least one of `agent_repo`, `trinity`, `slack` when those sources succeeded. **Source-ref totals should stay flat across back-to-back runs** unless real new URIs appeared — rising totals on unchanged fleet = bug.
5. **Slack close-out** to `#the-brain` — what was asked, who asked, ingest status (ok / partial / skipped), source counts.

## Output

JSON summary from the CLI (`status` = `ok` | `partial` | `failed`). Partial is honest when some sources worked and others did not. `skipped: true` is a valid success when a recent ingest already completed.
