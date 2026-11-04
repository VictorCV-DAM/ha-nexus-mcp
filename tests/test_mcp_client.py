import sys
import unittest
from unittest.mock import MagicMock

# Provide lightweight stub for homeassistant when running tests outside HA environment
if "homeassistant" not in sys.modules:
    ha_mock = MagicMock()
    sys.modules["homeassistant"] = ha_mock
    sys.modules["homeassistant.config_entries"] = ha_mock
    sys.modules["homeassistant.core"] = ha_mock
    sys.modules["homeassistant.exceptions"] = ha_mock
    sys.modules["homeassistant.helpers"] = ha_mock
    sys.modules["homeassistant.helpers.config_validation"] = ha_mock

from custom_components.nexus_mcp.mcp_client import McpTool


class TestMcpTool(unittest.TestCase):
    """Test McpTool data model and schema transformations."""

    def test_schema_conversions(self) -> None:
        """Verify conversion to OpenAI and Gemini tool formats."""
        tool = McpTool(
            name="ha_call_service",
            description="Call a service in Home Assistant",
            input_schema={
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "target": {"type": "array"},
                },
                "required": ["service"],
            },
        )

        # OpenAI format check
        openai_fmt = tool.to_openai_tool()
        self.assertEqual(openai_fmt["type"], "function")
        self.assertEqual(openai_fmt["function"]["name"], "ha_call_service")
        self.assertEqual(openai_fmt["function"]["parameters"], tool.input_schema)

        # Gemini format check (verifies automatic array sanitization with items: {type: object})
        gemini_fmt = tool.to_gemini_tool()
        self.assertEqual(gemini_fmt["name"], "ha_call_service")
        self.assertEqual(
            gemini_fmt["parameters"]["properties"]["target"]["items"],
            {"type": "object"},
        )


if __name__ == "__main__":
    unittest.main()
