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

PLATFORMS = ["conversation"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nexus MCP from a config entry."""
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

