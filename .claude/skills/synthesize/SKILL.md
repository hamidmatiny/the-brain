---
name: synthesize
description: Pull sibling agent repos (read-only) and produce one cross-department synthesis for aegis-ceo — cite sources; invent nothing
disable-model-invocation: false
---

# Synthesize (trial / scheduled)

## Purpose

Refresh `~/knowledge/{aegis-ceo,aegis-infra,aegis-threat-intel,aegis-analyst}` via read-only git, then write one honest synthesis of cross-department connections for `aegis-ceo`.

## Hard rules

- Read-only: run `~/scripts/pull-sibling-repos.sh` only. Never `git push`, never edit files under `~/knowledge/`.
- No live messaging to other agents. No `chat_with_agent` for this skill.
- Cite every claim with `repo/path` (and commit SHA when useful).
- If nothing cross-cutting appears, say so plainly — that is a valid result.
- **Fail-closed on pull:** do not synthesize from stale/partial `~/knowledge` and present it as current.

## Steps

1. Run `bash ~/scripts/pull-sibling-repos.sh` and capture the exit code plus each printed short SHA.
2. **Pull gate (required):** proceed only if exit code is **0** and you have **four** short SHAs — `aegis-ceo`, `aegis-infra`, `aegis-threat-intel`, `aegis-analyst`.
   - If exit code is nonzero, any SHA is missing, or the script output is incomplete: **abort**.
   - Write/print only a failure note, e.g. `~/memory/synthesis-YYYY-MM-DD-PULL-FAILED.md` (or chat only) with `status: pull-failed`, which repo/step failed, and that knowledge may be partial/stale.
   - Do **not** write `~/memory/synthesis-YYYY-MM-DD.md` as a current synthesis.
   - Do **not** continue to Steps 3–6.
3. Read each sibling's `CLAUDE.md`. Read `memory/*.md` where present. Skim `ARCHITECTURE.md` / `README.md` only if needed for a cited connection.
4. Look specifically for connections across departments (tier/auth decisions ↔ security posture; revenue/MRR ↔ prioritization; infra OmniRoute state ↔ who can actually run).
5. Write the report to `~/memory/synthesis-YYYY-MM-DD.md` AND print it in chat. Include the four SHAs in **Repos @**.
6. Do not enable or create schedules in this skill.

## Known failure modes

### FM-1 — Synthesizing after a failed/partial pull

**What went wrong:** The pull script uses `set -euo pipefail`, but the skill did not check exit status/SHAs, so a run could still write a "current" synthesis from stale or half-updated `~/knowledge`.

**Correct behavior:** Exit 0 + four SHAs required. Otherwise abort with `status: pull-failed` only.

## Output format (success only)

```markdown
# Fleet synthesis — YYYY-MM-DD

**Repos @:** aegis-ceo=<sha>, aegis-infra=<sha>, aegis-threat-intel=<sha>, aegis-analyst=<sha>

## Cross-department connections
- ... (each bullet cites source paths)

## Notable changes since last synthesis
- ... or "first run — no prior synthesis"

## Gaps / sparse sources
- ... (e.g. which repos have empty memory/)

## For aegis-ceo (no business judgment beyond surfacing)
- ...
```
