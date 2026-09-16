"""Read-only Trinity HTTP access (agents, executions, schedules)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _base() -> str:
    return os.environ.get("TRINITY_BACKEND_URL") or os.environ.get("TRINITY_API_URL") or "http://backend:8000"


def _token() -> str:
    # Prefer MCP key — agent JWT often fails validation for fleet-wide reads.
    for key in ("TRINITY_MCP_API_KEY", "TRINITY_API_KEY", "TRINITY_AGENT_AUTH_TOKEN"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    raise RuntimeError("No Trinity API token in env (TRINITY_MCP_API_KEY / TRINITY_AGENT_AUTH_TOKEN)")


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = _base().rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_token()}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Trinity GET {path} -> {e.code}: {body[:300]}") from e


def list_agents() -> list[dict[str, Any]]:
    data = _get("/api/agents")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("agents") or data.get("items") or []
    return []


def list_executions(agent_name: str, limit: int = 50) -> list[dict[str, Any]]:
    data = _get(f"/api/agents/{urllib.parse.quote(agent_name)}/executions", {"limit": limit})
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("executions") or data.get("items") or []
    return []


def list_schedules(agent_name: str) -> list[dict[str, Any]]:
    data = _get(f"/api/agents/{urllib.parse.quote(agent_name)}/schedules")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # common shapes
        if "detail" in data:
            raise RuntimeError(str(data["detail"]))
        return data.get("schedules") or data.get("items") or []
    return []


def list_slack_channels(agent_name: str) -> list[dict[str, Any]]:
    data = _get(f"/api/agents/{urllib.parse.quote(agent_name)}/slack/channels")
    if isinstance(data, dict):
        return data.get("channels") or []
    return []
