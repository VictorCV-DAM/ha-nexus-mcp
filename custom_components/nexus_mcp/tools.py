"""Built-in Home Assistant tools for Nexus MCP.

Allows the AI model to search entities, read states, execute services,
and create automations directly in Home Assistant.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any
import yaml

from homeassistant.core import HomeAssistant

from .mcp_client import McpTool

_LOGGER = logging.getLogger(__name__)


def get_builtin_tools() -> list[McpTool]:
    """Return standard Home Assistant MCP tools."""
    return [
        McpTool(
            name="ha_search_entities",
            description="Search for entities and devices in Home Assistant by friendly name, domain (e.g. light, switch, sensor), or entity ID.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to search for (e.g. 'bombilla izquierda', 'salon', 'temperatura').",
                    },
                    "domain": {
                        "type": "string",
                        "description": "Optional domain filter (e.g. 'light', 'switch', 'sensor', 'climate').",
                    },
                },
                "required": ["query"],
            },
        ),
        McpTool(
            name="ha_get_entity_state",
            description="Get the current state and attributes of a specific Home Assistant entity.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "The exact entity_id (e.g. 'light.bombilla_izquierda').",
                    }
                },
                "required": ["entity_id"],
            },
        ),
        McpTool(
            name="ha_call_service",
            description="Call a Home Assistant service to control a device or perform an action (e.g. turn on a light, lock a door).",
            input_schema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Service domain (e.g. 'light', 'switch', 'homeassistant').",
                    },
                    "service": {
                        "type": "string",
                        "description": "Service name (e.g. 'turn_on', 'turn_off', 'toggle').",
                    },
                    "target": {
                        "type": "object",
                        "description": "Target entity or device (e.g. {'entity_id': 'light.bombilla_izquierda'}).",
                    },
                    "data": {
                        "type": "object",
                        "description": "Optional service data parameters (e.g. {'brightness': 255}).",
                    },
                },
                "required": ["domain", "service"],
            },
        ),
        McpTool(
            name="ha_create_automation",
            description="Create and immediately activate a new automation in Home Assistant. Saves directly to automations.yaml and reloads the automation engine.",
            input_schema={
                "type": "object",
                "properties": {
                    "alias": {
                        "type": "string",
                        "description": "Descriptive title for the automation.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description of what the automation does.",
                    },
                    "trigger": {
                        "type": "array",
                        "description": "List of triggers (e.g. time_pattern, state changes, numeric_state).",
                        "items": {"type": "object"},
                    },
                    "condition": {
                        "type": "array",
                        "description": "Optional list of conditions that must be met.",
                        "items": {"type": "object"},
                    },
                    "action": {
                        "type": "array",
                        "description": "List of actions to execute when triggered.",
                        "items": {"type": "object"},
                    },
                    "mode": {
                        "type": "string",
                        "description": "Execution mode: 'single', 'restart', 'queued', or 'parallel'. Default is 'single'.",
                    },
                },
                "required": ["alias", "trigger", "action"],
            },
        ),
    ]


def sanitize_automation_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Sanitize and normalize triggers and actions into valid Home Assistant syntax."""
    # Ensure triggers is a list
    raw_triggers = entry.get("trigger", [])
    if isinstance(raw_triggers, dict):
        raw_triggers = [raw_triggers]

    sanitized_triggers = []
    for trg in raw_triggers:
        if not isinstance(trg, dict):
            continue
        t = dict(trg)

        # Handle time_pattern triggers
        is_time_pattern = (
            t.get("trigger") == "time_pattern"
            or t.get("platform") == "time_pattern"
            or "pattern" in t
            or "seconds" in t
            or "minutes" in t
            or "hours" in t
        )
        if is_time_pattern:
            t["platform"] = "time_pattern"
            t.pop("trigger", None)

            # Fix 'pattern: 00:00:05' -> seconds: '/5'
            if "pattern" in t:
                pat = str(t.pop("pattern")).strip()
                if ":" in pat:
                    parts = [p.strip() for p in pat.split(":")]
                    secs = parts[-1].lstrip("0") or "5"
                    t["seconds"] = f"/{secs}"
                else:
                    t["seconds"] = f"/{pat}" if pat.isdigit() else pat

            # Fix 'seconds: 5' where interval is intended
            if "seconds" in t:
                s = str(t["seconds"]).strip()
                if s.isdigit():
                    t["seconds"] = f"/{s}"

        sanitized_triggers.append(t)
    entry["trigger"] = sanitized_triggers

    # Ensure actions is a list
    raw_actions = entry.get("action", [])
    if isinstance(raw_actions, dict):
        raw_actions = [raw_actions]

    sanitized_actions = []
    for act in raw_actions:
        if not isinstance(act, dict):
            continue
        a = dict(act)

        # Fix domain: button, service: press -> service: button.press
        if "domain" in a and "service" in a:
            domain = str(a.pop("domain")).strip()
            srv = str(a.get("service")).strip()
            if "." not in srv:
                a["service"] = f"{domain}.{srv}"

        # If 'action' is used instead of 'service' or vice versa, ensure valid format
        if "action" in a and "domain" in a:
            domain = str(a.pop("domain")).strip()
            act_name = str(a.get("action")).strip()
            if "." not in act_name:
                a["action"] = f"{domain}.{act_name}"

        # Normalize target / entity_id
        if "entity_id" in a and "target" not in a:
            eid = a.pop("entity_id")
            a["target"] = {"entity_id": eid}

        sanitized_actions.append(a)
    entry["action"] = sanitized_actions

    # Ensure condition is a list
    raw_conditions = entry.get("condition", [])
    if isinstance(raw_conditions, dict):
        raw_conditions = [raw_conditions]
    entry["condition"] = raw_conditions

    return entry


async def execute_builtin_tool(
    hass: HomeAssistant, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Execute a built-in Home Assistant tool."""
    _LOGGER.info("Executing built-in HA tool '%s' with arguments: %s", name, arguments)

    if name == "ha_search_entities":
        query = arguments.get("query", "").lower()
        domain_filter = arguments.get("domain", "").lower()

        results = []
        for state in hass.states.async_all():
            entity_id = state.entity_id
            domain = entity_id.split(".")[0]
            friendly_name = state.attributes.get("friendly_name", "").lower()

            if domain_filter and domain != domain_filter:
                continue

            # Check match against entity_id or friendly_name
            if query in entity_id.lower() or query in friendly_name:
                results.append(
                    {
                        "entity_id": entity_id,
                        "name": state.attributes.get("friendly_name", entity_id),
                        "state": state.state,
                    }
                )
                if len(results) >= 10:
                    break

        return {"results": results, "count": len(results)}

    if name == "ha_get_entity_state":
        entity_id = arguments.get("entity_id", "")
        state = hass.states.get(entity_id)
        if not state:
            return {"error": f"Entity '{entity_id}' not found in Home Assistant."}

        # Filter heavy attributes to keep token consumption low
        attrs = dict(state.attributes)
        trimmed_attrs = {}
        for k, v in attrs.items():
            if isinstance(v, (list, dict)) and len(str(v)) > 200:
                continue
            trimmed_attrs[k] = v

        return {
            "entity_id": entity_id,
            "state": state.state,
            "attributes": trimmed_attrs,
        }

    if name == "ha_call_service":
        domain = arguments.get("domain", "")
        service = arguments.get("service", "")
        target = arguments.get("target") or {}
        data = arguments.get("data") or {}

        try:
            service_data = {**data}
            if target:
                service_data.update(target)

            await hass.services.async_call(
                domain, service, service_data, blocking=True
            )
            return {
                "status": "success",
                "message": f"Service '{domain}.{service}' executed successfully.",
            }
        except Exception as err:
            _LOGGER.error("Error executing service %s.%s: %s", domain, service, err)
            return {"status": "error", "message": str(err)}

    if name == "ha_create_automation":
        alias = arguments.get("alias", "Nueva Automatización")
        description = arguments.get("description", "")
        trigger = arguments.get("trigger", [])
        condition = arguments.get("condition", [])
        action = arguments.get("action", [])
        mode = arguments.get("mode", "single")

        auto_id = str(int(time.time() * 1000))
        raw_entry = {
            "id": auto_id,
            "alias": alias,
            "description": description,
            "trigger": trigger,
            "condition": condition,
            "action": action,
            "mode": mode,
        }
        automation_entry = sanitize_automation_entry(raw_entry)

        automations_path = hass.config.path("automations.yaml")

        def _save_automation() -> None:
            existing = []
            if os.path.exists(automations_path):
                with open(automations_path, "r", encoding="utf-8") as f:
                    try:
                        content = yaml.safe_load(f)
                        if isinstance(content, list):
                            existing = content
                    except Exception as parse_err:
                        _LOGGER.warning("Could not parse automations.yaml: %s", parse_err)
                        existing = []

            existing.append(automation_entry)

            with open(automations_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    existing,
                    f,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False,
                )

        # Write to file in executor thread to avoid blocking event loop
        await hass.async_add_executor_job(_save_automation)

        # Reload Home Assistant automations
        try:
            await hass.services.async_call("automation", "reload", blocking=True)
            return {
                "status": "success",
                "automation_id": auto_id,
                "alias": alias,
                "message": f"Automatización '{alias}' creada y activada correctamente en Home Assistant.",
            }
        except Exception as err:
            _LOGGER.error("Failed to reload automations after save: %s", err)
            return {
                "status": "warning",
                "message": f"Automatización guardada pero falló la recarga: {err}",
            }

    return {"error": f"Unknown tool '{name}'."}
