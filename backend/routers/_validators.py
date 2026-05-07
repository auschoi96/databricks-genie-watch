"""Input-shape validators shared across routers."""

import re

from fastapi import HTTPException

# Genie Space IDs are 32-character lowercase hex.
_SPACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def validate_space_id(space_id: str) -> str:
    """Ensure a path-segment looks like a Genie Space ID. Returns the cleaned value."""
    s = (space_id or "").strip().lower()
    if not _SPACE_ID_RE.match(s):
        raise HTTPException(status_code=400, detail=f"Invalid space_id: {space_id!r}")
    return s


def validate_days(days: int, *, default: int = 7, max_days: int = 365) -> int:
    """Clamp the days window to a sane range."""
    if days is None:
        return default
    if days < 1:
        return 1
    if days > max_days:
        return max_days
    return days
