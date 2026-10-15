"""Sensor platform for Nexus MCP conversation history, daily token usage, and rate limit telemetry."""
from __future__ import annotations

import datetime
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
try:
    from homeassistant.components.sensor import SensorStateClass
except (ImportError, AttributeError):
    SensorStateClass = None
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
try:
    from homeassistant.helpers.dispatcher import async_dispatcher_connect
except (ImportError, AttributeError):
    async_dispatcher_connect = None
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_LLM_PROVIDER,
    CONF_MODEL,
    DOMAIN,
    PROVIDER_CUSTOM_OPENAI,
    PROVIDER_GEMINI_FREE,
    PROVIDER_GROQ_FREE,
    PROVIDER_QWEN_FREE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nexus MCP sensors based on model capabilities."""
    provider = entry.options.get(
        CONF_LLM_PROVIDER, entry.data.get(CONF_LLM_PROVIDER, "")
    )

    entities: list[SensorEntity] = [NexusMcpHistorySensor(hass, entry)]

    # Token usage sensor: Only for providers that track and report token usage
    # (Cloud providers with tokens: Groq, Gemini, Qwen, Custom OpenAI).
    # Local models (Ollama) have no remote quotas or token limits.
    if provider in (
        PROVIDER_GEMINI_FREE,
        PROVIDER_GROQ_FREE,
        PROVIDER_QWEN_FREE,
        PROVIDER_CUSTOM_OPENAI,
    ):
        entities.append(NexusMcpTokenSensor(hass, entry))

    # Real-time rate limit / renewal countdown sensor:
    # Only for cloud providers that have tokens-per-minute (TPM) or request quotas.
    # Excluded for local models like Ollama where rate limits do not exist.
    if provider in (
        PROVIDER_GROQ_FREE,
        PROVIDER_GEMINI_FREE,
        PROVIDER_QWEN_FREE,
        PROVIDER_CUSTOM_OPENAI,
    ):
        entities.append(NexusMcpRateLimitResetSensor(hass, entry))

    async_add_entities(entities)


class NexusMcpHistorySensor(SensorEntity):
    """Sensor exposing conversation history and formatted markdown for Lovelace."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:forum-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the history sensor."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_conversation_history"
        self._attr_name = "Historial de Conversaciones"

    @property
    def device_info(self) -> dict[str, Any]:
        """Link sensor to the Nexus MCP device."""
        model_name = self.entry.options.get(
            CONF_MODEL, self.entry.data.get(CONF_MODEL, "Agent")
        )
        return {
            "identifiers": {(DOMAIN, self.entry.entry_id)},
            "name": f"Nexus MCP ({model_name})",
            "manufacturer": "Nexus MCP",
            "model": model_name,
            "sw_version": "1.3.4",
        }

    async def async_added_to_hass(self) -> None:
        """Register dispatcher when entity is added."""
        if hasattr(super(), "async_added_to_hass"):
            await super().async_added_to_hass()

        if async_dispatcher_connect:
            signal = f"{DOMAIN}_{self.entry.entry_id}_history_updated"
            self.async_on_remove(
                async_dispatcher_connect(self.hass, signal, self._handle_history_updated)
            )

    @callback
    def _handle_history_updated(self) -> None:
        """Handle history update signal."""
        self.async_write_ha_state()

    @property
    def _conversation_entity(self) -> Any:
        """Retrieve the associated conversation entity from hass.data."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        return entry_data.get("conversation_entity")

    @property
    def native_value(self) -> str:
        """Return the state of the sensor: last message preview or idle status."""
        conv_entity = self._conversation_entity
        if not conv_entity:
            return "Sin conversaciones"

        last_conv_id = getattr(conv_entity, "_last_conversation_id", None)
        history_dict = getattr(conv_entity, "_history", {})
        if not last_conv_id or last_conv_id not in history_dict:
            return "Sin conversaciones"

        msgs = history_dict[last_conv_id]
        if not msgs:
            return "Sin conversaciones"

        last_msg = msgs[-1]
        content = (getattr(last_msg, "content", "") or "").strip()
        if len(content) > 250:
            return content[:247] + "..."
        return content or "Activo"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes containing full history and formatted markdown."""
        conv_entity = self._conversation_entity
        if not conv_entity:
            return {
                "total_conversations": 0,
                "total_messages": 0,
                "history": [],
                "formatted_markdown": "*No hay conversaciones registradas.*",
            }

        last_conv_id = getattr(conv_entity, "_last_conversation_id", None)
        history_dict = getattr(conv_entity, "_history", {})
        active_msgs = history_dict.get(last_conv_id, []) if last_conv_id else []

        last_user_query = None
        last_assistant_response = None
        for msg in reversed(active_msgs):
            role = getattr(msg, "role", "")
            content = getattr(msg, "content", "")
            if role == "user" and last_user_query is None:
                last_user_query = content
            elif role == "assistant" and last_assistant_response is None:
                last_assistant_response = content
            if last_user_query and last_assistant_response:
                break

        raw_list = [
            {"role": getattr(m, "role", ""), "content": getattr(m, "content", "")}
            for m in active_msgs[-20:]
        ]

        if not active_msgs:
            formatted_md = "*No hay conversaciones recientes. Habla con Assist para empezar.*"
        else:
            md_lines = []
            for m in active_msgs[-12:]:
                role = getattr(m, "role", "")
                content = getattr(m, "content", "")
                if role == "user":
                    md_lines.append(f"🧑 **Tú:** {content}")
                elif role == "assistant":
                    md_lines.append(f"🤖 **Nexus:** {content}")
                md_lines.append("")
            formatted_md = "\n".join(md_lines).strip()

        return {
            "conversation_id": last_conv_id,
            "total_conversations": len(history_dict),
            "total_messages": len(active_msgs),
            "last_user_query": last_user_query,
            "last_assistant_response": last_assistant_response,
            "history": raw_list,
            "formatted_markdown": formatted_md,
        }


class NexusMcpTokenSensor(SensorEntity):
    """Sensor exposing daily token consumption and telemetry for the LLM model."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:chart-timeline-variant-shimmer"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the token sensor."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_daily_tokens"
        self._attr_name = "Consumo de Tokens Diario"
        self._attr_native_unit_of_measurement = "tokens"
        self._attr_state_class = getattr(SensorStateClass, "TOTAL_INCREASING", "total_increasing")

    @property
    def device_info(self) -> dict[str, Any]:
        """Link sensor to the Nexus MCP device."""
        model_name = self.entry.options.get(
            CONF_MODEL, self.entry.data.get(CONF_MODEL, "Agent")
        )
        return {
            "identifiers": {(DOMAIN, self.entry.entry_id)},
            "name": f"Nexus MCP ({model_name})",
            "manufacturer": "Nexus MCP",
            "model": model_name,
            "sw_version": "1.3.4",
        }

    async def async_added_to_hass(self) -> None:
        """Register dispatcher when entity is added."""
        if hasattr(super(), "async_added_to_hass"):
            await super().async_added_to_hass()

        if async_dispatcher_connect:
            signal = f"{DOMAIN}_{self.entry.entry_id}_telemetry_updated"
            self.async_on_remove(
                async_dispatcher_connect(self.hass, signal, self._handle_telemetry_updated)
            )

    @callback
    def _handle_telemetry_updated(self) -> None:
        """Handle telemetry update signal."""
        self.async_write_ha_state()

    @property
    def _conversation_entity(self) -> Any:
        """Retrieve the associated conversation entity from hass.data."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        return entry_data.get("conversation_entity")

    @property
    def native_value(self) -> int:
        """Return the total tokens used today."""
        conv_entity = self._conversation_entity
        if not conv_entity:
            return 0
        telem = getattr(conv_entity, "telemetry", {})
        return int(telem.get("tokens_today", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed token telemetry attributes."""
        conv_entity = self._conversation_entity
        if not conv_entity:
            return {
                "prompt_tokens_today": 0,
                "completion_tokens_today": 0,
                "last_total_tokens": 0,
            }
        telem = getattr(conv_entity, "telemetry", {})
        return {
            "prompt_tokens_today": telem.get("prompt_tokens_today", 0),
            "completion_tokens_today": telem.get("completion_tokens_today", 0),
            "last_prompt_tokens": telem.get("last_prompt_tokens", 0),
            "last_completion_tokens": telem.get("last_completion_tokens", 0),
            "last_total_tokens": telem.get("last_total_tokens", 0),
            "model": telem.get("model", ""),
            "provider": telem.get("provider", ""),
            "remaining_tokens_minute": telem.get("remaining_tokens"),
            "limit_tokens_minute": telem.get("limit_tokens"),
            "remaining_requests_minute": telem.get("remaining_requests"),
            "limit_requests_minute": telem.get("limit_requests"),
            "date": telem.get("date"),
            "last_updated": telem.get("last_updated"),
        }


class NexusMcpRateLimitResetSensor(SensorEntity):
    """Sensor exposing real-time countdown / seconds until next rate limit renewal."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:timer-sand"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the rate limit reset sensor."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_rate_limit_reset"
        self._attr_name = "Tiempo Desbloqueo Rate Limit"
        self._attr_native_unit_of_measurement = "s"
        self._attr_suggested_display_precision = 1

    @property
    def device_info(self) -> dict[str, Any]:
        """Link sensor to the Nexus MCP device."""
        model_name = self.entry.options.get(
            CONF_MODEL, self.entry.data.get(CONF_MODEL, "Agent")
        )
        return {
            "identifiers": {(DOMAIN, self.entry.entry_id)},
            "name": f"Nexus MCP ({model_name})",
            "manufacturer": "Nexus MCP",
            "model": model_name,
            "sw_version": "1.3.4",
        }

    async def async_added_to_hass(self) -> None:
        """Register dispatcher when entity is added."""
        if hasattr(super(), "async_added_to_hass"):
            await super().async_added_to_hass()

        if async_dispatcher_connect:
            signal = f"{DOMAIN}_{self.entry.entry_id}_telemetry_updated"
            self.async_on_remove(
                async_dispatcher_connect(self.hass, signal, self._handle_telemetry_updated)
            )

    @callback
    def _handle_telemetry_updated(self) -> None:
        """Handle telemetry update signal."""
        self.async_write_ha_state()

    @property
    def _conversation_entity(self) -> Any:
        """Retrieve the associated conversation entity from hass.data."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        return entry_data.get("conversation_entity")

    @property
    def native_value(self) -> float:
        """Return remaining seconds until rate limit unblock/reset (0 if ready)."""
        conv_entity = self._conversation_entity
        if not conv_entity:
            return 0.0
        telem = getattr(conv_entity, "telemetry", {})
        reset_at_iso = telem.get("rate_limit_reset_at")
        if not reset_at_iso:
            return 0.0
        try:
            reset_dt = datetime.datetime.fromisoformat(reset_at_iso)
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            diff = (reset_dt - now_dt).total_seconds()
            if diff > 0:
                return round(diff, 1)
        except Exception:
            pass
        return 0.0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return rate limit details."""
        conv_entity = self._conversation_entity
        if not conv_entity:
            return {"status": "ready"}
        telem = getattr(conv_entity, "telemetry", {})
        rem_sec = self.native_value
        return {
            "status": "throttled" if rem_sec > 0 else "ready",
            "reset_at": telem.get("rate_limit_reset_at"),
            "last_reset_duration": telem.get("rate_limit_reset_seconds", 0.0),
            "model": telem.get("model", ""),
            "provider": telem.get("provider", ""),
            "remaining_tokens_minute": telem.get("remaining_tokens"),
            "limit_tokens_minute": telem.get("limit_tokens"),
            "remaining_requests_minute": telem.get("remaining_requests"),
            "limit_requests_minute": telem.get("limit_requests"),
        }
