"""Read-only Slack channel history for the fleet.

Live path: Slack Web API conversations.history using FLEET_KG_SLACK_BOT_TOKEN
(or ~/memory/secrets/slack_bot_token). Cache fallback: knowledge/_sources/slack/history.json.
Fail closed if neither is available.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

KNOWLEDGE_ROOT = Path(os.path.expanduser(os.environ.get("KNOWLEDGE_ROOT", "~/knowledge")))
CACHE_PATH = KNOWLEDGE_ROOT / "_sources" / "slack" / "history.json"
SECRET_PATH = Path(os.path.expanduser("~/memory/secrets/slack_bot_token"))

# Known fleet channels (also discovered via Trinity bindings when available)
DEFAULT_CHANNELS = {
    "aegis-ceo": "C0C10JBBETZ",
    "aegis-infra": "C0C1FN1US4E",
    "aegis-threat-intel": "C0C1CMV29GT",
    "aegis-analyst": "C0C1LSNUZ97",
    "aegis-core-infra": "C0C1H5WD5NJ",
    "aegis-data-quality": "C0C1QCJTNH0",
    "the-brain": "C0C13HT74AK",
}


def _token() -> str | None:
    env = os.environ.get("FLEET_KG_SLACK_BOT_TOKEN") or os.environ.get("SLACK_BOT_TOKEN")
    if env:
        return env.strip()
    if SECRET_PATH.is_file():
        return SECRET_PATH.read_text(encoding="utf-8").strip() or None
    return None


def fetch_live(channel_id: str, limit: int = 50) -> dict[str, Any]:
    tok = _token()
    if not tok:
        raise RuntimeError("No Slack bot token (FLEET_KG_SLACK_BOT_TOKEN or ~/memory/secrets/slack_bot_token)")
    url = "https://slack.com/api/conversations.history?" + urllib.parse.urlencode(
        {"channel": channel_id, "limit": limit}
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"Slack conversations.history failed: {data.get('error')}")
    return data


def load_history(prefer_live: bool = True, limit: int = 50) -> dict[str, Any]:
    """Return {fetched_at, mode, channels: {name: {channel_id, messages, ...}}}."""
    channels = dict(DEFAULT_CHANNELS)
    # Enrich from Trinity bindings when possible
    try:
        from access import trinity as trinity_access

        for agent in list(DEFAULT_CHANNELS) + ["aegis-growth"]:
            try:
                for ch in trinity_access.list_slack_channels(agent):
                    cid = ch.get("channel_id")
                    cname = ch.get("channel_name") or agent
                    if cid:
                        channels[cname] = cid
            except Exception:
                continue
    except Exception:
        pass

    if prefer_live and _token():
        out_channels: dict[str, Any] = {}
        for name, cid in channels.items():
            try:
                data = fetch_live(cid, limit=limit)
                msgs = []
                for m in data.get("messages") or []:
                    msgs.append(
                        {
                            "ts": m.get("ts"),
                            "user": m.get("user"),
                            "bot_id": m.get("bot_id"),
                            "text": m.get("text") or "",
                            "thread_ts": m.get("thread_ts"),
                            "channel_id": cid,
                            "channel_name": name,
                        }
                    )
                out_channels[name] = {
                    "channel_id": cid,
                    "ok": True,
                    "messages": msgs,
                    "source": "slack.conversations.history",
                }
            except Exception as e:
                out_channels[name] = {
                    "channel_id": cid,
                    "ok": False,
                    "error": str(e),
                    "messages": [],
                }
        return {
            "fetched_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            "mode": "live",
            "channels": out_channels,
        }

    if CACHE_PATH.is_file():
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        cached["mode"] = "cache"
        cached["cache_path"] = str(CACHE_PATH)
        return cached

    raise RuntimeError(
        "INSUFFICIENT_ACCESS: no live Slack token and no cache at "
        f"{CACHE_PATH} — fail closed"
    )
