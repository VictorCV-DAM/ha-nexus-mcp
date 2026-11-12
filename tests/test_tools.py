"""Unit tests for Nexus MCP built-in tools and permission enforcement."""
import datetime
import json
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

for mod in [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.intent",
    "homeassistant.components",
    "homeassistant.components.conversation",
    "homeassistant.components.homeassistant",
    "homeassistant.components.homeassistant.exposed_entities",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()


class TestBuiltinTools(unittest.IsolatedAsyncioTestCase):
    """Test Home Assistant built-in tools, exposed entity filtering, and service calls."""

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

    async def test_ha_search_entities_respects_exposed_entities(self) -> None:
        """Verify ha_search_entities filters out entities not exposed to conversation."""
        from custom_components.nexus_mcp.tools import execute_builtin_tool

        mock_hass = MagicMock()
        state_exposed = MagicMock()
        state_exposed.entity_id = "light.exposed_light"
        state_exposed.state = "on"
        state_exposed.attributes = {"friendly_name": "Exposed Light"}

        state_hidden = MagicMock()
        state_hidden.entity_id = "light.hidden_light"
        state_hidden.state = "off"
        state_hidden.attributes = {"friendly_name": "Hidden Light"}

        mock_hass.states.async_all.return_value = [state_exposed, state_hidden]

        def fake_should_expose(hass, assistant, entity_id):
            return entity_id == "light.exposed_light"

        with patch("custom_components.nexus_mcp.tools.async_should_expose", side_effect=fake_should_expose):
            res = await execute_builtin_tool(mock_hass, "ha_search_entities", {"query": "light"})
            self.assertEqual(res["count"], 1)
            self.assertEqual(res["results"][0]["entity_id"], "light.exposed_light")

    async def test_ha_get_entity_state_unexposed_entity_denied(self) -> None:
        """Verify ha_get_entity_state denies access to unexposed entities."""
        from custom_components.nexus_mcp.tools import execute_builtin_tool

        mock_hass = MagicMock()
        state_hidden = MagicMock()
        state_hidden.entity_id = "lock.front_door"
        state_hidden.state = "locked"
        state_hidden.attributes = {"friendly_name": "Front Door"}
        mock_hass.states.get.return_value = state_hidden

        with patch("custom_components.nexus_mcp.tools.async_should_expose", return_value=False):
            res = await execute_builtin_tool(
                mock_hass, "ha_get_entity_state", {"entity_id": "lock.front_door"}
            )
            self.assertIn("not exposed", res["error"])

    async def test_ha_get_entity_state_datetime_serialization(self) -> None:
        """Verify ha_get_entity_state serializes datetime and date objects safely."""
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

        with patch("custom_components.nexus_mcp.tools.async_should_expose", return_value=True):
            res = await execute_builtin_tool(
                mock_hass, "ha_get_entity_state", {"entity_id": "sun.sun"}
            )
            self.assertEqual(res["entity_id"], "sun.sun")
            self.assertEqual(res["attributes"]["next_rising"], "2026-10-15T20:45:00")

            serialized = json.dumps(res)
            self.assertIn("2026-10-15T20:45:00", serialized)

    async def test_ha_call_service_immediate(self) -> None:
        """Verify ha_call_service executes immediately when delay is 0 and passes context."""
        from custom_components.nexus_mcp.tools import execute_builtin_tool

        mock_hass = MagicMock()
        mock_hass.services.async_call = AsyncMock()
        mock_context = MagicMock()

        res = await execute_builtin_tool(
            mock_hass,
            "ha_call_service",
            {
                "domain": "light",
                "service": "turn_on",
                "target": {"entity_id": "light.living_room"},
                "data": {"rgb_color": [0, 255, 0]},
            },
            context=mock_context,
        )
        self.assertEqual(res["status"], "success")
        mock_hass.services.async_call.assert_awaited_once_with(
            "light",
            "turn_on",
            {"entity_id": "light.living_room", "rgb_color": [0, 255, 0]},
            blocking=True,
            context=mock_context,
        )

    async def test_ha_call_service_admin_protection(self) -> None:
        """Verify ha_call_service blocks admin services for non-admin users."""
        from custom_components.nexus_mcp.tools import execute_builtin_tool

        mock_hass = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        non_admin_context = MagicMock()
        non_admin_context.user_id = "user_123"
        mock_user = MagicMock()
        mock_user.is_admin = False
        mock_hass.auth.async_get_user = AsyncMock(return_value=mock_user)

        with patch("custom_components.nexus_mcp.tools.async_should_expose", return_value=True):
            res = await execute_builtin_tool(
                mock_hass,
                "ha_call_service",
                {
                    "domain": "homeassistant",
                    "service": "restart",
                    "target": {"entity_id": "homeassistant.restart"},
                },
                context=non_admin_context,
            )
        self.assertEqual(res["status"], "error")
        self.assertIn("requires administrator privileges", res["message"])
        mock_hass.services.async_call.assert_not_called()

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

        res_taller = await execute_builtin_tool(
            mock_hass,
            "ha_search_entities",
            {"query": "luz del taller", "domain": "light"},
        )
        self.assertTrue(res_taller["count"] >= 1)
        self.assertEqual(res_taller["results"][0]["entity_id"], "switch.luz_taller_enchufe_1")

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
            context=None,
        )

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
            context=None,
        )

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
            context=None,
        )


    async def test_ha_call_service_target_security_hardening(self) -> None:
        """Verify ha_call_service rejects non-entity_id targets and enforces exposure on data['entity_id']."""
        from custom_components.nexus_mcp.tools import execute_builtin_tool

        mock_hass = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        # 1. Reject area_id in target
        res_area = await execute_builtin_tool(
            mock_hass,
            "ha_call_service",
            {"service": "light.turn_on", "target": {"area_id": "kitchen"}},
        )
        self.assertIn("error", res_area)
        self.assertIn("area_id", res_area["error"])

        # 2. Reject device_id in arguments
        res_dev = await execute_builtin_tool(
            mock_hass,
            "ha_call_service",
            {"service": "light.turn_on", "device_id": "dev_1234"},
        )
        self.assertIn("error", res_dev)
        self.assertIn("device_id", res_dev["error"])

        # 3. Reject floor_id and label_id
        res_floor = await execute_builtin_tool(
            mock_hass,
            "ha_call_service",
            {"service": "light.turn_on", "target": {"floor_id": "ground"}},
        )
        self.assertIn("error", res_floor)

        # 4. Reject unknown target key
        res_unknown = await execute_builtin_tool(
            mock_hass,
            "ha_call_service",
            {"service": "light.turn_on", "target": {"custom_target": "val"}},
        )
        self.assertIn("error", res_unknown)

        # 5. Extract entity_id from data and reject if not exposed
        with patch("custom_components.nexus_mcp.tools.async_should_expose", return_value=False):
            res_unexposed = await execute_builtin_tool(
                mock_hass,
                "ha_call_service",
                {"service": "light.turn_on", "data": {"entity_id": "light.hidden_light"}},
            )
            self.assertIn("error", res_unexposed)
            self.assertIn("not exposed", res_unexposed["error"])

        # 6. Extract entity_id from data and succeed if exposed
        with patch("custom_components.nexus_mcp.tools.async_should_expose", return_value=True):
            res_ok = await execute_builtin_tool(
                mock_hass,
                "ha_call_service",
                {"service": "light.turn_on", "data": {"entity_id": "light.safe_light", "brightness": 255}},
            )
            self.assertEqual(res_ok["status"], "success")
            mock_hass.services.async_call.assert_awaited_with(
                "light",
                "turn_on",
                {"entity_id": "light.safe_light", "brightness": 255},
                blocking=True,
                context=None,
            )



    async def test_ha_call_service_requires_exposed_target(self) -> None:
        """Verify ha_call_service rejects calls with no entity target and unexposed scripts."""
        from custom_components.nexus_mcp.tools import execute_builtin_tool

        mock_hass = MagicMock()
        mock_hass.services.async_call = AsyncMock()

        # 1. Target-less call (backup.create, recorder.purge, etc.) must be rejected
        res_no_target = await execute_builtin_tool(
            mock_hass,
            "ha_call_service",
            {"domain": "backup", "service": "create"},
        )
        self.assertIn("error", res_no_target)
        self.assertIn("At least one exposed 'entity_id' is required", res_no_target["error"])

        # 2. Target-less recorder.purge
        res_recorder = await execute_builtin_tool(
            mock_hass,
            "ha_call_service",
            {"domain": "recorder", "service": "purge"},
        )
        self.assertIn("error", res_recorder)
        self.assertIn("At least one exposed 'entity_id' is required", res_recorder["error"])

        # 3. Calling an unexposed script without target (e.g. service: script.secret_script)
        with patch("custom_components.nexus_mcp.tools.async_should_expose", return_value=False):
            res_unexposed_script = await execute_builtin_tool(
                mock_hass,
                "ha_call_service",
                {"domain": "script", "service": "secret_script"},
            )
            self.assertIn("error", res_unexposed_script)
            self.assertIn("not exposed", res_unexposed_script["error"])

        # 4. Calling an exposed script without target
        with patch("custom_components.nexus_mcp.tools.async_should_expose", return_value=True):
            res_exposed_script = await execute_builtin_tool(
                mock_hass,
                "ha_call_service",
                {"domain": "script", "service": "good_script"},
            )
            self.assertEqual(res_exposed_script["status"], "success")
            mock_hass.services.async_call.assert_awaited_with(
                "script",
                "good_script",
                {"entity_id": "script.good_script"},
                blocking=True,
                context=None,
            )

    async def test_ha_search_entities_and_get_state_includes_helpers(self) -> None:
        """Verify ha_search_entities and ha_get_entity_state find helpers even if unexposed."""
        from custom_components.nexus_mcp.tools import execute_builtin_tool

        mock_hass = MagicMock()
        state_btn = MagicMock()
        state_btn.entity_id = "input_button.sync_google_home"
        state_btn.state = "2026-11-12T18:00:00+00:00"
        state_btn.attributes = {"friendly_name": "Sincronizar Google Home"}

        mock_hass.states.async_all.return_value = [state_btn]
        mock_hass.states.get.return_value = state_btn

        # Even with async_should_expose returning False (default for helpers in HA)
        with patch("custom_components.nexus_mcp.tools.async_should_expose", return_value=False):
            res_search = await execute_builtin_tool(
                mock_hass,
                "ha_search_entities",
                {"query": "sync_google_home"}
            )
            self.assertEqual(res_search["count"], 1)
            self.assertEqual(res_search["results"][0]["entity_id"], "input_button.sync_google_home")

            res_state = await execute_builtin_tool(
                mock_hass,
                "ha_get_entity_state",
                {"entity_id": "input_button.sync_google_home"}
            )
            self.assertNotIn("error", res_state)
            self.assertEqual(res_state["entity_id"], "input_button.sync_google_home")

if __name__ == "__main__":
    unittest.main()
