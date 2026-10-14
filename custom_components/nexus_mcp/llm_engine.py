"""Universal LLM engine adapter for Nexus MCP.

Supports Google Gemini Free Tier, Ollama (Qwen 2.5 Coder), and OpenAI-compatible endpoints.
Uses aiohttp directly to eliminate external dependencies in Home Assistant.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import logging
from typing import Any

import aiohttp

from .const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_MODEL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_URL,
    PROVIDER_CUSTOM_OPENAI,
    PROVIDER_GEMINI_FREE,
    PROVIDER_OLLAMA_LOCAL,
)
from .mcp_client import McpTool

_LOGGER = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class LlmError(Exception):
    """Base exception for LLM errors."""


class LlmAuthError(LlmError):
    """Raised on authentication / API key failure."""


class LlmRateLimitError(LlmError):
    """Raised when rate limits are exceeded."""


@dataclass
class LlmToolCall:
    """Represents a tool call requested by the LLM."""

    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatMessage:
    """Standardized chat message."""

    role: str  # "system", "user", "assistant", "tool"
    content: str | None = None
    tool_calls: list[LlmToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # Used when role is "tool"


@dataclass
class LlmResponse:
    """Unified response from any LLM provider."""

    content: str | None
    tool_calls: list[LlmToolCall] = field(default_factory=list)
    finish_reason: str | None = None


class BaseLlmEngine(ABC):
    """Abstract base class for LLM engines."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the engine with an aiohttp session."""
        self._session = session

    @abstractmethod
    async def generate_response(
        self,
        messages: list[ChatMessage],
        tools: list[McpTool] | None = None,
        system_prompt: str | None = None,
    ) -> LlmResponse:
        """Generate response and handle tool calls."""


class OpenAiCompatibleEngine(BaseLlmEngine):
    """Engine for Ollama (Qwen 2.5 Coder), OpenAI, DashScope, and Groq."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        model: str,
        api_key: str | None = None,
    ) -> None:
        super().__init__(session)
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key or "sk-no-key-required"

    async def generate_response(
        self,
        messages: list[ChatMessage],
        tools: list[McpTool] | None = None,
        system_prompt: str | None = None,
    ) -> LlmResponse:
        """Send chat completion request to OpenAI-compatible endpoint."""
        url = f"{self._base_url}/chat/completions"
        if not self._base_url.endswith("/v1") and "v1" not in self._base_url:
            url = f"{self._base_url}/v1/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        # Convert standardized messages to OpenAI format
        api_messages: list[dict[str, Any]] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            msg_dict: dict[str, Any] = {"role": msg.role}
            if msg.content is not None:
                msg_dict["content"] = msg.content
            if msg.role == "tool" and msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            api_messages.append(msg_dict)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
        }

        if tools:
            payload["tools"] = [tool.to_openai_tool() for tool in tools]
            payload["tool_choice"] = "auto"

        try:
            async with self._session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 401:
                    raise LlmAuthError("Invalid API key or unauthorized access.")
                if resp.status == 429:
                    raise LlmRateLimitError("Rate limit exceeded for provider.")
                if resp.status != 200:
                    text = await resp.text()
                    raise LlmError(f"HTTP {resp.status} from {url}: {text}")

                data = await resp.json()
        except aiohttp.ClientError as err:
            raise LlmError(f"Network error connecting to {url}: {err}") from err

        choice = data["choices"][0]
        message_data = choice["message"]
        content = message_data.get("content")

        tool_calls: list[LlmToolCall] = []
        raw_tool_calls = message_data.get("tool_calls", [])
        for rtc in raw_tool_calls:
            call_id = rtc.get("id", "call_default")
            fn = rtc.get("function", {})
            fn_name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(LlmToolCall(call_id=call_id, name=fn_name, arguments=args))

        return LlmResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
        )


class GeminiEngine(BaseLlmEngine):
    """Engine for Google Gemini Free Tier using direct REST calls."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        model: str = DEFAULT_GEMINI_MODEL,
    ) -> None:
        super().__init__(session)
        self._api_key = api_key
        self._model = model

    async def generate_response(
        self,
        messages: list[ChatMessage],
        tools: list[McpTool] | None = None,
        system_prompt: str | None = None,
    ) -> LlmResponse:
        """Call Gemini generateContent endpoint."""
        url = f"{GEMINI_API_URL}/{self._model}:generateContent?key={self._api_key}"
        headers = {"Content-Type": "application/json"}

        # Build contents
        contents: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                continue  # Handled via systemInstruction

            parts: list[dict[str, Any]] = []
            if msg.content:
                parts.append({"text": msg.content})

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    parts.append(
                        {
                            "functionCall": {
                                "name": tc.name,
                                "args": tc.arguments,
                            }
                        }
                    )

            if msg.role == "tool":
                # Gemini functionResponse format
                try:
                    resp_dict = json.loads(msg.content or "{}")
                except json.JSONDecodeError:
                    resp_dict = {"output": msg.content}

                parts.append(
                    {
                        "functionResponse": {
                            "name": msg.tool_call_id or "tool_result",
                            "response": {"result": resp_dict},
                        }
                    }
                )

            gemini_role = "user" if msg.role in ("user", "tool") else "model"
            if parts:
                contents.append({"role": gemini_role, "parts": parts})

        payload: dict[str, Any] = {"contents": contents}

        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        tool.to_gemini_tool() for tool in tools
                    ]
                }
            ]

        try:
            async with self._session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 400:
                    text = await resp.text()
                    raise LlmError(f"Gemini Bad Request: {text}")
                if resp.status in (401, 403):
                    raise LlmAuthError("Invalid Gemini API key.")
                if resp.status == 429:
                    raise LlmRateLimitError("Gemini quota exceeded.")
                if resp.status != 200:
                    text = await resp.text()
                    raise LlmError(f"HTTP {resp.status} from Gemini: {text}")

                data = await resp.json()
        except aiohttp.ClientError as err:
            raise LlmError(f"Network error connecting to Gemini: {err}") from err

        candidates = data.get("candidates", [])
        if not candidates:
            return LlmResponse(content="", finish_reason="empty_response")

        candidate = candidates[0]
        content_obj = candidate.get("content", {})
        parts = content_obj.get("parts", [])

        text_pieces: list[str] = []
        tool_calls: list[LlmToolCall] = []

        for idx, part in enumerate(parts):
            if "text" in part:
                text_pieces.append(part["text"])
            if "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(
                    LlmToolCall(
                        call_id=f"gemini_call_{idx}",
                        name=fc.get("name", ""),
                        arguments=fc.get("args", {}),
                    )
                )

        full_text = "".join(text_pieces) if text_pieces else None
        return LlmResponse(
            content=full_text,
            tool_calls=tool_calls,
            finish_reason=candidate.get("finishReason"),
        )


def create_llm_engine(
    provider: str,
    config: dict[str, Any],
    session: aiohttp.ClientSession,
) -> BaseLlmEngine:
    """Factory function to instantiate the proper LLM engine."""
    if provider == PROVIDER_GEMINI_FREE:
        api_key = config.get(CONF_API_KEY, "")
        model = config.get(CONF_MODEL, DEFAULT_GEMINI_MODEL)
        return GeminiEngine(session=session, api_key=api_key, model=model)

    if provider == PROVIDER_OLLAMA_LOCAL:
        base_url = config.get(CONF_BASE_URL, DEFAULT_OLLAMA_URL)
        model = config.get(CONF_MODEL, DEFAULT_OLLAMA_MODEL)
        return OpenAiCompatibleEngine(
            session=session, base_url=base_url, model=model
        )

    # PROVIDER_CUSTOM_OPENAI
    base_url = config.get(CONF_BASE_URL, "https://api.openai.com/v1")
    model = config.get(CONF_MODEL, "gpt-4o-mini")
    api_key = config.get(CONF_API_KEY)
    return OpenAiCompatibleEngine(
        session=session, base_url=base_url, model=model, api_key=api_key
    )
