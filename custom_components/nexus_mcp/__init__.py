"""The Nexus MCP integration for Home Assistant."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_BASE_URL,
    CONF_LLM_PROVIDER,
    CONF_MODEL,
    DOMAIN,
    PROVIDER_GROQ_FREE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["conversation", "sensor"]


from pathlib import Path

try:
    from homeassistant.components.frontend import add_extra_js_url
except (ImportError, AttributeError):
    add_extra_js_url = None

try:
    from homeassistant.components.http import StaticPathConfig
except (ImportError, AttributeError):
    StaticPathConfig = None


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register custom Lovelace card for plug-and-play UI."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("frontend_registered"):
        return

    frontend_dir = Path(__file__).parent / "frontend"
    card_path = frontend_dir / "nexus-mcp-card.js"

    if not card_path.is_file():
        return

    url_path = "/nexus_mcp_static/nexus-mcp-card.js"

    # Register static path with Home Assistant HTTP server
    if hasattr(hass, "http"):
        if StaticPathConfig and hasattr(hass.http, "async_register_static_paths"):
            try:
                await hass.http.async_register_static_paths([
                    StaticPathConfig("/nexus_mcp_static", str(frontend_dir), cache_headers=False)
                ])
            except Exception as err:
                _LOGGER.debug("Could not register static path via async_register_static_paths: %s", err)
        elif hasattr(hass.http, "register_static_path"):
            try:
                hass.http.register_static_path(
                    "/nexus_mcp_static", str(frontend_dir), cache_headers=False
                )
            except Exception as err:
                _LOGGER.debug("Could not register static path via register_static_path: %s", err)

    # Register extra JS URL so Home Assistant frontend loads the card automatically
    if add_extra_js_url:
        try:
            add_extra_js_url(hass, f"{url_path}?v=1.2.0")
        except Exception as err:
            _LOGGER.debug("Could not add extra JS URL: %s", err)

    domain_data["frontend_registered"] = True


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Nexus MCP integration and global services."""
    await _async_register_frontend(hass)

    async def handle_clear_history(call) -> None:
        """Handle clearing conversation history."""
        entry_id = call.data.get("entry_id")
        domain_data = hass.data.get(DOMAIN, {})
        for eid, data in list(domain_data.items()):
            if entry_id and eid != entry_id:
                continue
            conv_entity = data.get("conversation_entity")
            if conv_entity:
                conv_entity._history.clear()
                conv_entity._last_conversation_id = None
                await conv_entity._async_save_history()

    if not hass.services.has_service(DOMAIN, "clear_history"):
        hass.services.async_register(DOMAIN, "clear_history", handle_clear_history)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nexus MCP from a config entry."""
    await _async_register_frontend(hass)

    merged_config = {**entry.data, **entry.options}
    provider = merged_config.get(CONF_LLM_PROVIDER)
    base_url = merged_config.get(CONF_BASE_URL, "")
    current_model = merged_config.get(CONF_MODEL, "")

    needs_update = False
    updated_data = dict(entry.data)

    # Auto-normalize Groq models (missing prefix or EU-restricted Llama)
    if provider == PROVIDER_GROQ_FREE or "groq.com" in base_url:
        if current_model in ("qwen3.8-27b", "qwen-27b", "qwen3.8", "qwen-3.8-27b"):
            updated_data[CONF_MODEL] = "qwen/qwen3.8-27b"
            current_model = "qwen/qwen3.8-27b"
            needs_update = True
        elif current_model in ("gpt-oss-120b", "120b", "openai-120b"):
            updated_data[CONF_MODEL] = "openai/gpt-oss-120b"
            current_model = "openai/gpt-oss-120b"
            needs_update = True
        elif current_model in ("gpt-oss-20b", "20b", "openai-20b"):
            updated_data[CONF_MODEL] = "openai/gpt-oss-20b"
            current_model = "openai/gpt-oss-20b"
            needs_update = True
        elif "llama" in current_model.lower():
            updated_data[CONF_MODEL] = "qwen/qwen3.8-27b"
            current_model = "qwen/qwen3.8-27b"
            needs_update = True

    desired_title = f"Nexus MCP ({current_model})" if current_model else entry.title
    title_needs_update = entry.title != desired_title and (entry.title.startswith("Nexus MCP") or not entry.title)

    if needs_update or title_needs_update:
        _LOGGER.info("Migrating entry '%s' -> title='%s', model='%s'", entry.title, desired_title, current_model)
        hass.config_entries.async_update_entry(entry, title=desired_title, data=updated_data)

    hass.data.setdefault(DOMAIN, {})
    _LOGGER.info("Initializing Nexus MCP Intercom (%s)", entry.title)

    # Store entry config and context
    hass.data[DOMAIN][entry.entry_id] = {
        "entry": entry,
    }

    # Set up conversation platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Nexus MCP Intercom (%s)", entry.title)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and entry.entry_id in hass.data.get(DOMAIN, {}):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry via Home Assistant's official config entry reload coordinator."""
    await hass.config_entries.async_reload(entry.entry_id)

