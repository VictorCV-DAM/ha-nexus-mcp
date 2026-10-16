"""The Nexus MCP integration for Home Assistant."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_BASE_URL,
    CONF_LLM_PROVIDER,
    CONF_MODEL,
    DOMAIN,
    PROVIDER_GROQ_FREE,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

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
            add_extra_js_url(hass, f"{url_path}?v=1.4.2")
        except Exception as err:
            _LOGGER.debug("Could not add extra JS URL: %s", err)

    # Also register as a Lovelace resource so it is discovered by the card picker automatically
    try:
        lovelace_data = hass.data.get("lovelace")
        resources = getattr(lovelace_data, "resources", None) if lovelace_data else None
        if resources:
            if not getattr(resources, "loaded", True):
                await resources.async_load()
                resources.loaded = True

            frontend_added = False
            for r in getattr(resources, "async_items", lambda: [])():
                if r.get("url", "").startswith(url_path):
                    frontend_added = True
                    # If version parameter differs, update existing resource to bust browser cache
                    if r.get("url") != f"{url_path}?v=1.4.2":
                        res_id = r.get("id")
                        if res_id and getattr(resources, "async_update_item", None):
                            try:
                                await resources.async_update_item(res_id, {
                                    "res_type": r.get("type", "module"),
                                    "url": f"{url_path}?v=1.4.2",
                                })
                            except Exception:
                                pass
                    break

            if not frontend_added:
                if getattr(resources, "async_create_item", None):
                    await resources.async_create_item({
                        "res_type": "module",
                        "url": f"{url_path}?v=1.4.2",
                    })
                elif getattr(resources, "data", None) and getattr(resources.data, "append", None):
                    resources.data.append({
                        "type": "module",
                        "url": f"{url_path}?v=1.4.2",
                    })
    except Exception as err:
        _LOGGER.debug("Could not auto-register Lovelace resource: %s", err)

    domain_data["frontend_registered"] = True


def _async_setup_services(hass: HomeAssistant) -> None:
    """Register Nexus MCP integration services if not already registered."""
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

    # Register multimodal WebSocket handler
    _async_setup_websocket(hass)


def _async_setup_websocket(hass: HomeAssistant) -> None:
    """Register Nexus MCP WebSocket command for multimodal chat."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    try:
        from homeassistant.components import websocket_api
        import voluptuous as vol

        @websocket_api.websocket_command(
            {
                vol.Required("type"): "nexus_mcp/chat",
                vol.Required("text"): str,
                vol.Optional("image"): str,
                vol.Optional("agent_id"): str,
                vol.Optional("conversation_id"): str,
            }
        )
        @websocket_api.async_response
        async def ws_handle_chat(
            hass: HomeAssistant,
            connection: websocket_api.ActiveConnection,
            msg: dict[str, Any],
        ) -> None:
            """Handle chat with optional image."""
            text = msg["text"]
            image = msg.get("image")
            agent_id = msg.get("agent_id")
            conversation_id = msg.get("conversation_id") or "nexus_chat"

            # Find matching conversation entity
            domain_entries = hass.data.get(DOMAIN, {})
            conv_entity = None
            if agent_id:
                for eid, data in domain_entries.items():
                    if isinstance(data, dict):
                        ce = data.get("conversation_entity")
                        if ce and (eid in agent_id or getattr(ce, "entity_id", "") == agent_id):
                            conv_entity = ce
                            break
            if not conv_entity:
                for data in domain_entries.values():
                    if isinstance(data, dict):
                        ce = data.get("conversation_entity")
                        if ce:
                            conv_entity = ce
                            break

            if not conv_entity:
                connection.send_error(msg["id"], "not_found", "No Nexus MCP agent found")
                return

            try:
                reply = await conv_entity.async_chat_process(
                    text=text,
                    image_data=image,
                    conversation_id=conversation_id,
                )
                connection.send_result(
                    msg["id"],
                    {
                        "response": {
                            "speech": {
                                "plain": {
                                    "speech": reply,
                                }
                            }
                        },
                        "conversation_id": conversation_id,
                    },
                )
            except Exception as err:
                connection.send_error(msg["id"], "chat_error", str(err))

        @websocket_api.websocket_command(
            {
                vol.Required("type"): "nexus_mcp/get_history",
                vol.Optional("agent_id"): str,
            }
        )
        @websocket_api.async_response
        async def ws_handle_get_history(
            hass: HomeAssistant,
            connection: websocket_api.ActiveConnection,
            msg: dict[str, Any],
        ) -> None:
            """Handle retrieving persistent conversation history."""
            agent_id = msg.get("agent_id")
            domain_entries = hass.data.get(DOMAIN, {})
            conv_entity = None
            if agent_id:
                for eid, data in domain_entries.items():
                    if isinstance(data, dict):
                        ce = data.get("conversation_entity")
                        if ce and (eid in agent_id or getattr(ce, "entity_id", "") == agent_id):
                            conv_entity = ce
                            break
            if not conv_entity:
                for data in domain_entries.values():
                    if isinstance(data, dict):
                        ce = data.get("conversation_entity")
                        if ce:
                            conv_entity = ce
                            break

            if not conv_entity:
                connection.send_result(msg["id"], {"messages": [], "conversation_id": None})
                return

            if not getattr(conv_entity, "_history_loaded", False):
                await conv_entity._async_load_history()

            last_conv_id = getattr(conv_entity, "_last_conversation_id", None)
            history_dict = getattr(conv_entity, "_history", {})
            msgs = history_dict.get(last_conv_id, []) if last_conv_id else []
            if not msgs and history_dict:
                last_conv_id = next(reversed(history_dict))
                msgs = history_dict[last_conv_id]

            raw_msgs = [
                {
                    "role": getattr(m, "role", "user"),
                    "content": getattr(m, "content", ""),
                }
                for m in msgs
                if getattr(m, "role", "") in ("user", "assistant") and getattr(m, "content", "")
            ]

            connection.send_result(
                msg["id"],
                {
                    "messages": raw_msgs,
                    "conversation_id": last_conv_id,
                },
            )

        try:
            websocket_api.async_register_command(hass, ws_handle_chat)
        except Exception as err:
            _LOGGER.debug("Could not register nexus_mcp/chat websocket command: %s", err)
        try:
            websocket_api.async_register_command(hass, ws_handle_get_history)
        except Exception as err:
            _LOGGER.debug("Could not register nexus_mcp/get_history websocket command: %s", err)
        domain_data["ws_registered"] = True
    except Exception as err:
        _LOGGER.debug("Could not register nexus_mcp websocket commands: %s", err)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Nexus MCP integration and global services."""
    await _async_register_frontend(hass)
    _async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nexus MCP from a config entry."""
    await _async_register_frontend(hass)
    _async_setup_services(hass)

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


_RELOAD_TASKS: dict[str, Any] = {}


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry via Home Assistant's official config entry reload coordinator."""
    # Check if a reload is already scheduled for this entry to debounce multiple consecutive updates
    existing_task = _RELOAD_TASKS.get(entry.entry_id)
    if existing_task and not existing_task.done():
        return

    async def _debounced_reload() -> None:
        await asyncio.sleep(0.05)
        try:
            await hass.config_entries.async_reload(entry.entry_id)
        except Exception as err:
            _LOGGER.debug("Error during debounced reload of %s: %s", entry.entry_id, err)
        finally:
            _RELOAD_TASKS.pop(entry.entry_id, None)

    if hasattr(hass, "async_create_task"):
        task = hass.async_create_task(_debounced_reload())
        _RELOAD_TASKS[entry.entry_id] = task
    else:
        await hass.config_entries.async_reload(entry.entry_id)

