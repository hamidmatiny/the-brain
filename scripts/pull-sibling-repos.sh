#!/usr/bin/env bash
# Read-only refresh of sibling AEGIS agent repos under ~/knowledge/.
# Used by /synthesize pull-gate: exit 0 only when all four clones refresh and
# short SHAs print. Fail closed on any error (do not leave partial success silent).
set -euo pipefail

KNOWLEDGE_ROOT="${KNOWLEDGE_ROOT:-$HOME/knowledge}"
mkdir -p "$KNOWLEDGE_ROOT"

# Ordered list — synthesize pull-gate expects these four names.
SIBLINGS=(aegis-ceo aegis-infra aegis-threat-intel aegis-analyst)

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
    # Ensure remote stays the intended URL shape without printing secrets.
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
  # Machine-readable line for the synthesize pull-gate.
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
  # pull_one may print clone/pull logs on stderr; keep only name=sha lines.
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
  echo "status=pull-failed count=${#shas[@]}/4" >&2
  exit 1
fi
if [[ "${#shas[@]}" -ne 4 ]]; then
  echo "status=pull-failed expected 4 SHAs got ${#shas[@]}" >&2
  exit 1
fi

echo "status=ok" >&2
exit 0
