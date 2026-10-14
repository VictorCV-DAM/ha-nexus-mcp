"""Unit tests for the LLM Engine module."""
import asyncio
import json
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

from custom_components.nexus_mcp.const import (
    PROVIDER_CUSTOM_OPENAI,
    PROVIDER_GEMINI_FREE,
    PROVIDER_OLLAMA_LOCAL,
)
from custom_components.nexus_mcp.llm_engine import (
    ChatMessage,
    GeminiEngine,
    OpenAiCompatibleEngine,
    create_llm_engine,
)
from custom_components.nexus_mcp.mcp_client import McpTool


class TestLlmEngine(unittest.IsolatedAsyncioTestCase):
    """Test LLM Engine requests, parsing, and tool calls."""

    async def test_openai_compatible_tool_call(self) -> None:
        """Test OpenAI-compatible engine parsing tool_calls."""
        mock_session = MagicMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Searching for entities...",
                            "tool_calls": [
                                {
                                    "id": "call_123",
                                    "type": "function",
                                    "function": {
                                        "name": "search_entities",
                                        "arguments": '{"query": "living room"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        )

        # Mock context manager for session.post
        mock_session.post.return_value.__aenter__.return_value = mock_response

        engine = OpenAiCompatibleEngine(
            session=mock_session,
            base_url="http://localhost:11434/v1",
            model="qwen2.5-coder:7b",
        )

        messages = [ChatMessage(role="user", content="Find my living room lights")]
        tools = [
            McpTool(
                name="search_entities",
                description="Search entities",
                input_schema={"type": "object"},
            )
        ]

        resp = await engine.generate_response(messages, tools=tools)
        self.assertEqual(resp.content, "Searching for entities...")
        self.assertEqual(len(resp.tool_calls), 1)
        self.assertEqual(resp.tool_calls[0].name, "search_entities")
        self.assertEqual(
            resp.tool_calls[0].arguments, {"query": "living room"}
        )

    async def test_gemini_tool_call(self) -> None:
        """Test Gemini engine parsing functionCall."""
        mock_session = MagicMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "create_automation",
                                        "args": {"alias": "Turn on light"},
                                    }
                                }
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ]
            }
        )

        mock_session.post.return_value.__aenter__.return_value = mock_response

        engine = GeminiEngine(
            session=mock_session,
            api_key="test_api_key",
            model="gemini-2.0-flash",
        )
        self.assertEqual(engine._model, "gemini-3.1-flash-lite")

        messages = [ChatMessage(role="user", content="Create automation")]
        resp = await engine.generate_response(messages)
        self.assertEqual(len(resp.tool_calls), 1)
        self.assertEqual(resp.tool_calls[0].name, "create_automation")
        self.assertEqual(
            resp.tool_calls[0].arguments, {"alias": "Turn on light"}
        )

    async def test_gemini_thought_signature_preservation(self) -> None:
        """Test that GeminiEngine preserves thoughtSignature and sets functionResponse name."""
        mock_session = MagicMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "ha_call_service",
                                        "args": {"service": "light.turn_off"},
                                        "id": "call_123",
                                    },
                                    "thoughtSignature": "sig_xyz_123",
                                }
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ]
            }
        )
        mock_session.post.return_value.__aenter__.return_value = mock_response

        engine = GeminiEngine(
            session=mock_session,
            api_key="test_api_key",
            model="gemini-3.1-flash-lite",
        )

        messages = [ChatMessage(role="user", content="Turn off light")]
        resp = await engine.generate_response(messages)

        self.assertEqual(len(resp.tool_calls), 1)
        tc = resp.tool_calls[0]
        self.assertEqual(tc.name, "ha_call_service")
        self.assertEqual(tc.call_id, "call_123")
        self.assertEqual(tc.thought_signature, "sig_xyz_123")

        # Now test Turn 2 sending functionResponse
        turn2_messages = [
            ChatMessage(role="user", content="Turn off light"),
            ChatMessage(role="assistant", tool_calls=[tc]),
            ChatMessage(role="tool", content='{"success": true}', tool_name=tc.name, tool_call_id=tc.call_id),
        ]
        mock_response.json = AsyncMock(
            return_value={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Done!"}]},
                        "finishReason": "STOP",
                    }
                ]
            }
        )
        resp2 = await engine.generate_response(turn2_messages)
        self.assertEqual(resp2.content, "Done!")

        # Verify posted payload
        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]
        contents = payload["contents"]
        # Model turn should have thoughtSignature
        model_turn = contents[1]
        self.assertEqual(model_turn["role"], "model")
        self.assertEqual(model_turn["parts"][0]["thoughtSignature"], "sig_xyz_123")
        # User tool turn should have functionResponse with name 'ha_call_service'
        user_turn = contents[2]
        self.assertEqual(user_turn["role"], "user")
        self.assertEqual(user_turn["parts"][0]["functionResponse"]["name"], "ha_call_service")

    def test_factory_creation(self) -> None:
        """Test create_llm_engine factory for all providers."""
        mock_session = MagicMock()

        gemini_eng = create_llm_engine(
            PROVIDER_GEMINI_FREE, {"api_key": "abc"}, mock_session
        )
        self.assertIsInstance(gemini_eng, GeminiEngine)

        ollama_eng = create_llm_engine(
            PROVIDER_OLLAMA_LOCAL,
            {"base_url": "http://ollama:11434/v1"},
            mock_session,
        )
        self.assertIsInstance(ollama_eng, OpenAiCompatibleEngine)

        custom_eng = create_llm_engine(
            PROVIDER_CUSTOM_OPENAI,
            {"base_url": "https://api.openai.com/v1", "api_key": "xyz"},
            mock_session,
        )
        self.assertIsInstance(custom_eng, OpenAiCompatibleEngine)


if __name__ == "__main__":
    unittest.main()
