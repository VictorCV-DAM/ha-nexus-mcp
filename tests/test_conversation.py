"""Unit tests for the Nexus MCP Conversation Entity (Intercom)."""
import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

if "homeassistant" not in sys.modules:
    ha_mock = MagicMock()
    sys.modules["homeassistant"] = ha_mock
    sys.modules["homeassistant.config_entries"] = ha_mock
    sys.modules["homeassistant.core"] = ha_mock
    sys.modules["homeassistant.exceptions"] = ha_mock
    sys.modules["homeassistant.helpers"] = ha_mock
    sys.modules["homeassistant.helpers.config_validation"] = ha_mock
    sys.modules["homeassistant.helpers.aiohttp_client"] = ha_mock
    sys.modules["homeassistant.helpers.entity_platform"] = ha_mock
    sys.modules["homeassistant.helpers.intent"] = ha_mock
    sys.modules["homeassistant.components"] = ha_mock
    sys.modules["homeassistant.components.conversation"] = ha_mock

class FakeConversationEntity:
    pass

sys.modules["homeassistant.components.conversation"].ConversationEntity = FakeConversationEntity
ha_mock.components.conversation.ConversationEntity = FakeConversationEntity

class FakeIntentResponse:
    def __init__(self, language="en"):
        self.language = language
        self.speech_text = None

    def async_set_speech(self, text):
        self.speech_text = text

class FakeConversationResult:
    def __init__(self, response, conversation_id):
        self.response = response
        self.conversation_id = conversation_id

from custom_components.nexus_mcp.const import CONF_LLM_PROVIDER, PROVIDER_GEMINI_FREE
from custom_components.nexus_mcp.conversation import NexusMcpConversationEntity
from custom_components.nexus_mcp.llm_engine import LlmResponse


class TestConversationIntercom(unittest.IsolatedAsyncioTestCase):
    """Test conversation entity intercom behavior."""

    async def test_async_process_success(self) -> None:
        """Test processing user utterance and forwarding to LLM engine."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_1"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            mock_engine.generate_response.return_value = LlmResponse(
                content="Luz del salón apagada."
            )
            mock_factory.return_value = mock_engine

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            user_input = MagicMock()
            user_input.text = "Apaga la luz del salón"
            user_input.conversation_id = "conv_1"
            user_input.language = "es"

            result = await entity.async_process(user_input)

            self.assertEqual(result.conversation_id, "conv_1")
            self.assertEqual(result.response.speech_text, "Luz del salón apagada.")
            mock_engine.generate_response.assert_awaited_once()

    async def test_async_process_error_handling(self) -> None:
        """Test error handling when the server fails."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_2"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            mock_engine.generate_response.side_effect = RuntimeError("Connection refused")
            mock_factory.return_value = mock_engine

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            user_input = MagicMock()
            user_input.text = "¿Qué hora es?"
            user_input.conversation_id = "conv_2"
            user_input.language = "es"

            result = await entity.async_process(user_input)

            self.assertIn("Error al comunicar con el servidor de IA", result.response.speech_text)


if __name__ == "__main__":
    unittest.main()
