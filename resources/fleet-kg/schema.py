"""Fleet knowledge-graph entity and relationship vocabularies."""

from __future__ import annotations

ENTITY_TYPES = frozenset(
    {
        "agent",
        "department",
        "task",
        "decision",
        "skill",
        "promotion",
        "escalation",
        "event",
        "document",
    }
)

REL_TYPES = frozenset(
    {
        "reports_to",
        "requested_by",
        "resulted_in",
        "escalated_to",
        "blocked_by",
        "member_of",
        "has_skill",
        "has_level",
        "occurred_in",
        "cites",
    }
)

# Stable node ids
def agent_id(name: str) -> str:
    return f"agent:{name.strip().lower()}"


def dept_id(name: str) -> str:
    return f"department:{name.strip().lower().replace(' ', '-')}"


def skill_id(agent: str, skill: str) -> str:
    return f"skill:{agent}:{skill.strip().lower().replace('/', '-')}"


def task_id(execution_id: str) -> str:
    return f"task:exec:{execution_id}"


def escalation_id(key: str) -> str:
    return f"escalation:{key}"


def promotion_id(agent: str, since: str) -> str:
    return f"promotion:{agent}:{since}"


def event_id(key: str) -> str:
    return f"event:{key}"


def document_id(repo: str, path: str) -> str:
    return f"document:{repo}:{path}"


def slack_msg_id(channel: str, ts: str) -> str:
    return f"event:slack:{channel}:{ts}"
