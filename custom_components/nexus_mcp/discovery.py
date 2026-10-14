"""Auto-discovery helpers for Home Assistant integrations and MCP servers."""
from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def async_autodiscover_ha_mcp_url(hass: HomeAssistant) -> str | None:
    """Auto-discover the HA-MCP Server URL from existing ha_mcp_tools integration entries."""
    try:
        for entry in hass.config_entries.async_entries("ha_mcp_tools"):
            # Priority 1: Direct access port with secret_path (internal high-speed access)
            secret_path = entry.data.get("secret_path")
            if secret_path:
                url = f"http://127.0.0.1:9584{secret_path}"
                _LOGGER.info("Auto-discovered direct HA-MCP Server URL: %s", url)
                return url

            # Priority 2: Webhook endpoint
            webhook_id = entry.data.get("webhook_id")
            if webhook_id:
                url = f"http://127.0.0.1:8123/api/webhook/{webhook_id}"
                _LOGGER.info("Auto-discovered webhook HA-MCP Server URL: %s", url)
                return url

    except Exception as err:
        _LOGGER.debug("Error during HA-MCP auto-discovery: %s", err)

    return None
