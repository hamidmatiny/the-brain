# Fleet Knowledge Graph (company-wide institutional memory)

Structured property graph for Hamid's personal Trinity fleet (`the-brain` / VP).

## Backing store

**SQLite typed property graph** at `~/memory/fleet-kg.sqlite` (nodes + edges + source_refs + FTS).

**Why SQLite (not Neo4j/hosted graph DB):**

- Runs inside the existing agent container with zero new services
- Scales comfortably past dozens→thousands of agents with indexes
- Every claim carries a durable `source_refs` row (repo path, Trinity execution id, Slack ts)
- Portable with Trinity backups; no separate ops surface

**Why LangGraph/LangChain:** orchestrate multi-source **ingest** and **query** as explicit graphs with fail-closed gates — not as an LLM free-form narrative over flat logs.

## Entity types

`agent` · `department` · `task` · `decision` · `skill` · `promotion` · `escalation` · `event` · `document`

## Relationship types

`reports_to` · `requested_by` · `resulted_in` · `escalated_to` · `blocked_by` · `member_of` · `has_skill` · `has_level` · `occurred_in` · `cites`

## Access layers

| Source | How |
|--------|-----|
| Agent repos | `scripts/pull-sibling-repos.sh` → `~/knowledge/<agent>/` (GITHUB_PAT or deploy keys) |
| Trinity | HTTP `TRINITY_BACKEND_URL` + `TRINITY_MCP_API_KEY` (agents, executions, schedules) |
| Slack | Live `conversations.history` via `FLEET_KG_SLACK_BOT_TOKEN`, or cached `knowledge/_sources/slack/history.json` |

## CLI

```bash
python3 resources/fleet-kg/cli.py ingest
python3 resources/fleet-kg/cli.py query "who reports to whom"
python3 resources/fleet-kg/cli.py query "what is aegis-analyst career level"
python3 resources/fleet-kg/cli.py stats
```

Fail-closed: if the graph lacks grounded evidence, the query answer is `INSUFFICIENT_DATA` with an explicit reason — never a fabricated story.
