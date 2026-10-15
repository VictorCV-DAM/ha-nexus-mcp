"""Universal LLM engine adapter for Nexus MCP.

Supports Google Gemini Free Tier, Ollama (Qwen 2.5 Coder), and OpenAI-compatible endpoints.
Uses aiohttp directly to eliminate external dependencies in Home Assistant.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
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
    DEFAULT_GROQ_MODEL,
    DEFAULT_GROQ_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_QWEN_MODEL,
    DEFAULT_QWEN_URL,
    PROVIDER_CUSTOM_OPENAI,
    PROVIDER_GEMINI_FREE,
    PROVIDER_GROQ_FREE,
    PROVIDER_OLLAMA_LOCAL,
    PROVIDER_QWEN_FREE,
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
    thought_signature: str | None = None


@dataclass
class ChatMessage:
    """Standardized chat message."""

    role: str  # "system", "user", "assistant", "tool"
    content: str | None = None
    tool_calls: list[LlmToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # Used when role is "tool" (call ID for OpenAI)
    tool_name: str | None = None  # Function name for Gemini functionResponse
    image_data: str | None = None  # Base64 Data URL for multimodal image analysis


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
        # Auto-normalize Groq models (missing prefix or EU-restricted Llama)
        clean_model = (model or "").strip()
        if "groq.com" in self._base_url:
            if clean_model in ("qwen3.8-27b", "qwen-27b", "qwen3.8", "qwen-3.8-27b"):
                clean_model = "qwen/qwen3.8-27b"
            elif clean_model in ("gpt-oss-120b", "120b", "openai-120b"):
                clean_model = "openai/gpt-oss-120b"
            elif clean_model in ("gpt-oss-20b", "20b", "openai-20b"):
                clean_model = "openai/gpt-oss-20b"
            elif "llama" in clean_model.lower():
                _LOGGER.warning(
                    "Llama model '%s' is not served by Groq in Europe. Auto-redirecting to 'qwen/qwen3.8-27b'.",
                    clean_model,
                )
                clean_model = "qwen/qwen3.8-27b"
        self._model = clean_model
        self._api_key = api_key or "sk-no-key-required"

    def _is_vision_model(self) -> bool:
        """Check if the configured model supports vision/multimodal input."""
        m = self._model.lower()
        if "groq.com" in self._base_url:
            # Groq currently only supports vision on specific models like llama-3.2-*-vision
            return "vision" in m
        vision_indicators = ("vision", "-vl", "gemini", "gpt-4o", "omni", "claude-3")
        return any(ind in m for ind in vision_indicators)

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
            "User-Agent": "HomeAssistant-NexusMCP/1.0",
        }

        # Convert standardized messages to OpenAI format
        api_messages: list[dict[str, Any]] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if msg.role == "tool":
                # OpenAI/Groq strict requirement: role 'tool' MUST have tool_call_id AND
                # must match a tool_call in the preceding assistant message.
                prev_has_tool_call = False
                if msg.tool_call_id and api_messages:
                    for prev_msg in reversed(api_messages):
                        if prev_msg.get("role") == "assistant":
                            prev_calls = prev_msg.get("tool_calls", [])
                            if any(tc.get("id") == msg.tool_call_id for tc in prev_calls):
                                prev_has_tool_call = True
                            break
                        elif prev_msg.get("role") != "tool":
                            break

                if not msg.tool_call_id or not prev_has_tool_call:
                    # Convert orphaned or unlinked tool result to assistant text note to prevent HTTP 400
                    api_messages.append({
                        "role": "assistant",
                        "content": f"[Tool: {msg.tool_name or 'info'}] {msg.content or ''}",
                    })
                    continue

                api_messages.append({
                    "role": "tool",
                    "content": msg.content or "",
                    "tool_call_id": msg.tool_call_id,
                })
                continue

            msg_dict: dict[str, Any] = {"role": msg.role}
            if msg.image_data and msg.role == "user" and self._is_vision_model():
                msg_dict["content"] = [
                    {"type": "text", "text": msg.content or ""},
                    {"type": "image_url", "image_url": {"url": msg.image_data}},
                ]
            else:
                text_content = msg.content or ""
                if msg.image_data and msg.role == "user":
                    text_content = f"[Attached Image] {text_content}".strip()
                msg_dict["content"] = text_content
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
            payload["temperature"] = 0.1

        data = None
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                async with self._session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 401:
                        raise LlmAuthError("Invalid API key or unauthorized access.")
                    if resp.status == 429:
                        error_body = await resp.text()
                        retry_after = resp.headers.get("Retry-After")
                        delay = 2.0 * (attempt + 1)
                        if retry_after and retry_after.replace(".", "", 1).isdigit():
                            delay = max(1.0, min(float(retry_after), 5.0))

                        # If on Groq and hit rate limit, attempt bidirectional fallback between 120b and qwen
                        if "groq.com" in self._base_url:
                            if self._model == "openai/gpt-oss-120b":
                                _LOGGER.warning(
                                    "Groq rate limit on openai/gpt-oss-120b. Auto-falling back to qwen/qwen3.8-27b...",
                                )
                                self._model = "qwen/qwen3.8-27b"
                                payload["model"] = "qwen/qwen3.8-27b"
                                await asyncio.sleep(1.0)
                                continue
                            if self._model == "qwen/qwen3.8-27b":
                                _LOGGER.warning(
                                    "Groq rate limit on qwen/qwen3.8-27b. Auto-falling back to openai/gpt-oss-120b...",
                                )
                                self._model = "openai/gpt-oss-120b"
                                payload["model"] = "openai/gpt-oss-120b"
                                await asyncio.sleep(1.0)
                                continue

                        if attempt < max_retries:
                            _LOGGER.warning(
                                "HTTP 429 rate limit from %s (attempt %d). Retrying in %.1fs...",
                                url,
                                attempt + 1,
                                delay,
                            )
                            await asyncio.sleep(delay)
                            continue

                        try:
                            err_json = json.loads(error_body)
                            msg = err_json.get("error", {}).get("message", error_body)
                        except Exception:
                            msg = error_body
                        raise LlmRateLimitError(f"Rate limit exceeded: {msg}")

                    if resp.status == 400:
                        text = await resp.text()
                        # If Groq or OpenAI rejected with tool_use_failed, malformed JSON, or failed_generation
                        if any(w in text.lower() for w in ("malformed", "tool_use_failed", "failed_generation", "invalid json")):
                            _LOGGER.warning(
                                "Model generated malformed tool call JSON (attempt %d/%d): %s. Retrying with deterministic temperature...",
                                attempt + 1,
                                max_retries + 1,
                                text,
                            )
                            if attempt < max_retries:
                                payload["temperature"] = 0.0
                                await asyncio.sleep(1.0)
                                continue
                        raise LlmError(f"HTTP 400 Bad Request from {url}: {text}")

                    if resp.status != 200:
                        text = await resp.text()
                        raise LlmError(f"HTTP {resp.status} from {url}: {text}")

                    data = await resp.json()
                    break
            except aiohttp.ClientError as err:
                if attempt < max_retries:
                    await asyncio.sleep(1.0)
                    continue
                raise LlmError(f"Network error connecting to {url}: {err}") from err

        if not data:
            raise LlmError(f"No response received from {url}.")

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

        # Automatically upgrade retired or deprecated models to gemini-3.8-flash
        clean_model = model.strip()
        if clean_model.startswith("models/"):
            clean_model = clean_model[len("models/"):]

        if clean_model in ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.0-pro"):
            _LOGGER.info(
                "Upgrading deprecated Gemini model '%s' to '%s'",
                model,
                DEFAULT_GEMINI_MODEL,
            )
            clean_model = DEFAULT_GEMINI_MODEL

        self._model = clean_model

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
            if msg.content and msg.role != "tool":
                parts.append({"text": msg.content})

            if msg.image_data and msg.role == "user":
                img_str = msg.image_data
                mime_type = "image/jpeg"
                if "," in img_str and ";base64" in img_str:
                    header, b64_data = img_str.split(",", 1)
                    mime_type = header.split(";")[0].replace("data:", "")
                else:
                    b64_data = img_str
                parts.append({"inlineData": {"mimeType": mime_type, "data": b64_data}})

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    fc_data: dict[str, Any] = {
                        "name": tc.name,
                        "args": tc.arguments,
                    }
                    if tc.call_id and not tc.call_id.startswith("gemini_call_"):
                        fc_data["id"] = tc.call_id

                    # Gemini 3 requires thoughtSignature on functionCall parts in multi-turn history.
                    sig = tc.thought_signature or "skip_thought_signature_validator"
                    fc_part: dict[str, Any] = {
                        "functionCall": fc_data,
                        "thoughtSignature": sig,
                    }
                    parts.append(fc_part)

            if msg.role == "tool":
                # Gemini functionResponse format
                try:
                    resp_dict = json.loads(msg.content or "{}")
                except json.JSONDecodeError:
                    resp_dict = {"output": msg.content}

                func_name = msg.tool_name or msg.tool_call_id or "tool_result"
                parts.append(
                    {
                        "functionResponse": {
                            "name": func_name,
                            "response": {"result": resp_dict},
                        }
                    }
                )

            gemini_role = "user" if msg.role in ("user", "tool") else "model"
            if parts:
                if contents and contents[-1]["role"] == gemini_role:
                    contents[-1]["parts"].extend(parts)
                else:
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

        max_attempts = 3
        backoff_seconds = 1.5
        data: dict[str, Any] | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                async with self._session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 429:
                        # If the model hit quota limit and it's gemini-3.8-flash or gemini-flash-latest (only 20 req/day),
                        # automatically fallback to high-quota gemini-3.1-flash-lite (500 req/day!)
                        if self._model != "gemini-3.1-flash-lite":
                            _LOGGER.warning(
                                "Gemini model '%s' quota exceeded (HTTP 429). Falling back to 'gemini-3.1-flash-lite' (500 req/day)...",
                                self._model,
                            )
                            self._model = "gemini-3.1-flash-lite"
                            url = f"{GEMINI_API_URL}/{self._model}:generateContent?key={self._api_key}"
                            await asyncio.sleep(1.0)
                            continue

                        if attempt < max_attempts:
                            await asyncio.sleep(backoff_seconds * attempt)
                            continue

                        raise LlmRateLimitError(
                            "Google Gemini free tier daily request limit reached. "
                            "Please wait a few moments or verify your quota in Google AI Studio."
                        )

                    if resp.status == 503:
                        if attempt < max_attempts:
                            _LOGGER.warning(
                                "Gemini API temporarily busy (HTTP 503, attempt %d/%d). Retrying in %.1fs...",
                                attempt,
                                max_attempts,
                                backoff_seconds * attempt,
                            )
                            await asyncio.sleep(backoff_seconds * attempt)
                            continue
                        raise LlmRateLimitError(
                            "Google Gemini servers are temporarily experiencing high demand. Please try again shortly."
                        )

                    if resp.status == 400:
                        text = await resp.text()
                        raise LlmError(f"Gemini Bad Request: {text}")
                    if resp.status in (401, 403):
                        raise LlmAuthError("Invalid or unauthorized Google Gemini API key.")
                    if resp.status != 200:
                        text = await resp.text()
                        raise LlmError(f"HTTP {resp.status} from Gemini: {text}")

                    data = await resp.json()
                    break
            except aiohttp.ClientError as err:
                if attempt < max_attempts:
                    await asyncio.sleep(backoff_seconds * attempt)
                    continue
                raise LlmError(f"Network error connecting to Gemini: {err}") from err

        if data is None:
            raise LlmError("No valid response received from Google Gemini server.")

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
                thought_sig = (
                    part.get("thoughtSignature")
                    or part.get("thought_signature")
                    or fc.get("thoughtSignature")
                    or fc.get("thought_signature")
                )
                call_id = fc.get("id") or f"gemini_call_{idx}"
                tool_calls.append(
                    LlmToolCall(
                        call_id=call_id,
                        name=fc.get("name", ""),
                        arguments=fc.get("args", {}),
                        thought_signature=thought_sig,
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

    if provider == PROVIDER_GROQ_FREE:
        base_url = config.get(CONF_BASE_URL, DEFAULT_GROQ_URL)
        model = config.get(CONF_MODEL, DEFAULT_GROQ_MODEL)
        api_key = config.get(CONF_API_KEY, "")
        return OpenAiCompatibleEngine(
            session=session, base_url=base_url, model=model, api_key=api_key
        )

    if provider == PROVIDER_QWEN_FREE:
        base_url = config.get(CONF_BASE_URL, DEFAULT_QWEN_URL)
        model = config.get(CONF_MODEL, DEFAULT_QWEN_MODEL)
        api_key = config.get(CONF_API_KEY, "")
        return OpenAiCompatibleEngine(
            session=session, base_url=base_url, model=model, api_key=api_key
        )

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
