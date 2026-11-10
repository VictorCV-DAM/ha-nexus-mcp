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


FRONTEND_VERSION = "1.6.1"


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
            add_extra_js_url(hass, f"{url_path}?v={FRONTEND_VERSION}")
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
                r_url = r.get("url", "")
                # Clean up legacy local resource if still present
                if "/local/nexus-mcp-card.js" in r_url:
                    res_id = r.get("id")
                    if res_id and getattr(resources, "async_delete_item", None):
                        try:
                            await resources.async_delete_item(res_id)
                        except Exception:
                            pass
                    continue

                if r_url.startswith(url_path):
                    frontend_added = True
                    # If version parameter differs, update existing resource to bust browser cache
                    if r_url != f"{url_path}?v={FRONTEND_VERSION}":
                        res_id = r.get("id")
                        if res_id and getattr(resources, "async_update_item", None):
                            try:
                                await resources.async_update_item(res_id, {
                                    "res_type": r.get("type", "module"),
                                    "url": f"{url_path}?v={FRONTEND_VERSION}",
                                })
                            except Exception:
                                pass
                    break

            if not frontend_added:
                if getattr(resources, "async_create_item", None):
                    await resources.async_create_item({
                        "res_type": "module",
                        "url": f"{url_path}?v={FRONTEND_VERSION}",
                    })
                elif getattr(resources, "data", None) and getattr(resources.data, "append", None):
                    resources.data.append({
                        "type": "module",
                        "url": f"{url_path}?v={FRONTEND_VERSION}",
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
            if not isinstance(data, dict):
                continue
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
                vol.Optional("language"): str,
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
            language = msg.get("language")

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
                    language=language,
                    context=connection.context(msg),
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

        @websocket_api.websocket_command(
            {
                vol.Required("type"): "nexus_mcp/yaml_to_json",
                vol.Required("yaml"): str,
            }
        )
        @websocket_api.async_response
        async def ws_handle_yaml_to_json(
            hass: HomeAssistant,
            connection: websocket_api.ActiveConnection,
            msg: dict[str, Any],
        ) -> None:
            """Safely parse YAML to JSON data for the frontend card."""
            try:
                import time
                import yaml

                raw_yaml = msg["yaml"]
                data = yaml.safe_load(raw_yaml)
                if isinstance(data, list) and data:
                    data = data[0]

                if not isinstance(data, dict):
                    connection.send_error(msg["id"], "invalid_format", "YAML must be a dictionary/mapping")
                    return

                HELPER_DOMAINS = {
                    "input_boolean", "input_number", "input_select", "input_text",
                    "input_datetime", "input_button", "counter", "timer", "schedule",
                }

                helper_domain = None
                helper_data = None
                helper_slug = None

                for hd in HELPER_DOMAINS:
                    if hd in data:
                        helper_domain = hd
                        val = data[hd]
                        if isinstance(val, dict):
                            helper_slug = next(iter(val.keys())) if val else None
                            first_val = next(iter(val.values())) if val else {}
                            if isinstance(first_val, dict) and any(k in first_val for k in ("name", "options", "min", "max", "icon", "duration", "initial")):
                                helper_data = dict(first_val)
                                if "name" not in helper_data:
                                    helper_data["name"] = helper_slug
                            else:
                                helper_data = dict(val)
                        elif isinstance(val, list) and val and isinstance(val[0], dict):
                            helper_data = dict(val[0])
                        break

                if not helper_domain:
                    candidate = data.get("type") or data.get("domain") or data.get("platform")
                    if candidate in HELPER_DOMAINS:
                        helper_domain = candidate
                        helper_data = {k: v for k, v in data.items() if k not in ("type", "domain", "platform")}

                if helper_domain and helper_data:
                    if "name" not in helper_data:
                        helper_data["name"] = "Nuevo Ayudante"
                    helper_id = (
                        helper_data.get("id")
                        or helper_data.get(f"{helper_domain}_id")
                        or helper_data.get("helper_id")
                        or helper_slug
                    )
                    if not helper_id and "entity_id" in helper_data:
                        ent = str(helper_data["entity_id"])
                        if ent.startswith(f"{helper_domain}."):
                            helper_id = ent.split(".", 1)[1]
                    if helper_id:
                        helper_data[f"{helper_domain}_id"] = helper_id

                    connection.send_result(msg["id"], {
                        "is_helper": True,
                        "is_update": bool(helper_id),
                        "helper_domain": helper_domain,
                        "helper_id": helper_id,
                        "data": helper_data,
                    })
                    return

                # Check for Lovelace Dashboard Card (MUST be checked before scripts/scenes)
                CARD_TYPES = {
                    "tile", "entities", "entity", "glance", "button", "gauge", "markdown",
                    "thermostat", "weather-forecast", "light", "alarm-panel", "picture",
                    "picture-elements", "picture-entity", "picture-glance", "history-graph",
                    "statistics-graph", "logbook", "media-control", "map", "iframe",
                    "grid", "vertical-stack", "horizontal-stack", "area", "sensor", "humor"
                }
                candidate_type = str(data.get("type", "")).strip()
                is_card = False
                if candidate_type:
                    if (
                        candidate_type in CARD_TYPES
                        or candidate_type.startswith("custom:")
                        or candidate_type.endswith("-card")
                        or "cards" in data
                        or "card" in data
                    ):
                        is_card = True

                if is_card and not any(k in data for k in ("trigger", "triggers", "sequence")):
                    card_title = data.get("title") or data.get("name") or data.get("header") or ""
                    connection.send_result(msg["id"], {
                        "is_card": True,
                        "card_type": candidate_type,
                        "title": card_title,
                        "data": data,
                    })
                    return

                # Check for scene
                if "scene" in data:
                    val = data["scene"]
                    if isinstance(val, list) and val:
                        data = val[0]
                    elif isinstance(val, dict):
                        first_val = next(iter(val.values())) if val else {}
                        if isinstance(first_val, dict) and "entities" in first_val:
                            data = dict(first_val)
                            if "name" not in data and "alias" not in data:
                                data["name"] = next(iter(val.keys()))
                        else:
                            data = dict(val)

                if isinstance(data, dict) and "entities" in data and not any(k in data for k in ("trigger", "triggers", "sequence", "type")):
                    scene_data = dict(data)
                    if "name" not in scene_data:
                        scene_data["name"] = scene_data.get("alias") or "Nueva Escena"
                    is_update = bool(scene_data.get("id") or scene_data.get("scene_id"))
                    scene_id = scene_data.get("scene_id") or scene_data.get("id") or f"nexus_scene_{int(time.time() * 1000)}"
                    connection.send_result(msg["id"], {
                        "is_scene": True,
                        "is_update": is_update,
                        "scene_id": scene_id,
                        "data": scene_data,
                    })
                    return

                # Check for script (requires sequence: or script: key; never match plain card actions)
                if "script" in data:
                    val = data["script"]
                    if isinstance(val, dict):
                        first_val = next(iter(val.values())) if val else {}
                        if isinstance(first_val, dict) and ("sequence" in first_val or "action" in first_val):
                            data = dict(first_val)
                            if "alias" not in data and "name" not in data:
                                data["alias"] = next(iter(val.keys()))
                        else:
                            data = dict(val)
                    elif isinstance(val, list) and val:
                        data = val[0]

                has_trigger = any(k in data for k in ("trigger", "triggers", "platform"))
                is_script = ("sequence" in data or "script" in data) and not has_trigger and not is_card

                if is_script:
                    script_data = dict(data)
                    seq = script_data.get("sequence") or script_data.get("action") or script_data.get("actions")
                    if isinstance(seq, dict):
                        seq = [seq]
                    script_data["sequence"] = seq if isinstance(seq, list) else []
                    script_data.pop("action", None)
                    script_data.pop("actions", None)
                    if "alias" not in script_data:
                        script_data["alias"] = script_data.get("name") or "Nuevo Script"
                    is_update = bool(script_data.get("id") or script_data.get("script_id"))
                    script_id = script_data.get("script_id") or script_data.get("id") or f"nexus_script_{int(time.time() * 1000)}"
                    connection.send_result(msg["id"], {
                        "is_script": True,
                        "is_update": is_update,
                        "script_id": script_id,
                        "data": script_data,
                    })
                    return

                # Otherwise automation: normalize trigger, action, condition to lists if provided as dict
                for key in ("trigger", "triggers", "action", "actions", "condition", "conditions"):
                    if key in data and isinstance(data[key], dict):
                        data[key] = [data[key]]

                original_id = data.get("id")
                allow_update = msg.get("allow_update", False)
                if allow_update and original_id:
                    is_update = True
                    auto_id = str(original_id)
                else:
                    is_update = False
                    auto_id = f"nexus_{int(time.time() * 1000)}"

                data["id"] = auto_id

                connection.send_result(msg["id"], {
                    "is_automation": True,
                    "is_update": is_update,
                    "automation_id": auto_id,
                    "data": data,
                })
            except Exception as err:
                connection.send_error(msg["id"], "parse_error", str(err))

        try:
            websocket_api.async_register_command(hass, ws_handle_chat)
        except Exception as err:
            _LOGGER.debug("Could not register nexus_mcp/chat websocket command: %s", err)
        try:
            websocket_api.async_register_command(hass, ws_handle_get_history)
        except Exception as err:
            _LOGGER.debug("Could not register nexus_mcp/get_history websocket command: %s", err)
        try:
            websocket_api.async_register_command(hass, ws_handle_yaml_to_json)
        except Exception as err:
            _LOGGER.debug("Could not register nexus_mcp/yaml_to_json websocket command: %s", err)
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
    if needs_update:
        # Update in-memory entry data cleanly without triggering re-entrant reload loops
        hass.config_entries.async_update_entry(entry, data=updated_data)

    hass.data.setdefault(DOMAIN, {})
    _LOGGER.info("Initializing Nexus MCP Intercom (%s)", desired_title)

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

