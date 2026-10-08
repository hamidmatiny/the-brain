"""Phase 1 loops record a recommendation. They do not start runs or change schedules."""

from __future__ import annotations

import os

LIVE_ENV = "AEGIS_FLEET_GRAPH_LIVE"


def observe_mode() -> bool:
    return os.environ.get(LIVE_ENV) != "1"


def apply_allowed() -> bool:
    """Live schedule and trigger writes stay off until Hamid turns the env var on.

    Phase 1 does not implement that write even when the variable is set.
    """
    return False
