"""Unit tests for Nexus MCP built-in tools and automation sanitizer."""
import sys
import unittest
from unittest.mock import MagicMock

if "homeassistant" not in sys.modules:
    ha_mock = MagicMock()
    sys.modules["homeassistant"] = ha_mock
    sys.modules["homeassistant.core"] = ha_mock

from custom_components.nexus_mcp.tools import sanitize_automation_entry


class TestToolsSanitizer(unittest.TestCase):
    """Test Home Assistant automation sanitizer."""

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


if __name__ == "__main__":
    unittest.main()
