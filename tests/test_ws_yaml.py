import unittest
from unittest.mock import MagicMock
import sys

# Ensure Home Assistant mocks are established
if "homeassistant" not in sys.modules:
    ha_mock = MagicMock()
    for mod in [
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.core",
        "homeassistant.exceptions",
        "homeassistant.helpers",
        "homeassistant.helpers.config_validation",
        "homeassistant.helpers.aiohttp_client",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.intent",
        "homeassistant.components",
        "homeassistant.components.conversation",
        "homeassistant.components.websocket_api",
    ]:
        sys.modules[mod] = ha_mock
else:
    ha_mock = sys.modules["homeassistant"]

registered_handlers = {}

def fake_register_command(hass, func):
    registered_handlers[getattr(func, "__name__", str(func))] = func

ws_mock = MagicMock()
ws_mock.websocket_command = lambda schema: (lambda func: func)
ws_mock.async_response = lambda func: func
ws_mock.async_register_command = fake_register_command
sys.modules["homeassistant.components.websocket_api"] = ws_mock
sys.modules["homeassistant.components"].websocket_api = ws_mock

from custom_components.nexus_mcp import _async_setup_websocket, DOMAIN


class TestWebSocketYamlToJson(unittest.IsolatedAsyncioTestCase):
    """Test the nexus_mcp/yaml_to_json WebSocket handler."""

    async def asyncSetUp(self):
        self.hass = MagicMock()
        self.hass.data = {DOMAIN: {}}
        self.connection = MagicMock()
        self.connection.send_result = MagicMock()
        self.connection.send_error = MagicMock()

    def _get_handler(self):
        self.hass.data[DOMAIN] = {}
        _async_setup_websocket(self.hass)
        return registered_handlers.get("ws_handle_yaml_to_json")

    async def test_automation_yaml_parsing(self):
        handler = self._get_handler()
        self.assertIsNotNone(handler)

        yaml_content = """
alias: "Test Auto"
description: "Test Description"
trigger:
  - platform: state
    entity_id: binary_sensor.motion
    to: "on"
action:
  - service: light.turn_on
    target:
      entity_id: light.living_room
"""
        msg = {"id": 1, "type": "nexus_mcp/yaml_to_json", "yaml": yaml_content}
        await handler(self.hass, self.connection, msg)

        self.connection.send_result.assert_called_once()
        result = self.connection.send_result.call_args[0][1]
        self.assertTrue(result.get("is_automation"))
        self.assertFalse(result.get("is_update"))
        self.assertEqual(result["data"]["alias"], "Test Auto")
        self.assertTrue(result["data"]["id"].startswith("nexus_"))

    async def test_automation_update_yaml_parsing(self):
        handler = self._get_handler()
        yaml_content = """
id: "apagar_luz_taller_auto"
alias: "Apagar luz taller auto"
trigger:
  - platform: state
    entity_id: switch.luz_taller
    to: "on"
action:
  - service: switch.turn_off
    target:
      entity_id: switch.luz_taller
"""
        msg = {"id": 10, "type": "nexus_mcp/yaml_to_json", "yaml": yaml_content, "allow_update": True}
        await handler(self.hass, self.connection, msg)

        result = self.connection.send_result.call_args[0][1]
        self.assertTrue(result.get("is_automation"))
        self.assertTrue(result.get("is_update"))
        self.assertEqual(result["data"]["id"], "apagar_luz_taller_auto")

    async def test_helper_yaml_parsing(self):
        handler = self._get_handler()

        yaml_content = """
input_boolean:
  vacation_mode:
    name: "Modo Vacaciones"
    icon: "mdi:airplane"
"""
        msg = {"id": 2, "type": "nexus_mcp/yaml_to_json", "yaml": yaml_content}
        await handler(self.hass, self.connection, msg)

        self.connection.send_result.assert_called_once()
        result = self.connection.send_result.call_args[0][1]
        self.assertTrue(result.get("is_helper"))
        self.assertEqual(result.get("helper_domain"), "input_boolean")
        self.assertEqual(result.get("helper_id"), "vacation_mode")
        self.assertEqual(result["data"]["name"], "Modo Vacaciones")

    async def test_script_yaml_parsing(self):
        handler = self._get_handler()

        yaml_content = """
alias: "Secuencia Buenas Noches"
description: "Apaga todo y cierra"
sequence:
  - service: light.turn_off
    target:
      entity_id: all
  - service: switch.turn_off
    target:
      entity_id: switch.termo
mode: single
"""
        msg = {"id": 3, "type": "nexus_mcp/yaml_to_json", "yaml": yaml_content}
        await handler(self.hass, self.connection, msg)

        self.connection.send_result.assert_called_once()
        result = self.connection.send_result.call_args[0][1]
        self.assertTrue(result.get("is_script"))
        self.assertEqual(result["data"]["alias"], "Secuencia Buenas Noches")
        self.assertEqual(len(result["data"]["sequence"]), 2)
        self.assertTrue(result.get("script_id").startswith("nexus_script_"))

    async def test_scene_yaml_parsing(self):
        handler = self._get_handler()

        yaml_content = """
name: "Modo Cine"
icon: "mdi:movie"
entities:
  light.living_room:
    state: "on"
    brightness: 40
  switch.projector:
    state: "on"
"""
        msg = {"id": 4, "type": "nexus_mcp/yaml_to_json", "yaml": yaml_content}
        await handler(self.hass, self.connection, msg)

        self.connection.send_result.assert_called_once()
        result = self.connection.send_result.call_args[0][1]
        self.assertTrue(result.get("is_scene"))
        self.assertEqual(result["data"]["name"], "Modo Cine")
        self.assertIn("light.living_room", result["data"]["entities"])
        self.assertTrue(result.get("scene_id").startswith("nexus_scene_"))

    async def test_card_yaml_parsing(self):
        handler = self._get_handler()

        yaml_content = """
type: tile
entity: light.luz_taller
name: "Luz Taller LED"
color: amber
icon: mdi:lamp
"""
        msg = {"id": 5, "type": "nexus_mcp/yaml_to_json", "yaml": yaml_content}
        await handler(self.hass, self.connection, msg)

        self.connection.send_result.assert_called_once()
        result = self.connection.send_result.call_args[0][1]
        self.assertTrue(result.get("is_card"))
        self.assertEqual(result.get("card_type"), "tile")
        self.assertEqual(result.get("title"), "Luz Taller LED")
        self.assertEqual(result["data"]["entity"], "light.luz_taller")
        self.assertEqual(result.get("resource_type"), "card")

    async def test_card_yaml_update_mode(self):
        handler = self._get_handler()
        yaml_content = """
type: custom:mushroom-entity-card
entity: switch.enchufe_carga_oukitel
name: Carga Oukitel
icon: mdi:power
"""
        msg = {"id": 6, "type": "nexus_mcp/yaml_to_json", "yaml": yaml_content, "mode": "update"}
        await handler(self.hass, self.connection, msg)

        result = self.connection.send_result.call_args[0][1]
        self.assertTrue(result.get("is_card"))
        self.assertTrue(result.get("is_update"))
        self.assertEqual(result.get("resource_type"), "card")

    async def test_modern_script_action_syntax(self):
        handler = self._get_handler()
        yaml_content = """
alias: "Encender Enchufe Oukitel"
action:
  - action: switch.turn_on
    target:
      entity_id: switch.enchufe_carga_oukitel
"""
        msg = {"id": 7, "type": "nexus_mcp/yaml_to_json", "yaml": yaml_content}
        await handler(self.hass, self.connection, msg)

        result = self.connection.send_result.call_args[0][1]
        self.assertTrue(result.get("is_script"))
        self.assertEqual(result.get("resource_type"), "script")
        self.assertEqual(result["data"]["alias"], "Encender Enchufe Oukitel")
        self.assertIn("sequence", result["data"])

    async def test_truncated_yaml_auto_repair(self):
        handler = self._get_handler()
        # Truncated YAML where model cut off mid-token on line 4
        yaml_content = """type: custom:button-card
entity: switch.enchufe_carga_oukitel
name: Carga Oukitel
show"""
        msg = {"id": 8, "type": "nexus_mcp/yaml_to_json", "yaml": yaml_content}
        await handler(self.hass, self.connection, msg)

        self.connection.send_result.assert_called_once()
        result = self.connection.send_result.call_args[0][1]
        self.assertTrue(result.get("is_card"))
        self.assertEqual(result["data"]["type"], "custom:button-card")
        self.assertEqual(result["data"]["entity"], "switch.enchufe_carga_oukitel")


if __name__ == "__main__":
    unittest.main()
