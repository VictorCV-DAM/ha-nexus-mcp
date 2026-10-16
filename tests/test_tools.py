"""Unit tests for Nexus MCP built-in tools and automation sanitizer."""
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

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

    async def test_ha_get_entity_state_datetime_serialization(self) -> None:
        """Verify ha_get_entity_state serializes datetime and date objects safely."""
        import datetime
        import json
        from custom_components.nexus_mcp.tools import execute_builtin_tool

        mock_hass = MagicMock()
        state_sun = MagicMock()
        state_sun.entity_id = "sun.sun"
        state_sun.state = "above_horizon"
        now_dt = datetime.datetime(2026, 10, 15, 20, 45, 0)
        state_sun.attributes = {
            "friendly_name": "Sun",
            "next_rising": now_dt,
            "next_setting": now_dt,
            "supported_modes": {"day", "night"},
        }
        mock_hass.states.get.return_value = state_sun

        res = await execute_builtin_tool(
            mock_hass, "ha_get_entity_state", {"entity_id": "sun.sun"}
        )
        self.assertEqual(res["entity_id"], "sun.sun")
        self.assertEqual(res["attributes"]["next_rising"], "2026-10-15T20:45:00")

        # Must serialize cleanly with standard json.dumps
        serialized = json.dumps(res)
        self.assertIn("2026-10-15T20:45:00", serialized)

    async def test_ha_call_service_immediate(self) -> None:
        """Verify ha_call_service executes immediately when delay is 0."""
        from custom_components.nexus_mcp.tools import execute_builtin_tool

        mock_hass = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        res = await execute_builtin_tool(
            mock_hass,
            "ha_call_service",
            {
                "domain": "light",
                "service": "turn_on",
                "target": {"entity_id": "light.living_room"},
                "data": {"rgb_color": [0, 255, 0]},
            },
        )
        self.assertEqual(res["status"], "success")
        mock_hass.services.async_call.assert_awaited_once_with(
            "light",
            "turn_on",
            {"entity_id": "light.living_room", "rgb_color": [0, 255, 0]},
            blocking=True,
        )

    async def test_ha_call_service_with_delay(self) -> None:
        """Verify ha_call_service schedules execution when delay is provided."""
        from custom_components.nexus_mcp.tools import execute_builtin_tool

        mock_hass = MagicMock()
        mock_hass.services.async_call = AsyncMock()
        created_tasks = []
        def fake_create_task(coro):
            created_tasks.append(coro)
            coro.close()
            return MagicMock()

        mock_hass.async_create_task = fake_create_task

        res = await execute_builtin_tool(
            mock_hass,
            "ha_call_service",
            {
                "domain": "light",
                "service": "turn_off",
                "target": {"entity_id": ["light.left", "light.right"]},
                "delay": 5,
            },
        )
        self.assertEqual(res["status"], "scheduled")
        self.assertIn("scheduled to execute in 5.0 seconds", res["message"])
        self.assertEqual(len(created_tasks), 1)


    async def test_ha_search_entities_light_switch_fallback_and_ranking(self) -> None:
        """Verify ha_search_entities finds smart plug switches when searching for lights and ranks properly."""
        from custom_components.nexus_mcp.tools import execute_builtin_tool

        mock_hass = MagicMock()
        state_workshop_plug = MagicMock()
        state_workshop_plug.entity_id = "switch.luz_taller_enchufe_1"
        state_workshop_plug.state = "off"
        state_workshop_plug.attributes = {"friendly_name": "Socket 1"}

        state_bar_light = MagicMock()
        state_bar_light.entity_id = "light.barra_de_luz"
        state_bar_light.state = "off"
        state_bar_light.attributes = {"friendly_name": "Barra de luz"}

        state_left_bulb = MagicMock()
        state_left_bulb.entity_id = "light.bombilla_izquierda"
        state_left_bulb.state = "off"
        state_left_bulb.attributes = {"friendly_name": "Bombilla Izquierda"}

        mock_hass.states.async_all.return_value = [state_bar_light, state_workshop_plug, state_left_bulb]

        # 1. Searching for 'luz del taller' with domain='light' should match switch.luz_taller_enchufe_1
        # and rank it ABOVE light.barra_de_luz
        res_taller = await execute_builtin_tool(
            mock_hass,
            "ha_search_entities",
            {"query": "luz del taller", "domain": "light"},
        )
        self.assertTrue(res_taller["count"] >= 1)
        self.assertEqual(res_taller["results"][0]["entity_id"], "switch.luz_taller_enchufe_1")

        # 2. Searching for 'bombilla izquierda'
        res_bulb = await execute_builtin_tool(
            mock_hass,
            "ha_search_entities",
            {"query": "bombilla izquierda"},
        )
        self.assertEqual(res_bulb["results"][0]["entity_id"], "light.bombilla_izquierda")

    async def test_ha_call_service_smart_routing(self) -> None:
        """Verify ha_call_service resolves missing domain and reroutes light.turn_on on switch entities."""
        from custom_components.nexus_mcp.tools import execute_builtin_tool

        mock_hass = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        # 1. Missing domain with turn_on and target switch.luz_taller_enchufe_1 -> routes to switch or homeassistant
        await execute_builtin_tool(
            mock_hass,
            "ha_call_service",
            {"service": "turn_on", "target": {"entity_id": "switch.luz_taller_enchufe_1"}},
        )
        mock_hass.services.async_call.assert_awaited_with(
            "switch",
            "turn_on",
            {"entity_id": "switch.luz_taller_enchufe_1"},
            blocking=True,
        )

        # 2. Calling domain 'light' on switch.luz_taller_enchufe_1 -> automatically redirects to 'homeassistant'
        await execute_builtin_tool(
            mock_hass,
            "ha_call_service",
            {"domain": "light", "service": "turn_on", "target": {"entity_id": "switch.luz_taller_enchufe_1"}},
        )
        mock_hass.services.async_call.assert_awaited_with(
            "homeassistant",
            "turn_on",
            {"entity_id": "switch.luz_taller_enchufe_1"},
            blocking=True,
        )

        # 3. Handling service_data from Ollama local model format
        await execute_builtin_tool(
            mock_hass,
            "ha_call_service",
            {
                "service": "turn_on",
                "service_data": {"entity_id": "light.bombilla_izquierda", "brightness": 200},
            },
        )
        mock_hass.services.async_call.assert_awaited_with(
            "light",
            "turn_on",
            {"entity_id": "light.bombilla_izquierda", "brightness": 200},
            blocking=True,
        )


if __name__ == "__main__":
    unittest.main()

