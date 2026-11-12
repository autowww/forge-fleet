"""User-visible service identity."""

from __future__ import annotations

import re

SERVICE_NAME = "forge-squid"
CONFIG_DIR_NAME = "forge-squid"
DEFAULT_EDGAR_USER_AGENT = "forge-squid/0.1 (ops@forgesdlc.com)"

# Open WebUI connection rows that point back at this shim (drop from catalog).
_OWUI_SHIM = re.compile(r"^forge-squid\.", re.I)


def is_owui_shim_connection_id(model_id: str) -> bool:
    return bool(_OWUI_SHIM.match(model_id.strip()))
