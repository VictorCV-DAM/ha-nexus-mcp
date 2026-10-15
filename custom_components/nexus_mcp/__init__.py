"""The Nexus MCP integration for Home Assistant."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_MODEL, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["conversation"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nexus MCP from a config entry."""
    # Ensure entry title displays the selected model name (auto-migrating existing entries)
    model = entry.data.get(CONF_MODEL)
    if model:
        desired_title = f"Nexus MCP ({model})"
        if entry.title != desired_title and (entry.title.startswith("Nexus MCP") or not entry.title):
            _LOGGER.info("Updating entry title from '%s' to '%s'", entry.title, desired_title)
            hass.config_entries.async_update_entry(entry, title=desired_title)

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
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

