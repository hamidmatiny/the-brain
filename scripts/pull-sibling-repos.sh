#!/usr/bin/env bash
# Read-only refresh of fleet agent repos under ~/knowledge/.
# Used by /synthesize and /ingest-fleet-kg pull-gates.
# Exit 0 only when ALL configured fleet clones refresh and short SHAs print.
# Fail closed on any error (do not leave partial success silent).
set -euo pipefail

KNOWLEDGE_ROOT="${KNOWLEDGE_ROOT:-$HOME/knowledge}"
mkdir -p "$KNOWLEDGE_ROOT"

# Full Track B fleet (the-brain included so VP can index its own mandate).
# Override with FLEET_REPOS="aegis-ceo aegis-infra ..." if needed.
if [[ -n "${FLEET_REPOS:-}" ]]; then
  # shellcheck disable=SC2206
  SIBLINGS=(${FLEET_REPOS})
else
  SIBLINGS=(
    aegis-ceo
    aegis-infra
    aegis-threat-intel
    aegis-analyst
    aegis-core-infra
    aegis-data-quality
    aegis-growth
    the-brain
  )
fi

EXPECTED="${#SIBLINGS[@]}"

# Prefer HTTPS with a read token if present; else SSH deploy key ~/.ssh/id_<repo>.
# Never push. Never write remotes.
github_url() {
  local name="$1"
  local token="${GITHUB_TOKEN:-${GH_TOKEN:-${GITHUB_PAT:-}}}"
  if [[ -n "$token" ]]; then
    printf 'https://x-access-token:%s@github.com/hamidmatiny/%s.git' "$token" "$name"
  else
    printf 'git@github.com:hamidmatiny/%s.git' "$name"
  fi
}

ssh_key_for() {
  local name="$1"
  local key="$HOME/.ssh/id_${name}"
  if [[ -f "$key" ]]; then
    printf '%s' "$key"
  else
    printf ''
  fi
}

pull_one() {
  local name="$1"
  local dest="$KNOWLEDGE_ROOT/$name"
  local url
  url="$(github_url "$name")"
  local key
  key="$(ssh_key_for "$name")"

  local git_ssh=()
  if [[ -n "$key" && "$url" == git@* ]]; then
    git_ssh=(env "GIT_SSH_COMMAND=ssh -i $key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new")
  fi

  if [[ ! -d "$dest/.git" ]]; then
    echo "clone $name -> $dest" >&2
    "${git_ssh[@]}" git clone --depth 1 "$url" "$dest"
  else
    echo "pull $name" >&2
    (
      cd "$dest"
      "${git_ssh[@]}" git remote set-url origin "$url"
      "${git_ssh[@]}" git fetch --depth 1 origin HEAD
      local branch
      branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
      if [[ -z "$branch" || "$branch" == "HEAD" ]]; then
        "${git_ssh[@]}" git checkout -B main FETCH_HEAD
      else
        "${git_ssh[@]}" git reset --hard FETCH_HEAD
      fi
    )
  fi

  local sha
  sha="$(git -C "$dest" rev-parse --short HEAD)"
  if [[ -z "$sha" || ${#sha} -lt 7 ]]; then
    echo "ERROR: missing short SHA for $name" >&2
    return 1
  fi
  echo "${name}=${sha}"
}

failed=0
declare -a shas=()
for name in "${SIBLINGS[@]}"; do
  if ! out="$(pull_one "$name")"; then
    echo "ERROR: pull failed for $name" >&2
    failed=1
    continue
  fi
  line="$(printf '%s\n' "$out" | grep -E "^${name}=[0-9a-f]+$" | tail -1 || true)"
  if [[ -z "$line" ]]; then
    echo "ERROR: no SHA line for $name" >&2
    failed=1
    continue
  fi
  echo "$line"
  shas+=("$line")
done

if [[ "$failed" -ne 0 ]]; then
  echo "status=pull-failed count=${#shas[@]}/${EXPECTED}" >&2
  exit 1
fi
if [[ "${#shas[@]}" -ne "$EXPECTED" ]]; then
  echo "status=pull-failed expected ${EXPECTED} SHAs got ${#shas[@]}" >&2
  exit 1
fi

echo "status=ok repos=${EXPECTED}" >&2
exit 0
