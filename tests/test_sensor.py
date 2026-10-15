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


if __name__ == "__main__":
    unittest.main()
