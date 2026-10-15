"""Unit tests for Nexus MCP Config and Options Flows."""
import sys
import unittest
from unittest.mock import MagicMock

if "voluptuous" not in sys.modules:
    vol_mock = MagicMock()
    vol_mock.Schema = lambda s: MagicMock()
    vol_mock.Required = lambda k, **kw: k
    vol_mock.Optional = lambda k, **kw: k
    vol_mock.In = lambda o: o
    sys.modules["voluptuous"] = vol_mock

class FakeConfigFlow:
    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
    def __init__(self):
        self.hass = MagicMock()
    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}
    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

class FakeOptionsFlow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
    def __init__(self, config_entry):
        self.config_entry = config_entry
        self.hass = MagicMock()
    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}
    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

if "homeassistant" not in sys.modules:
    ha_mock = MagicMock()
    sys.modules["homeassistant"] = ha_mock
    config_entries_mock = MagicMock()
    config_entries_mock.ConfigFlow = FakeConfigFlow
    config_entries_mock.OptionsFlow = FakeOptionsFlow
    ha_mock.config_entries = config_entries_mock
    sys.modules["homeassistant.config_entries"] = config_entries_mock
    sys.modules["homeassistant.core"] = ha_mock
    sys.modules["homeassistant.exceptions"] = ha_mock
    sys.modules["homeassistant.helpers"] = ha_mock
    sys.modules["homeassistant.helpers.config_validation"] = ha_mock
    sys.modules["homeassistant.helpers.aiohttp_client"] = ha_mock
    sys.modules["homeassistant.helpers.entity_platform"] = ha_mock
    sys.modules["homeassistant.helpers.intent"] = ha_mock
    sys.modules["homeassistant.components"] = ha_mock
    sys.modules["homeassistant.components.conversation"] = ha_mock
    sys.modules["homeassistant.data_entry_flow"] = ha_mock
else:
    sys.modules["homeassistant.config_entries"].ConfigFlow = FakeConfigFlow
    sys.modules["homeassistant.config_entries"].OptionsFlow = FakeOptionsFlow
    sys.modules["homeassistant"].config_entries.ConfigFlow = FakeConfigFlow
    sys.modules["homeassistant"].config_entries.OptionsFlow = FakeOptionsFlow

from custom_components.nexus_mcp.config_flow import NexusMcpConfigFlow, NexusMcpOptionsFlow
from custom_components.nexus_mcp.const import (
    CONF_API_KEY,
    CONF_AUTONOMOUS_MODE,
    CONF_BASE_URL,
    CONF_LLM_PROVIDER,
    CONF_MCP_SERVER_URL,
    CONF_MODEL,
    PROVIDER_GEMINI_FREE,
    PROVIDER_GROQ_FREE,
    PROVIDER_QWEN_FREE,
    PROVIDER_CUSTOM_OPENAI,
)


class TestConfigFlow(unittest.IsolatedAsyncioTestCase):
    """Test Nexus MCP ConfigFlow steps and placeholders."""

    async def test_step_user_has_all_placeholders(self) -> None:
        """Verify step_user provides links to all key providers."""
        flow = NexusMcpConfigFlow()
        flow.hass = MagicMock()

        result = await flow.async_step_user()
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "user")
        placeholders = result["description_placeholders"]
        self.assertIn("gemini_api_url", placeholders)
        self.assertIn("groq_api_url", placeholders)
        self.assertIn("qwen_api_url", placeholders)
        self.assertIn("openrouter_api_url", placeholders)

    async def test_step_custom_openai_has_placeholders(self) -> None:
        """Verify custom_openai step provides links for OpenRouter, OpenAI, and DeepSeek."""
        flow = NexusMcpConfigFlow()
        flow.hass = MagicMock()

        result = await flow.async_step_custom_openai()
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "custom_openai")
        placeholders = result["description_placeholders"]
        self.assertIn("openrouter_api_url", placeholders)
        self.assertIn("openai_api_url", placeholders)
        self.assertIn("deepseek_api_url", placeholders)

    async def test_options_flow_allows_updating_credentials_and_has_links(self) -> None:
        """Verify OptionsFlow exposes api_key, model, mcp_url and all provider links."""
        mock_entry = MagicMock()
        mock_entry.data = {
            CONF_LLM_PROVIDER: PROVIDER_GROQ_FREE,
            CONF_API_KEY: "gsk_test123",
            CONF_MODEL: "qwen/qwen3.8-27b",
            CONF_BASE_URL: "https://api.groq.com/openai/v1",
            CONF_MCP_SERVER_URL: "http://127.0.0.1:9584",
            CONF_AUTONOMOUS_MODE: False,
        }
        mock_entry.options = {}

        options_flow = NexusMcpOptionsFlow(mock_entry)
        options_flow.hass = MagicMock()

        result = await options_flow.async_step_init()
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "init")
        placeholders = result["description_placeholders"]
        self.assertIn("gemini_api_url", placeholders)
        self.assertIn("groq_api_url", placeholders)
        self.assertIn("qwen_api_url", placeholders)
        self.assertIn("openrouter_api_url", placeholders)
        self.assertIn("ha_mcp_repo_url", placeholders)

    async def test_step_mcp_server_creates_entry_with_model_in_title(self) -> None:
        """Verify async_step_mcp_server sets model in entry title."""
        flow = NexusMcpConfigFlow()
        flow.hass = MagicMock()
        flow._provider = PROVIDER_GROQ_FREE
        flow._llm_data = {
            CONF_LLM_PROVIDER: PROVIDER_GROQ_FREE,
            CONF_API_KEY: "gsk_test",
            CONF_MODEL: "llama-3.3-70b-versatile",
        }
        result = await flow.async_step_mcp_server(
            {CONF_MCP_SERVER_URL: "http://127.0.0.1:9584", CONF_AUTONOMOUS_MODE: False}
        )
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["title"], "Nexus MCP (llama-3.3-70b-versatile)")

    async def test_options_flow_updates_entry_title_on_model_change(self) -> None:
        """Verify OptionsFlow updates the entry title when model is modified."""
        mock_entry = MagicMock()
        mock_entry.title = "Nexus MCP (old-model)"
        mock_entry.data = {
            CONF_LLM_PROVIDER: PROVIDER_GROQ_FREE,
            CONF_API_KEY: "gsk_test",
            CONF_MODEL: "old-model",
            CONF_BASE_URL: "https://api.groq.com/openai/v1",
            CONF_MCP_SERVER_URL: "http://127.0.0.1:9584",
            CONF_AUTONOMOUS_MODE: False,
        }
        mock_entry.options = {}

        options_flow = NexusMcpOptionsFlow(mock_entry)
        options_flow.hass = MagicMock()

        await options_flow.async_step_init(
            {
                CONF_MODEL: "llama-3.3-70b-versatile",
                CONF_MCP_SERVER_URL: "http://127.0.0.1:9584",
                CONF_AUTONOMOUS_MODE: True,
            }
        )
        options_flow.hass.config_entries.async_update_entry.assert_called_once()
        call_kwargs = options_flow.hass.config_entries.async_update_entry.call_args[1]
        self.assertEqual(call_kwargs["title"], "Nexus MCP (llama-3.3-70b-versatile)")


if __name__ == "__main__":
    unittest.main()
