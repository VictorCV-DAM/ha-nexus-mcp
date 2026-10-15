"""Unit tests for Nexus MCP built-in tools and automation sanitizer."""
import sys
import unittest
from unittest.mock import MagicMock

if "homeassistant" not in sys.modules:
    ha_mock = MagicMock()
    sys.modules["homeassistant"] = ha_mock
    sys.modules["homeassistant.core"] = ha_mock

from custom_components.nexus_mcp.tools import sanitize_automation_entry


class TestToolsSanitizer(unittest.IsolatedAsyncioTestCase):
    """Test Home Assistant automation sanitizer and tools."""

    def test_sanitize_time_pattern_and_domain_action(self) -> None:
        """Verify malformed pattern and domain actions are normalized."""
        raw = {
            "alias": "Reiniciar bombilla izquierda cada 5s",
            "trigger": [{"pattern": "00:00:05", "trigger": "time_pattern"}],
            "action": [
                {
                    "domain": "button",
                    "service": "press",
                    "target": {"entity_id": "button.bulb_rgbcw_6930e7_reiniciar"},
                }
            ],
            "mode": "single",
        }

        sanitized = sanitize_automation_entry(raw)
        trg = sanitized["trigger"][0]
        self.assertEqual(trg["platform"], "time_pattern")
        self.assertNotIn("pattern", trg)
        self.assertEqual(trg["seconds"], "/5")

        act = sanitized["action"][0]
        self.assertNotIn("domain", act)
        self.assertEqual(act["service"], "button.press")
        self.assertEqual(
            act["target"]["entity_id"], "button.bulb_rgbcw_6930e7_reiniciar"
        )

    def test_sanitize_single_dict_inputs(self) -> None:
        """Verify single dict inputs for trigger and action are converted to lists."""
        raw = {
            "alias": "Test Single Dict",
            "trigger": {"platform": "time_pattern", "seconds": "5"},
            "action": {"domain": "light", "service": "turn_on", "entity_id": "light.desk"},
        }

        sanitized = sanitize_automation_entry(raw)
        self.assertIsInstance(sanitized["trigger"], list)
        self.assertEqual(sanitized["trigger"][0]["seconds"], "/5")
        self.assertIsInstance(sanitized["action"], list)
        self.assertEqual(sanitized["action"][0]["service"], "light.turn_on")
        self.assertEqual(sanitized["action"][0]["target"]["entity_id"], "light.desk")


    async def test_ha_search_entities_flexible(self) -> None:
        """Verify ha_search_entities handles plurals, broad queries, and domain summaries."""
        from custom_components.nexus_mcp.tools import execute_builtin_tool

        mock_hass = MagicMock()
        state_light = MagicMock()
        state_light.entity_id = "light.living_room"
        state_light.state = "on"
        state_light.attributes = {"friendly_name": "Living Room Light"}

        state_switch = MagicMock()
        state_switch.entity_id = "switch.coffee_maker"
        state_switch.state = "off"
        state_switch.attributes = {"friendly_name": "Coffee Maker"}

        mock_hass.states.async_all.return_value = [state_light, state_switch]

        # 1. Search with plural 'lights' should match 'light.living_room'
        res_plural = await execute_builtin_tool(mock_hass, "ha_search_entities", {"query": "lights"})
        self.assertEqual(res_plural["count"], 1)
        self.assertEqual(res_plural["results"][0]["entity_id"], "light.living_room")

        # 2. Broad search with 'all' or empty should return available entities
        res_all = await execute_builtin_tool(mock_hass, "ha_search_entities", {"query": "all"})
        self.assertEqual(res_all["count"], 2)
        self.assertEqual(res_all["total_entities_in_ha"], 2)

        # 3. Non-matching query should return hint with available domains
        res_none = await execute_builtin_tool(mock_hass, "ha_search_entities", {"query": "non_existent"})
        self.assertEqual(res_none["count"], 0)
        self.assertIn("hint", res_none)
        self.assertIn("light", res_none["hint"])


if __name__ == "__main__":
    unittest.main()
