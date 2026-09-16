---
name: synthesize
description: Pull fleet agent repos (read-only), refresh the knowledge graph when possible, and produce one cross-department synthesis for aegis-ceo — cite sources; invent nothing
disable-model-invocation: false
---

# Synthesize (trial / scheduled)

## Purpose

Refresh `~/knowledge/<fleet-agent>/` via read-only git (full Track B roster), optionally refresh the fleet knowledge graph, then write one honest synthesis of cross-department connections for `aegis-ceo`.

## Hard rules

- Read-only: run `~/scripts/pull-sibling-repos.sh` only for remotes. Never `git push`, never edit files under `~/knowledge/` remotes.
- Prefer graph-backed claims via `python3 resources/fleet-kg/cli.py query "..."` when the graph has been ingested; still cite `repo/path` or graph `source_uri`.
- No fabricating connections. Cross-agent messaging is not required for synthesis (file/graph reading is enough); A2A to `aegis-ceo` for delivering the report is allowed when permissions exist.
- Cite every claim with `repo/path` (and commit SHA when useful) or `source_kind`/`source_uri` from the graph.
- If nothing cross-cutting appears, say so plainly — that is a valid result.
- **Fail-closed on pull:** do not synthesize from stale/partial `~/knowledge` and present it as current.
- **No strategic narrative without Repos @:** if the expected fleet SHAs are missing from this turn's pull output, you may not write growth/MRR/priority recommendations framed as a synthesis.

## Steps

1. Run `bash ~/scripts/pull-sibling-repos.sh` and capture the exit code plus each printed short SHA.
2. **Pull gate (required):** proceed only if exit code is **0** and you have one SHA line per configured fleet repo (default **8**: ceo, infra, threat-intel, analyst, core-infra, data-quality, growth, the-brain).
   - If exit code is nonzero, any SHA is missing, or the script output is incomplete: **abort**.
   - Write/print only a failure note, e.g. `~/memory/synthesis-YYYY-MM-DD-PULL-FAILED.md` (or chat only) with `status: pull-failed`, which repo/step failed, and that knowledge may be partial/stale.
   - Do **not** write `~/memory/synthesis-YYYY-MM-DD.md` as a current synthesis.
   - Do **not** continue to Steps 3–7.
3. Optionally refresh the graph: `python3 resources/fleet-kg/cli.py ingest` (honest `partial` is OK if Slack/Trinity hiccup; still require Step 2 pull success).
4. Read each sibling's `CLAUDE.md`. Read `memory/*.md` where present. Query the graph for org/career/escalation context when useful.
5. Look specifically for connections across departments (tier/auth decisions ↔ security posture; revenue/MRR ↔ prioritization; infra OmniRoute state ↔ who can actually run).
6. Write the report to `~/memory/synthesis-YYYY-MM-DD.md` AND print it in chat. Include the fleet SHAs in **Repos @**.
7. Do not enable or create schedules in this skill.
8. **Slack completed-task close-out (mandatory):** post to `#the-brain` via `list_channel_groups` (`channel_type: "slack"`) then `send_group_message` — what was asked, who asked, what you did, real outcome (including `status: pull-failed` when the gate aborted), who you reported to. Trinity `report` is not a substitute. See CLAUDE.md § Slack completed-task close-out.

## Known failure modes

### FM-1 — Synthesizing after a failed/partial pull

**Correct behavior:** Exit 0 + full SHA set required. Otherwise abort with `status: pull-failed` only.

### FM-2 — Fabricating a synthesis without a successful pull (regression 2026-09-15)

**Correct behavior:** If Step 2 pull gate fails **or** you did not actually run the pull script this turn, output **only**:
```
status: pull-failed
reason: <exact>
knowledge_state: partial-or-stale — not used for synthesis
```
No strategic narrative. No MRR/fleet recommendations. No pretending sibling inputs were read.

## Output format (success only)

```markdown
# Fleet synthesis — YYYY-MM-DD

**Repos @:** <name>=<sha>, ...

## Cross-department connections
- ... (each bullet cites source paths or graph source_uri)

## Notable changes since last synthesis
- ... or "first run — no prior synthesis"

## Gaps / sparse sources
- ... (e.g. which repos have empty memory/; graph INSUFFICIENT_DATA areas)

## For aegis-ceo (no business judgment beyond surfacing)
- ...
```
