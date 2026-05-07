"""Unity Catalog helpers for resource enrichment in GenieWatch.

Forked-down from genie-workbench's uc_client.py. GenieWatch only needs
table metadata lookup (kind, owner, comment) for the Resources tab.
"""

import logging
from typing import Optional

from backend.services.auth import get_workspace_client

logger = logging.getLogger(__name__)


def _enum_value(v) -> str:
    raw = getattr(v, "value", v)
    return str(raw or "")


def get_table(full_name: str) -> Optional[dict]:
    """Look up a UC table by `catalog.schema.name`. Returns None on failure."""
    if not full_name or full_name.count(".") != 2:
        return None
    try:
        client = get_workspace_client()
        t = client.tables.get(full_name=full_name)
    except Exception as e:
        logger.debug("UC tables.get(%s) failed: %s", full_name, e)
        return None
    return {
        "full_name": full_name,
        "kind": _enum_value(getattr(t, "table_type", None)),
        "owner": getattr(t, "owner", None),
        "comment": getattr(t, "comment", None),
    }
