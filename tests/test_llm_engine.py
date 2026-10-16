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
    PROVIDER_GROQ_FREE,
    PROVIDER_OLLAMA_LOCAL,
    PROVIDER_QWEN_FREE,
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

    async def test_openai_compatible_assistant_tool_call_string_content(self) -> None:
        """Test that assistant messages with tool_calls and content=None have content as empty string, never omitted."""
        mock_session = MagicMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "choices": [{"message": {"role": "assistant", "content": "Done"}}]
            }
        )
        mock_session.post.return_value.__aenter__.return_value = mock_response

        engine = OpenAiCompatibleEngine(
            session=mock_session,
            base_url="https://api.groq.com/openai/v1",
            model="openai/gpt-oss-120b",
        )

        from custom_components.nexus_mcp.llm_engine import LlmToolCall
        tc = LlmToolCall(call_id="call_abc", name="ha_search_entities", arguments={})
        messages = [
            ChatMessage(role="user", content="Turn off lights"),
            ChatMessage(role="assistant", content=None, tool_calls=[tc]),
            ChatMessage(role="tool", content='{"result": "ok"}', tool_call_id="call_abc", tool_name="ha_search_entities"),
        ]

        await engine.generate_response(messages)

        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]
        api_messages = payload["messages"]

        # Ensure message 1 (assistant with tool calls) has content as string
        asst_msg = api_messages[1]
        self.assertIn("content", asst_msg)
        self.assertIsInstance(asst_msg["content"], str)
        self.assertEqual(asst_msg["content"], "")

    async def test_openai_compatible_image_handling(self) -> None:
        """Test that text models (e.g. Groq 120b) receive string content for images, while vision models receive array."""
        mock_session = MagicMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "choices": [{"message": {"role": "assistant", "content": "I see it"}}]
            }
        )
        mock_session.post.return_value.__aenter__.return_value = mock_response

        # 1. Text model on Groq: must convert to string
        engine_text = OpenAiCompatibleEngine(
            session=mock_session,
            base_url="https://api.groq.com/openai/v1",
            model="openai/gpt-oss-120b",
        )
        msg_with_img = ChatMessage(
            role="user",
            content="What is this?",
            image_data="data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==",
        )
        await engine_text.generate_response([msg_with_img])

        payload_text = mock_session.post.call_args[1]["json"]
        user_msg_text = payload_text["messages"][0]
        self.assertIsInstance(user_msg_text["content"], str)
        self.assertIn("[Attached Image]", user_msg_text["content"])
        self.assertIn("What is this?", user_msg_text["content"])

        # 2. Vision model (e.g. gpt-4o): sends multimodal array
        engine_vision = OpenAiCompatibleEngine(
            session=mock_session,
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
        )
        await engine_vision.generate_response([msg_with_img])

        payload_vision = mock_session.post.call_args[1]["json"]
        user_msg_vision = payload_vision["messages"][0]
        self.assertIsInstance(user_msg_vision["content"], list)
        self.assertEqual(user_msg_vision["content"][0]["type"], "text")
        self.assertEqual(user_msg_vision["content"][1]["type"], "image_url")

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

        groq_eng = create_llm_engine(
            PROVIDER_GROQ_FREE, {"api_key": "gsk_123"}, mock_session
        )
        self.assertIsInstance(groq_eng, OpenAiCompatibleEngine)

        qwen_eng = create_llm_engine(
            PROVIDER_QWEN_FREE, {"api_key": "sk-123"}, mock_session
        )
        self.assertIsInstance(qwen_eng, OpenAiCompatibleEngine)

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

    def test_sanitize_openai_api_messages(self) -> None:
        """Test sanitization ensures valid user query, merges consecutive users, and fixes orphan tools."""
        from custom_components.nexus_mcp.llm_engine import (
            sanitize_openai_api_messages,
            prune_api_messages_for_budget,
        )

        # 1. No user query -> auto-inject user query
        msgs = [{"role": "system", "content": "Sys prompt"}]
        sanitized = sanitize_openai_api_messages(msgs)
        self.assertEqual(len(sanitized), 2)
        self.assertEqual(sanitized[1]["role"], "user")

        # 2. Consecutive users -> merged
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "World"},
        ]
        sanitized = sanitize_openai_api_messages(msgs)
        self.assertEqual(len(sanitized), 1)
        self.assertEqual(sanitized[0]["content"], "Hello\n\nWorld")

        # 3. Orphan tool -> converted to assistant
        msgs = [
            {"role": "tool", "content": "results", "tool_call_id": "orphan_call"}
        ]
        sanitized = sanitize_openai_api_messages(msgs)
        self.assertEqual(sanitized[0]["role"], "user")  # injected user first
        self.assertEqual(sanitized[1]["role"], "assistant")

        # 4. Budget pruning preserves active user query and tool calls
        msgs = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Old query"},
            {"role": "assistant", "content": "Old answer"},
            {"role": "user", "content": "Active command"},
            {
                "role": "assistant",
                "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "x" * 500},
        ]
        pruned = prune_api_messages_for_budget(msgs)
        roles = [m["role"] for m in pruned]
        self.assertIn("user", roles)
        self.assertEqual(pruned[1]["content"], "Active command")
        self.assertTrue(pruned[-1]["content"].endswith("... [trimmed]"))

    def test_extract_fallback_tool_calls(self) -> None:
        """Test extraction of tool calls from XML tags and markdown code blocks emitted by local LLMs."""
        from custom_components.nexus_mcp.llm_engine import extract_fallback_tool_calls
        from custom_components.nexus_mcp.mcp_client import McpTool

        tools = [
            McpTool(name="ha_call_service", description="Call service", input_schema={}),
            McpTool(name="ha_search_entities", description="Search entities", input_schema={}),
        ]

        # 1. Ollama Qwen Coder style: <tools> tag with single JSON
        content1 = (
            "<tools>\n"
            '{"name": "ha_call_service", "arguments": {"domain": "light", "service": "turn_on", "service_data": {"entity_id": "light.cocina"}}}\n'
            "</tools>"
        )
        calls1, rem1 = extract_fallback_tool_calls(content1, tools)
        self.assertEqual(len(calls1), 1)
        self.assertEqual(calls1[0].name, "ha_call_service")
        self.assertEqual(calls1[0].arguments["domain"], "light")
        self.assertEqual(calls1[0].arguments["service_data"]["entity_id"], "light.cocina")
        self.assertIsNone(rem1)

        # 2. Multiple tool calls in single <tools> block (NDJSON)
        content2 = (
            "<tools>\n"
            '{"name": "ha_call_service", "arguments": {"domain": "light", "service": "turn_on", "service_data": {"entity_id": "light.cocina"}}}\n'
            '{"name": "ha_call_service", "arguments": {"domain": "light", "service": "turn_off", "service_data": {"entity_id": "light.salon"}}}\n'
            "</tools>"
        )
        calls2, rem2 = extract_fallback_tool_calls(content2, tools)
        self.assertEqual(len(calls2), 2)
        self.assertEqual(calls2[0].arguments["service_data"]["entity_id"], "light.cocina")
        self.assertEqual(calls2[1].arguments["service_data"]["entity_id"], "light.salon")
        self.assertIsNone(rem2)

        # 3. Markdown code block with conversational prefix
        content3 = (
            "Voy a encender la luz:\n"
            "```json\n"
            '{"name": "ha_call_service", "arguments": {"domain": "light", "service": "turn_on"}}\n'
            "```"
        )
        calls3, rem3 = extract_fallback_tool_calls(content3, tools)
        self.assertEqual(len(calls3), 1)
        self.assertEqual(calls3[0].name, "ha_call_service")
        self.assertEqual(rem3, "Voy a encender la luz:")


if __name__ == "__main__":
    unittest.main()
