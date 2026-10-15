"""Unit tests for the Nexus MCP History Sensor and Dashboard integration."""
import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

if "homeassistant" not in sys.modules:
    ha_mock = MagicMock()
    sys.modules["homeassistant"] = ha_mock
else:
    ha_mock = sys.modules["homeassistant"]

for mod in [
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.components",
    "homeassistant.components.sensor",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

sys.modules["homeassistant.core"].callback = lambda func: func
ha_mock.core.callback = lambda func: func

class FakeSensorEntity:
    """Mock SensorEntity base class."""
    @property
    def unique_id(self):
        return getattr(self, "_attr_unique_id", None)

    def async_write_ha_state(self):
        pass

    def async_on_remove(self, func):
        pass

sys.modules["homeassistant.components.sensor"].SensorEntity = FakeSensorEntity
ha_mock.components.sensor.SensorEntity = FakeSensorEntity

from custom_components.nexus_mcp.const import DOMAIN
from custom_components.nexus_mcp.llm_engine import ChatMessage
from custom_components.nexus_mcp.sensor import (
    NexusMcpHistorySensor,
    NexusMcpTokenSensor,
    NexusMcpDailyQuotaSensor,
    NexusMcpRateLimitResetSensor,
    NexusMcpModelLimitSensor,
    NexusMcpMaxWaitSensor,
    async_setup_entry as async_setup_sensor_entry,
)
from custom_components.nexus_mcp import async_setup


class TestSensorHistory(unittest.IsolatedAsyncioTestCase):
    """Test Nexus MCP History Sensor behavior."""

    def setUp(self) -> None:
        """Set up test environment."""
        self.hass = MagicMock()
        self.entry = MagicMock()
        self.entry.entry_id = "test_sensor_entry"
        self.hass.data = {DOMAIN: {self.entry.entry_id: {}}}

    async def test_sensor_setup_entry(self) -> None:
        """Test async_setup_entry adds the sensor entity."""
        added_entities = []
        await async_setup_sensor_entry(
            self.hass, self.entry, lambda entities: added_entities.extend(entities)
        )
        self.assertEqual(len(added_entities), 1)
        self.assertIsInstance(added_entities[0], NexusMcpHistorySensor)
        self.assertEqual(
            added_entities[0].unique_id, "test_sensor_entry_conversation_history"
        )

    def test_sensor_empty_history(self) -> None:
        """Test sensor state and attributes when no conversation exists."""
        sensor = NexusMcpHistorySensor(self.hass, self.entry)
        self.assertEqual(sensor.native_value, "Sin conversaciones")

        attrs = sensor.extra_state_attributes
        self.assertEqual(attrs["total_conversations"], 0)
        self.assertEqual(attrs["total_messages"], 0)
        self.assertEqual(attrs["history"], [])
        self.assertIn("No hay conversaciones", attrs["formatted_markdown"])

    def test_sensor_with_active_conversation(self) -> None:
        """Test sensor reflects active conversations with formatted markdown."""
        sensor = NexusMcpHistorySensor(self.hass, self.entry)

        # Mock conversation entity in hass.data
        mock_conv_entity = MagicMock()
        mock_conv_entity._last_conversation_id = "conv_123"
        mock_conv_entity._history = {
            "conv_123": [
                ChatMessage(role="user", content="¿Qué temperatura hace en el salón?"),
                ChatMessage(role="assistant", content="Hay 21 grados."),
            ]
        }
        self.hass.data[DOMAIN][self.entry.entry_id]["conversation_entity"] = mock_conv_entity

        # State should be preview of last message
        self.assertEqual(sensor.native_value, "Hay 21 grados.")

        attrs = sensor.extra_state_attributes
        self.assertEqual(attrs["conversation_id"], "conv_123")
        self.assertEqual(attrs["total_conversations"], 1)
        self.assertEqual(attrs["total_messages"], 2)
        self.assertEqual(attrs["last_user_query"], "¿Qué temperatura hace en el salón?")
        self.assertEqual(attrs["last_assistant_response"], "Hay 21 grados.")

        # Formatted markdown checks
        md = attrs["formatted_markdown"]
        self.assertIn("🧑 **Tú:** ¿Qué temperatura hace en el salón?", md)
        self.assertIn("🤖 **Nexus:** Hay 21 grados.", md)

    def test_sensor_long_message_truncation(self) -> None:
        """Test sensor native_value truncates strings longer than 250 characters."""
        sensor = NexusMcpHistorySensor(self.hass, self.entry)

        mock_conv_entity = MagicMock()
        mock_conv_entity._last_conversation_id = "conv_long"
        long_content = "X" * 300
        mock_conv_entity._history = {
            "conv_long": [ChatMessage(role="assistant", content=long_content)]
        }
        self.hass.data[DOMAIN][self.entry.entry_id]["conversation_entity"] = mock_conv_entity

        val = sensor.native_value
        self.assertLessEqual(len(val), 250)
        self.assertTrue(val.endswith("..."))

    def test_sensor_dispatcher_callback(self) -> None:
        """Test dispatcher triggers state write."""
        sensor = NexusMcpHistorySensor(self.hass, self.entry)
        sensor.async_write_ha_state = MagicMock()

        sensor._handle_history_updated()
        sensor.async_write_ha_state.assert_called_once()

    async def test_clear_history_service(self) -> None:
        """Test clear_history service empties conversation history and updates store."""
        mock_hass = MagicMock()
        mock_hass.data = {DOMAIN: {}}
        mock_hass.services.has_service.return_value = False

        registered_services = {}
        def mock_register(domain, service, func):
            registered_services[f"{domain}.{service}"] = func

        mock_hass.services.async_register = mock_register

        await async_setup(mock_hass, {})
        self.assertIn(f"{DOMAIN}.clear_history", registered_services)

        # Mock an entity with history
        mock_conv_entity = MagicMock()
        mock_conv_entity._history = {"conv_1": [ChatMessage(role="user", content="Test")]}
        mock_conv_entity._last_conversation_id = "conv_1"
        mock_conv_entity._async_save_history = AsyncMock()

        mock_hass.data[DOMAIN]["entry_test"] = {"conversation_entity": mock_conv_entity}

        # Invoke service call
        service_handler = registered_services[f"{DOMAIN}.clear_history"]
        mock_call = MagicMock()
        mock_call.data = {"entry_id": "entry_test"}
        await service_handler(mock_call)

        self.assertEqual(len(mock_conv_entity._history), 0)
        self.assertIsNone(mock_conv_entity._last_conversation_id)
        mock_conv_entity._async_save_history.assert_awaited_once()

    async def test_frontend_card_registration(self) -> None:
        """Test _async_register_frontend registers static path and JS URL."""
        from custom_components.nexus_mcp import _async_register_frontend

        mock_hass = MagicMock()
        mock_hass.data = {}
        mock_hass.http = MagicMock()
        mock_hass.http.async_register_static_paths = AsyncMock()

        with patch("custom_components.nexus_mcp.add_extra_js_url") as mock_add_js, \
             patch("custom_components.nexus_mcp.StaticPathConfig") as mock_static_cfg:

            await _async_register_frontend(mock_hass)

            self.assertTrue(mock_hass.data[DOMAIN]["frontend_registered"])
            mock_add_js.assert_called_once()
            mock_hass.http.async_register_static_paths.assert_awaited_once()

            # Second call should be no-op (idempotent)
            await _async_register_frontend(mock_hass)
            mock_add_js.assert_called_once()

    async def test_sensor_setup_entry_cloud_provider(self) -> None:
        """Test async_setup_entry adds 5 entities for cloud providers (Gemini, Groq, etc.)."""
        from custom_components.nexus_mcp.const import CONF_LLM_PROVIDER, PROVIDER_GROQ_FREE
        from custom_components.nexus_mcp.sensor import (
            NexusMcpHistorySensor,
            NexusMcpMaxWaitSensor,
            NexusMcpModelLimitSensor,
            NexusMcpRateLimitResetSensor,
            NexusMcpTokenSensor,
        )

        cloud_entry = MagicMock()
        cloud_entry.entry_id = "cloud_entry_123"
        cloud_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GROQ_FREE}
        cloud_entry.options = {}

        added_entities = []
        await async_setup_sensor_entry(
            self.hass, cloud_entry, lambda entities: added_entities.extend(entities)
        )
        self.assertEqual(len(added_entities), 6)
        self.assertIsInstance(added_entities[0], NexusMcpHistorySensor)
        self.assertIsInstance(added_entities[1], NexusMcpTokenSensor)
        self.assertIsInstance(added_entities[2], NexusMcpDailyQuotaSensor)
        self.assertIsInstance(added_entities[3], NexusMcpRateLimitResetSensor)
        self.assertIsInstance(added_entities[4], NexusMcpModelLimitSensor)
        self.assertIsInstance(added_entities[5], NexusMcpMaxWaitSensor)

    async def test_sensor_setup_entry_local_ollama_skips_rate_limits(self) -> None:
        """Test async_setup_entry adds only history sensor for local models like Ollama."""
        from custom_components.nexus_mcp.const import CONF_LLM_PROVIDER, PROVIDER_OLLAMA_LOCAL
        from custom_components.nexus_mcp.sensor import NexusMcpHistorySensor

        local_entry = MagicMock()
        local_entry.entry_id = "ollama_entry_456"
        local_entry.data = {CONF_LLM_PROVIDER: PROVIDER_OLLAMA_LOCAL}
        local_entry.options = {}

        added_entities = []
        await async_setup_sensor_entry(
            self.hass, local_entry, lambda entities: added_entities.extend(entities)
        )
        # For local models, rate limit and token quota sensors must NOT be created
        self.assertEqual(len(added_entities), 1)
        self.assertIsInstance(added_entities[0], NexusMcpHistorySensor)

    def test_token_sensor_metrics_and_attributes(self) -> None:
        """Test NexusMcpTokenSensor extracts daily metrics and rate limits from conversation entity."""
        from custom_components.nexus_mcp.sensor import NexusMcpTokenSensor

        token_sensor = NexusMcpTokenSensor(self.hass, self.entry)
        self.assertEqual(token_sensor.native_value, 0)

        # Mock conversation entity with telemetry
        mock_conv_entity = MagicMock()
        mock_conv_entity.telemetry = {
            "tokens_today": 8420,
            "prompt_tokens_today": 6000,
            "completion_tokens_today": 2420,
            "last_prompt_tokens": 1200,
            "last_completion_tokens": 450,
            "last_total_tokens": 1650,
            "model": "openai/gpt-oss-120b",
            "provider": "groq_free",
            "remaining_tokens": 7180,
            "limit_tokens": 8000,
            "remaining_requests": 29,
            "limit_requests": 30,
            "date": "2026-10-15",
            "last_updated": "2026-10-15T20:00:00+00:00",
        }
        self.hass.data[DOMAIN][self.entry.entry_id]["conversation_entity"] = mock_conv_entity

        self.assertEqual(token_sensor.native_value, 8420)
        attrs = token_sensor.extra_state_attributes
        self.assertEqual(attrs["prompt_tokens_today"], 6000)
        self.assertEqual(attrs["completion_tokens_today"], 2420)
        self.assertEqual(attrs["last_total_tokens"], 1650)
        self.assertEqual(attrs["remaining_tokens_minute"], 7180)
        self.assertEqual(attrs["limit_tokens_minute"], 8000)
        self.assertEqual(attrs["model"], "openai/gpt-oss-120b")

    def test_rate_limit_reset_sensor_idle_and_throttled(self) -> None:
        """Test NexusMcpRateLimitResetSensor returns 0 when idle and countdown when throttled."""
        import datetime
        from custom_components.nexus_mcp.sensor import NexusMcpRateLimitResetSensor

        reset_sensor = NexusMcpRateLimitResetSensor(self.hass, self.entry)
        self.assertEqual(reset_sensor.native_value, 0.0)
        self.assertEqual(reset_sensor.extra_state_attributes["status"], "ready")

        # Mock throttled state in conversation entity
        mock_conv_entity = MagicMock()
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        reset_time = now_utc + datetime.timedelta(seconds=4.5)
        mock_conv_entity.telemetry = {
            "rate_limit_status": "throttled",
            "rate_limit_reset_seconds": 4.5,
            "rate_limit_reset_at": reset_time.isoformat(),
            "model": "openai/gpt-oss-20b",
            "provider": "groq_free",
            "remaining_tokens": 0,
            "limit_tokens": 8000,
        }
        self.hass.data[DOMAIN][self.entry.entry_id]["conversation_entity"] = mock_conv_entity

        val = reset_sensor.native_value
        self.assertGreater(val, 0.0)
        self.assertLessEqual(val, 5.0)

        attrs = reset_sensor.extra_state_attributes
        self.assertEqual(attrs["status"], "throttled")
        self.assertEqual(attrs["last_reset_duration"], 4.5)
        self.assertEqual(attrs["model"], "openai/gpt-oss-20b")

    def test_model_limit_sensor_defaults_and_live_update(self) -> None:
        """Test NexusMcpModelLimitSensor returns theoretical TPM and live confirmed limit."""
        from custom_components.nexus_mcp.const import CONF_LLM_PROVIDER, CONF_MODEL, PROVIDER_GROQ_FREE
        from custom_components.nexus_mcp.sensor import NexusMcpModelLimitSensor

        self.entry.data = {CONF_LLM_PROVIDER: PROVIDER_GROQ_FREE, CONF_MODEL: "openai/gpt-oss-120b"}
        self.entry.options = {}

        limit_sensor = NexusMcpModelLimitSensor(self.hass, self.entry)
        # Default theoretical TPM for 120b is 8000
        self.assertEqual(limit_sensor.native_value, 8000)

        attrs = limit_sensor.extra_state_attributes
        self.assertEqual(attrs["tpm_maximo"], 8000)
        self.assertEqual(attrs["rpm_maximo"], 30)
        self.assertEqual(attrs["rpd_maximo_diario"], 14400)
        self.assertEqual(attrs["context_window_tokens"], 131072)

        # Mock live update from server headers (e.g. user upgraded to dev tier or higher quota)
        mock_conv_entity = MagicMock()
        mock_conv_entity.telemetry = {"limit_tokens": 15000, "limit_requests": 60}
        self.hass.data[DOMAIN][self.entry.entry_id]["conversation_entity"] = mock_conv_entity

        self.assertEqual(limit_sensor.native_value, 15000)
        attrs_live = limit_sensor.extra_state_attributes
        self.assertEqual(attrs_live["tpm_maximo"], 15000)
        self.assertEqual(attrs_live["rpm_maximo"], 60)

    def test_max_wait_sensor_window_and_daily_reset(self) -> None:
        """Test NexusMcpMaxWaitSensor returns 60s window wait and daily reset calculation."""
        from custom_components.nexus_mcp.const import CONF_LLM_PROVIDER, CONF_MODEL, PROVIDER_GROQ_FREE
        from custom_components.nexus_mcp.sensor import NexusMcpMaxWaitSensor

        self.entry.data = {CONF_LLM_PROVIDER: PROVIDER_GROQ_FREE, CONF_MODEL: "openai/gpt-oss-120b"}
        self.entry.options = {}

        max_wait_sensor = NexusMcpMaxWaitSensor(self.hass, self.entry)
        self.assertEqual(max_wait_sensor.native_value, 60)

        attrs = max_wait_sensor.extra_state_attributes
        self.assertIn("60 segundos", attrs["espera_tope_tpm"])
        self.assertGreater(attrs["segundos_hasta_reseteo_diario"], 0)
        self.assertLessEqual(attrs["segundos_hasta_reseteo_diario"], 86400)
        self.assertIn("00:00 UTC", attrs["hora_reseteo_diario"])
        self.assertIn("h", attrs["espera_tope_diario"])

    def test_daily_quota_sensor_remaining_and_percentage(self) -> None:
        """Test NexusMcpDailyQuotaSensor calculates remaining daily requests and percentage."""
        from custom_components.nexus_mcp.const import CONF_LLM_PROVIDER, CONF_MODEL, PROVIDER_GROQ_FREE
        from custom_components.nexus_mcp.sensor import NexusMcpDailyQuotaSensor

        self.entry.data = {CONF_LLM_PROVIDER: PROVIDER_GROQ_FREE, CONF_MODEL: "qwen/qwen3.8-27b"}
        self.entry.options = {}

        quota_sensor = NexusMcpDailyQuotaSensor(self.hass, self.entry)
        # Default without requests made: full 14400
        self.assertEqual(quota_sensor.native_value, 14400)

        # Mock requests made today
        mock_conv_entity = MagicMock()
        mock_conv_entity.telemetry = {
            "requests_today": 12,
            "tokens_today": 6775,
        }
        self.hass.data[DOMAIN][self.entry.entry_id]["conversation_entity"] = mock_conv_entity

        self.assertEqual(quota_sensor.native_value, 14388)
        attrs = quota_sensor.extra_state_attributes
        self.assertEqual(attrs["peticiones_restantes_hoy"], 14388)
        self.assertEqual(attrs["peticiones_usadas_hoy"], 12)
        self.assertEqual(attrs["limite_diario_peticiones"], 14400)
        self.assertEqual(attrs["porcentaje_cuota_restante"], "99.92%")
        self.assertEqual(attrs["tokens_consumidos_hoy"], 6775)


if __name__ == "__main__":
    unittest.main()


