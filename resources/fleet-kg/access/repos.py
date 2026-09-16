"""Read-only fleet access: sibling repos under ~/knowledge."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

KNOWLEDGE_ROOT = Path(os.path.expanduser(os.environ.get("KNOWLEDGE_ROOT", "~/knowledge")))

FLEET_REPOS = [
    "aegis-ceo",
    "aegis-infra",
    "aegis-threat-intel",
    "aegis-analyst",
    "aegis-core-infra",
    "aegis-data-quality",
    "aegis-growth",
    "the-brain",
]


def pull_script() -> Path:
    # Prefer agent-local script; fall back to repo-relative
    candidates = [
        Path(os.path.expanduser("~/scripts/pull-sibling-repos.sh")),
        Path(__file__).resolve().parents[3] / "scripts" / "pull-sibling-repos.sh",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("pull-sibling-repos.sh not found")


def pull_all() -> dict[str, Any]:
    script = pull_script()
    proc = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    lines = (proc.stdout or "").strip().splitlines()
    shas: dict[str, str] = {}
    for line in lines:
        if "=" in line and not line.startswith("status="):
            name, sha = line.split("=", 1)
            shas[name.strip()] = sha.strip()
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "shas": shas,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "expected": list(FLEET_REPOS),
    }


def read_text(repo: str, rel_path: str) -> dict[str, Any]:
    path = KNOWLEDGE_ROOT / repo / rel_path
    if not path.is_file():
        return {"ok": False, "error": f"missing {path}", "uri": str(path)}
    text = path.read_text(encoding="utf-8", errors="replace")
    sha = "unknown"
    git_dir = KNOWLEDGE_ROOT / repo / ".git"
    if git_dir.exists():
        try:
            sha = subprocess.check_output(
                ["git", "-C", str(KNOWLEDGE_ROOT / repo), "rev-parse", "--short", "HEAD"],
                text=True,
            ).strip()
        except subprocess.CalledProcessError:
            pass
    return {
        "ok": True,
        "repo": repo,
        "path": rel_path,
        "text": text,
        "sha": sha,
        "uri": f"repo://{repo}/{rel_path}@{sha}",
        "source_kind": "agent_repo",
    }


def list_memory_files(repo: str) -> list[str]:
    mem = KNOWLEDGE_ROOT / repo / "memory"
    if not mem.is_dir():
        return []
    return sorted(str(p.relative_to(KNOWLEDGE_ROOT / repo)) for p in mem.rglob("*") if p.is_file())
