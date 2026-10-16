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
    get_entity_description,
)

_LOGGER = logging.getLogger(__name__)

# Known theoretical specifications and default tier limits
MODEL_THEORETICAL_SPECS: dict[str, dict[str, Any]] = {
    # Groq Cloud models (Free Dev Tier)
    "openai/gpt-oss-120b": {
        "tpm": 8000,
        "rpm": 30,
        "rpd": 14400,
        "context_window": 131072,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 0,
        "reset_tz": "UTC",
    },
    "openai/gpt-oss-20b": {
        "tpm": 8000,
        "rpm": 30,
        "rpd": 14400,
        "context_window": 131072,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 0,
        "reset_tz": "UTC",
    },
    "qwen/qwen3.8-27b": {
        "tpm": 7000,
        "rpm": 30,
        "rpd": 14400,
        "context_window": 131072,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 0,
        "reset_tz": "UTC",
    },
    # Google Gemini models (Free Tier)
    "gemini-3.1-flash-lite": {
        "tpm": 250000,
        "rpm": 15,
        "rpd": 500,
        "context_window": 1048576,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 8,  # Midnight PST = 08:00 UTC
        "reset_tz": "PST (08:00 UTC)",
    },
    "gemini-flash-latest": {
        "tpm": 250000,
        "rpm": 5,
        "rpd": 20,
        "context_window": 1048576,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 8,
        "reset_tz": "PST (08:00 UTC)",
    },
    "gemini-3.8-flash": {
        "tpm": 250000,
        "rpm": 5,
        "rpd": 20,
        "context_window": 1048576,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 8,
        "reset_tz": "PST (08:00 UTC)",
    },
    # Qwen Cloud models
    "qwen-plus-latest": {
        "tpm": 60000,
        "rpm": 30,
        "rpd": 10000,
        "context_window": 131072,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 0,
        "reset_tz": "UTC",
    },
}


def get_model_specs(model: str, provider: str) -> dict[str, Any]:
    """Retrieve theoretical specifications and maximum limits for a given model."""
    clean_model = model.strip()
    if clean_model.startswith("models/"):
        clean_model = clean_model[len("models/"):]
    if clean_model in MODEL_THEORETICAL_SPECS:
        return MODEL_THEORETICAL_SPECS[clean_model]

    # Defaults based on provider
    if provider == PROVIDER_GROQ_FREE:
        return {
            "tpm": 8000,
            "rpm": 30,
            "rpd": 14400,
            "context_window": 131072,
            "tpm_window_seconds": 60,
            "daily_reset_hour_utc": 0,
            "reset_tz": "UTC",
        }
    if provider == PROVIDER_GEMINI_FREE:
        return {
            "tpm": 250000,
            "rpm": 15,
            "rpd": 500,
            "context_window": 1048576,
            "tpm_window_seconds": 60,
            "daily_reset_hour_utc": 8,
            "reset_tz": "PST (08:00 UTC)",
        }
    return {
        "tpm": 60000,
        "rpm": 30,
        "rpd": 10000,
        "context_window": 128000,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 0,
        "reset_tz": "UTC",
    }


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

    # Sensors for cloud providers with rate limits, quotas, and token tracking.
    # Local models (Ollama) have no remote quotas or token limits.
    if provider in (
        PROVIDER_GEMINI_FREE,
        PROVIDER_GROQ_FREE,
        PROVIDER_QWEN_FREE,
        PROVIDER_CUSTOM_OPENAI,
    ):
        entities.append(NexusMcpTokenSensor(hass, entry))
        entities.append(NexusMcpDailyRequestsUsedSensor(hass, entry))
        entities.append(NexusMcpDailyQuotaSensor(hass, entry))
        entities.append(NexusMcpDailyQuotaPercentSensor(hass, entry))
        entities.append(NexusMcpDailyRequestsLimitSensor(hass, entry))
        entities.append(NexusMcpModelLimitSensor(hass, entry))
        entities.append(NexusMcpRpmLimitSensor(hass, entry))
        entities.append(NexusMcpMaxWaitSensor(hass, entry))
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
        self._attr_name = "Conversation History"
        self._attr_translation_key = "conversation_history"

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
            "sw_version": "1.4.2",
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
            "description": get_entity_description("conversation_history", self.hass),
            "conversation_id": last_conv_id,
            "total_conversations": len(history_dict),
            "total_messages": len(active_msgs),
            "last_user_query": last_user_query,
            "last_assistant_response": last_assistant_response,
            "history": raw_list,
            "formatted_markdown": formatted_md,
        }


class NexusMcpBaseTelemetrySensor(SensorEntity):
    """Base class for Nexus MCP telemetry, quota, and limit sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the base telemetry sensor."""
        self.hass = hass
        self.entry = entry

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
            "sw_version": "1.4.2",
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
    def telemetry(self) -> dict[str, Any]:
        """Return live telemetry metrics."""
        conv = self._conversation_entity
        return getattr(conv, "telemetry", {}) if conv else {}

    @property
    def model_specs(self) -> dict[str, Any]:
        """Return theoretical specs for model."""
        model_name = self.entry.options.get(CONF_MODEL, self.entry.data.get(CONF_MODEL, "Agent"))
        provider = self.entry.options.get(CONF_LLM_PROVIDER, self.entry.data.get(CONF_LLM_PROVIDER, ""))
        return get_model_specs(model_name, provider)


class NexusMcpTokenSensor(NexusMcpBaseTelemetrySensor):
    """Sensor exposing daily token consumption for the LLM model."""

    _attr_icon = "mdi:chart-timeline-variant-shimmer"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the daily tokens used sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_daily_tokens"
        self._attr_name = "Daily Tokens Used"
        self._attr_translation_key = "daily_tokens"
        self._attr_native_unit_of_measurement = "tokens"
        self._attr_state_class = getattr(SensorStateClass, "TOTAL_INCREASING", "total_increasing")

    @property
    def native_value(self) -> int:
        """Return the total tokens used today."""
        return int(self.telemetry.get("tokens_today", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed token telemetry attributes."""
        telem = self.telemetry
        return {
            "description": get_entity_description("daily_tokens", self.hass),
            "prompt_tokens_today": telem.get("prompt_tokens_today", 0),
            "completion_tokens_today": telem.get("completion_tokens_today", 0),
            "last_prompt_tokens": telem.get("last_prompt_tokens", 0),
            "last_completion_tokens": telem.get("last_completion_tokens", 0),
            "last_total_tokens": telem.get("last_total_tokens", 0),
            "remaining_tokens_minute": telem.get("remaining_tokens"),
            "limit_tokens_minute": telem.get("limit_tokens"),
            "model": telem.get("model", ""),
            "provider": telem.get("provider", ""),
            "date": telem.get("date"),
            "last_updated": telem.get("last_updated"),
        }


class NexusMcpDailyRequestsUsedSensor(NexusMcpBaseTelemetrySensor):
    """Sensor exposing total requests made today."""

    _attr_icon = "mdi:message-badge-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the daily requests used sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_daily_requests_used"
        self._attr_name = "Daily Requests Used"
        self._attr_translation_key = "daily_requests_used"
        self._attr_native_unit_of_measurement = "requests"
        self._attr_state_class = getattr(SensorStateClass, "TOTAL_INCREASING", "total_increasing")

    @property
    def native_value(self) -> int:
        """Return total queries submitted today."""
        return int(self.telemetry.get("requests_today", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra description and date attributes."""
        return {
            "description": get_entity_description("daily_requests_used", self.hass),
            "date": self.telemetry.get("date"),
            "last_updated": self.telemetry.get("last_updated"),
        }


class NexusMcpDailyQuotaSensor(NexusMcpBaseTelemetrySensor):
    """Sensor exposing remaining daily requests quota."""

    _attr_icon = "mdi:counter"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the daily requests remaining sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_daily_quota_remaining"
        self._attr_name = "Daily Requests Remaining"
        self._attr_translation_key = "daily_requests_remaining"
        self._attr_native_unit_of_measurement = "requests"

    @property
    def native_value(self) -> int:
        """Return remaining requests for today."""
        max_rpd = int(self.model_specs.get("rpd", 14400))
        used = int(self.telemetry.get("requests_today", 0))
        return max(0, max_rpd - used)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed daily quota attributes."""
        max_rpd = int(self.model_specs.get("rpd", 14400))
        used = int(self.telemetry.get("requests_today", 0))
        remaining = max(0, max_rpd - used)
        tokens_today = int(self.telemetry.get("tokens_today", 0))
        pct_str = f"{round((remaining / max_rpd) * 100, 2)}%" if max_rpd > 0 else "100.0%"
        return {
            "description": get_entity_description("daily_requests_remaining", self.hass),
            "daily_limit": max_rpd,
            "requests_used_today": used,
            "requests_remaining": remaining,
            "peticiones_restantes_hoy": remaining,
            "peticiones_usadas_hoy": used,
            "limite_diario_peticiones": max_rpd,
            "porcentaje_cuota_restante": pct_str,
            "tokens_consumidos_hoy": tokens_today,
        }


class NexusMcpDailyQuotaPercentSensor(NexusMcpBaseTelemetrySensor):
    """Sensor exposing remaining daily requests quota as percentage."""

    _attr_icon = "mdi:percent-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the daily quota percent sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_daily_quota_percent"
        self._attr_name = "Daily Quota Remaining"
        self._attr_translation_key = "daily_quota_percent"
        self._attr_native_unit_of_measurement = "%"
        self._attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float:
        """Return remaining quota percentage."""
        max_rpd = int(self.model_specs.get("rpd", 14400))
        used = int(self.telemetry.get("requests_today", 0))
        remaining = max(0, max_rpd - used)
        return round((remaining / max_rpd) * 100, 1) if max_rpd > 0 else 100.0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return description attribute."""
        return {
            "description": get_entity_description("daily_quota_percent", self.hass),
            "reset_hour": f"{self.model_specs.get('daily_reset_hour_utc', 0):02d}:00 UTC",
        }


class NexusMcpDailyRequestsLimitSensor(NexusMcpBaseTelemetrySensor):
    """Sensor exposing maximum daily requests limit (RPD)."""

    _attr_icon = "mdi:shield-check-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the daily requests limit sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_daily_requests_limit"
        self._attr_name = "Daily Requests Limit"
        self._attr_translation_key = "daily_requests_limit"
        self._attr_native_unit_of_measurement = "requests/day"

    @property
    def native_value(self) -> int:
        """Return maximum allowable requests per day."""
        return int(self.model_specs.get("rpd", 14400))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return description and timezone."""
        return {
            "description": get_entity_description("daily_requests_limit", self.hass),
            "timezone": self.model_specs.get("reset_tz", "UTC"),
        }


class NexusMcpModelLimitSensor(NexusMcpBaseTelemetrySensor):
    """Sensor exposing theoretical or live confirmed tokens per minute (TPM)."""

    _attr_icon = "mdi:gauge-full"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the tokens per minute limit sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_model_limit"
        self._attr_name = "Tokens Per Minute Limit"
        self._attr_translation_key = "model_limit"
        self._attr_native_unit_of_measurement = "tokens/min"

    @property
    def native_value(self) -> int:
        """Return the maximum input tokens per minute."""
        live = self.telemetry.get("limit_tokens")
        if live is not None:
            try:
                return int(live)
            except (ValueError, TypeError):
                pass
        return int(self.model_specs.get("tpm", 7000))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return description and context window."""
        model_name = self.entry.options.get(CONF_MODEL, self.entry.data.get(CONF_MODEL, "Agent"))
        provider = self.entry.options.get(CONF_LLM_PROVIDER, self.entry.data.get(CONF_LLM_PROVIDER, ""))
        live_rpm = self.telemetry.get("limit_requests")
        rpm_val = int(live_rpm) if live_rpm is not None else self.model_specs.get("rpm", 30)
        return {
            "description": get_entity_description("model_limit", self.hass),
            "tpm_maximo": self.native_value,
            "rpm_maximo": rpm_val,
            "rpd_maximo_diario": int(self.model_specs.get("rpd", 14400)),
            "context_window_tokens": self.model_specs.get("context_window", 131072),
            "model": model_name,
            "provider": provider,
        }


class NexusMcpRpmLimitSensor(NexusMcpBaseTelemetrySensor):
    """Sensor exposing theoretical or live confirmed requests per minute (RPM)."""

    _attr_icon = "mdi:speedometer"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the requests per minute limit sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_rpm_limit"
        self._attr_name = "Requests Per Minute Limit"
        self._attr_translation_key = "rpm_limit"
        self._attr_native_unit_of_measurement = "req/min"

    @property
    def native_value(self) -> int:
        """Return the maximum requests per minute."""
        live = self.telemetry.get("limit_requests")
        if live is not None:
            try:
                return int(live)
            except (ValueError, TypeError):
                pass
        return int(self.model_specs.get("rpm", 30))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return description."""
        return {
            "description": get_entity_description("rpm_limit", self.hass),
        }


class NexusMcpMaxWaitSensor(NexusMcpBaseTelemetrySensor):
    """Sensor exposing maximum wait time in seconds for the sliding window."""

    _attr_icon = "mdi:timer-sand-complete"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the max wait time sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_max_wait_time"
        self._attr_name = "Max Window Wait Time"
        self._attr_translation_key = "max_wait_time"
        self._attr_native_unit_of_measurement = "s"
        self._attr_suggested_display_precision = 0

    @property
    def native_value(self) -> int:
        """Return maximum wait seconds for per-minute token replenishment."""
        return int(self.model_specs.get("tpm_window_seconds", 60))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return description and wait breakdown."""
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        reset_hour = self.model_specs.get("daily_reset_hour_utc", 0)
        target_dt = now_utc.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
        if target_dt <= now_utc:
            target_dt += datetime.timedelta(days=1)
        sec_to_daily_reset = int((target_dt - now_utc).total_seconds())
        hours = sec_to_daily_reset // 3600
        minutes = (sec_to_daily_reset % 3600) // 60
        formatted_daily_wait = f"{hours}h {minutes}m"
        return {
            "description": get_entity_description("max_wait_time", self.hass),
            "espera_tope_tpm": "60 segundos (1 minuto para renovación completa de la ventana deslizante)",
            "segundos_hasta_reseteo_diario": sec_to_daily_reset,
            "hora_reseteo_diario": f"{reset_hour:02d}:00 UTC",
            "espera_tope_diario": formatted_daily_wait,
        }


class NexusMcpRateLimitResetSensor(NexusMcpBaseTelemetrySensor):
    """Sensor exposing real-time countdown seconds until next rate limit renewal."""

    _attr_icon = "mdi:timer-sand"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the rate limit cooldown sensor."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_rate_limit_reset"
        self._attr_name = "Rate Limit Cooldown"
        self._attr_translation_key = "rate_limit_reset"
        self._attr_native_unit_of_measurement = "s"
        self._attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float:
        """Return remaining seconds until rate limit unblock/reset (0 if ready)."""
        telem = self.telemetry
        reset_at_iso = telem.get("rate_limit_reset_at")
        if not reset_at_iso:
            return 0.0
        try:
            reset_dt = datetime.datetime.fromisoformat(reset_at_iso)
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            rem = (reset_dt - now_dt).total_seconds()
            return max(0.0, round(rem, 1))
        except Exception:
            return 0.0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return description, status, model, and provider."""
        rem_sec = self.native_value
        return {
            "description": get_entity_description("rate_limit_reset", self.hass),
            "status": "throttled" if rem_sec > 0 else "ready",
            "last_reset_duration": self.telemetry.get("rate_limit_reset_seconds", 0.0),
            "model": self.telemetry.get("model", ""),
            "provider": self.telemetry.get("provider", ""),
        }
