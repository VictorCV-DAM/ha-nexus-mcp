"""Built-in Home Assistant tools for Nexus MCP.

Allows the AI model to search entities, read states, execute services,
and create automations directly in Home Assistant.
"""
import datetime
import logging
import os
import time
from typing import Any
import yaml

from homeassistant.core import HomeAssistant

from .mcp_client import McpTool

_LOGGER = logging.getLogger(__name__)


def serialize_for_json(obj: Any) -> Any:
    """Recursively convert datetime, set, and non-serializable objects into JSON-compatible types."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, (datetime.date, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): serialize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [serialize_for_json(x) for x in obj]
    return obj


def get_builtin_tools() -> list[McpTool]:
    """Return standard Home Assistant MCP tools."""
    return [
        McpTool(
            name="ha_search_entities",
            description="Search for entities and devices in Home Assistant by friendly name, domain (e.g. light, switch, sensor, climate), or entity ID. Pass empty query or 'all' to list available entities.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to search for (e.g. 'living room light', 'kitchen', 'temperature', 'all').",
                    },
                    "domain": {
                        "type": "string",
                        "description": "Optional domain filter (e.g. 'light', 'switch', 'sensor', 'climate').",
                    },
                },
                "required": [],
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
                        "description": "The exact entity_id (e.g. 'light.living_room').",
                    }
                },
                "required": ["entity_id"],
            },
        ),
        McpTool(
            name="ha_call_service",
            description="Call a Home Assistant service to control a device or perform an action (e.g. turn on/off lights, set color/brightness, toggle switches). Supports optional 'delay' in seconds for timed actions (e.g. delay: 5 to turn off after 5 seconds).",
            input_schema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Optional service domain (e.g. 'light', 'switch', 'homeassistant'). If omitted, service can be 'domain.service' (e.g. 'light.turn_on').",
                    },
                    "service": {
                        "type": "string",
                        "description": "Service name (e.g. 'turn_on', 'turn_off', 'toggle', or full 'light.turn_on').",
                    },
                    "target": {
                        "type": "object",
                        "description": "Target entity or device (e.g. {'entity_id': 'light.living_room'} or {'entity_id': ['light.left', 'light.right']}).",
                    },
                    "data": {
                        "type": "object",
                        "description": "Optional service data parameters (e.g. {'brightness': 255, 'rgb_color': [0, 255, 0]}).",
                    },
                    "delay": {
                        "type": "number",
                        "description": "Optional delay in seconds before executing this action (e.g. 5 for 'after 5 seconds').",
                    },
                },
                "required": ["service"],
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
        import re
        query = (arguments.get("query") or arguments.get("q") or "").lower().strip()
        domain_filter = (arguments.get("domain") or "").lower().strip()

        all_states = list(hass.states.async_all())
        total_count = len(all_states)

        # Count domains to provide helpful feedback to the LLM
        domain_counts: dict[str, int] = {}
        for state in all_states:
            d = state.entity_id.split(".")[0]
            domain_counts[d] = domain_counts.get(d, 0) + 1

        is_broad_query = not query or query in (
            "*", "all", "everything", "entities", "devices",
            "todos", "todas", "dispositivos", "entidades", "listar",
        )

        # Stop words removal for Spanish and English
        STOP_WORDS = {
            "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "en", "y", "o", "a",
            "al", "para", "por", "con", "the", "a", "an", "of", "in", "and", "or", "to", "for", "with"
        }
        raw_tokens = [w for w in re.split(r"[\s_,.-]+", query) if w]
        tokens = [w for w in raw_tokens if w not in STOP_WORDS]
        if not tokens:
            tokens = raw_tokens

        # Plural and root variants for query and tokens
        query_variants = [query] if query else []
        if query.endswith("es") and len(query) > 3:
            query_variants.append(query[:-2])
        elif query.endswith("s") and len(query) > 2:
            query_variants.append(query[:-1])
        if query in ("luces", "luz"):
            query_variants.extend(["luz", "luce", "light"])

        def _get_token_variants(t: str) -> list[str]:
            v = [t]
            if t.endswith("es") and len(t) > 3:
                v.append(t[:-2])
            elif t.endswith("s") and len(t) > 2:
                v.append(t[:-1])
            if t in ("luces", "luz"):
                v.extend(["luz", "luce", "light"])
            return v

        # Attempt to access HA registries for rich area, alias, and device name matching
        ent_reg = None
        area_reg = None
        dev_reg = None
        try:
            from homeassistant.helpers import (
                area_registry as ar,
                device_registry as dr,
                entity_registry as er,
            )
            ent_reg = er.async_get(hass)
            area_reg = ar.async_get(hass)
            dev_reg = dr.async_get(hass)
        except Exception:
            pass

        scored_results: list[tuple[int, dict[str, Any]]] = []
        for state in all_states:
            entity_id = state.entity_id
            domain = entity_id.split(".")[0]
            friendly_name = state.attributes.get("friendly_name", "").lower()

            area_name = ""
            aliases: list[str] = []
            dev_name = ""
            if ent_reg:
                try:
                    ent_entry = ent_reg.async_get(entity_id)
                    if ent_entry:
                        if getattr(ent_entry, "aliases", None):
                            aliases = [str(a).lower() for a in ent_entry.aliases]
                        area_id = ent_entry.area_id
                        if not area_id and ent_entry.device_id and dev_reg:
                            dev_entry = dev_reg.async_get(ent_entry.device_id)
                            if dev_entry:
                                area_id = dev_entry.area_id
                                dev_name = str(dev_entry.name_by_user or dev_entry.name or "").lower()
                        if area_id and area_reg:
                            area_entry = area_reg.async_get_area(area_id)
                            if area_entry:
                                area_name = str(area_entry.name or "").lower()
                except Exception:
                    pass

            searchable_text = f"{entity_id.lower()} {friendly_name} {area_name} {dev_name} {' '.join(aliases)}".strip()

            # Domain filtering with smart fallback for lights connected to switches/smart plugs
            if domain_filter:
                if domain_filter == "light":
                    # Many users control lights via smart plugs or relays (switch domain)
                    is_light_switch = domain == "switch" and any(
                        kw in searchable_text for kw in ("luz", "light", "lamp", "bombilla", "foco", "enchufe", "taller")
                    )
                    if domain != "light" and not is_light_switch:
                        continue
                elif domain_filter == "climate":
                    is_climate_alt = domain in ("switch", "fan", "scene") and any(
                        kw in searchable_text for kw in ("aire", "clima", "acondicionado", "termostato", "hvac", "frio", "calor")
                    )
                    if domain != "climate" and not is_climate_alt:
                        continue
                elif domain != domain_filter:
                    continue

            score = 0
            if is_broad_query:
                if domain in ("light", "switch", "sensor", "climate", "cover", "media_player", "automation"):
                    score = 10
            else:
                # 1. Exact query match in entity_id or friendly_name (including query variants)
                if any(qv in entity_id.lower() or (friendly_name and qv in friendly_name) for qv in query_variants):
                    score += 100
                elif any(qv in searchable_text for qv in query_variants):
                    score += 70

                # 2. Token matches
                matched_tokens = sum(1 for t in tokens if any(tv in searchable_text for tv in _get_token_variants(t)))
                if matched_tokens == len(tokens) and len(tokens) > 0:
                    score += 80 + len(tokens) * 5
                elif matched_tokens > 0:
                    score += int(30 * (matched_tokens / len(tokens)))

                # 3. Area or device name bonus
                if area_name and any(t in area_name for t in tokens):
                    score += 40

                # 4. Direct domain bonus
                if domain_filter and domain == domain_filter:
                    score += 5

            if score > 0:
                item = {
                    "entity_id": entity_id,
                    "name": state.attributes.get("friendly_name", entity_id),
                    "state": state.state,
                    "domain": domain,
                }
                if area_name:
                    item["area"] = area_name
                scored_results.append((score, item))

        # Sort by score descending
        scored_results.sort(key=lambda x: x[0], reverse=True)
        results = [item for _, item in scored_results[:15]]

        resp: dict[str, Any] = {
            "results": results,
            "count": len(results),
            "total_entities_in_ha": total_count,
        }
        if not results:
            primary_domains = {
                k: v for k, v in domain_counts.items()
                if k in ("light", "switch", "sensor", "binary_sensor", "climate", "cover", "automation")
            }
            resp["hint"] = (
                f"No entities matched query '{query}'. However, Home Assistant has {total_count} total entities "
                f"configured across domains: {primary_domains}. Try searching by domain or broader keywords."
            )
        return resp

    if name == "ha_get_entity_state":
        entity_id = arguments.get("entity_id", "")
        state = hass.states.get(entity_id)
        if not state:
            return {"error": f"Entity '{entity_id}' not found in Home Assistant."}

        # Filter heavy attributes to keep token consumption low and serialize datetimes
        attrs = dict(state.attributes)
        trimmed_attrs = {}
        for k, v in attrs.items():
            if isinstance(v, (list, dict)) and len(str(v)) > 200:
                continue
            trimmed_attrs[k] = serialize_for_json(v)

        return {
            "entity_id": entity_id,
            "state": state.state,
            "attributes": trimmed_attrs,
        }

    if name == "ha_call_service":
        domain = str(arguments.get("domain") or "").strip()
        service = str(arguments.get("service") or arguments.get("action") or "").strip()
        target = dict(arguments.get("target") or {})
        data = dict(arguments.get("data") or {})
        service_data = arguments.get("service_data")

        # Normalize entity_id and parameters from local LLM variations
        if isinstance(service_data, dict):
            if "entity_id" in service_data and "entity_id" not in target:
                target["entity_id"] = service_data["entity_id"]
            for k, v in service_data.items():
                if k != "entity_id" and k not in data:
                    data[k] = v

        if "entity_id" in arguments and "entity_id" not in target:
            target["entity_id"] = arguments["entity_id"]

        if "." in service and not domain:
            domain, service = service.split(".", 1)
        elif "." in domain and not service:
            domain, service = domain.split(".", 1)

        # Automatic domain resolution if missing
        target_eid = target.get("entity_id")
        target_eids = [target_eid] if isinstance(target_eid, str) else (target_eid if isinstance(target_eid, list) else [])
        first_target_domain = target_eids[0].split(".")[0] if (target_eids and "." in target_eids[0]) else None

        if not domain:
            if first_target_domain and service in ("turn_on", "turn_off", "toggle"):
                domain = first_target_domain if first_target_domain in ("light", "switch", "climate", "fan", "cover", "media_player") else "homeassistant"
            elif first_target_domain:
                domain = first_target_domain
            else:
                domain = "homeassistant"

        # If calling light.turn_on/turn_off on a switch entity (smart plug controlling light), redirect to homeassistant or switch
        if domain == "light" and first_target_domain == "switch":
            domain = "homeassistant"

        try:
            delay = float(arguments.get("delay") or data.get("delay") or 0.0)
        except (ValueError, TypeError):
            delay = 0.0

        try:
            call_data = {**data}
            if "delay" in call_data:
                del call_data["delay"]
            if target:
                call_data.update(target)

            if delay > 0:
                import asyncio

                async def _delayed_service_call():
                    try:
                        await asyncio.sleep(delay)
                        await hass.services.async_call(
                            domain, service, call_data, blocking=False
                        )
                    except Exception as ex:
                        _LOGGER.error("Delayed service execution failed (%s.%s): %s", domain, service, ex)

                if hasattr(hass, "async_create_task"):
                    hass.async_create_task(_delayed_service_call())
                return {
                    "status": "scheduled",
                    "message": f"Service '{domain}.{service}' scheduled to execute in {delay:.1f} seconds.",
                }

            await hass.services.async_call(
                domain, service, call_data, blocking=True
            )
            return {
                "status": "success",
                "message": f"Service '{domain}.{service}' executed successfully.",
            }
        except Exception as err:
            _LOGGER.error("Error executing service %s.%s: %s", domain, service, err)
            return {"status": "error", "message": str(err)}

    if name == "ha_create_automation":
        alias = arguments.get("alias", "New Automation")
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
                "message": f"Automation '{alias}' created and activated successfully in Home Assistant.",
            }
        except Exception as err:
            _LOGGER.error("Failed to reload automations after save: %s", err)
            return {
                "status": "warning",
                "message": f"Automation saved but failed to reload: {err}",
            }

    return {"error": f"Unknown tool '{name}'."}
