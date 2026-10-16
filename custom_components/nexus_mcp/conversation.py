"""Conversation entity for Nexus MCP (Ultra-lightweight intercom for Home Assistant)."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from homeassistant.components import conversation
from homeassistant.components.conversation import (
    ConversationEntity,
    ConversationEntityFeature,
    ConversationInput,
    ConversationResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import intent
try:
    from homeassistant.helpers.storage import Store
except (ImportError, AttributeError):
    Store = None

try:
    from homeassistant.helpers.dispatcher import async_dispatcher_send
except (ImportError, AttributeError):
    async_dispatcher_send = None

from .const import (
    CONF_AUTONOMOUS_MODE,
    CONF_LLM_PROVIDER,
    CONF_MCP_SERVER_URL,
    CONF_MODEL,
    DEFAULT_AUTONOMOUS_MODE,
    DEFAULT_MCP_SERVER_URL,
    DOMAIN,
)
from .discovery import async_autodiscover_ha_mcp_url
from .llm_engine import ChatMessage, GeminiEngine, LlmAuthError, LlmRateLimitError, create_llm_engine
from .tools import execute_builtin_tool, get_builtin_tools

_LOGGER = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 25
MAX_STORED_CONVERSATIONS = 20
STORAGE_KEY = f"{DOMAIN}_history"
STORAGE_VERSION = 1

RESET_COMMANDS = {
    "nueva conversación", "nueva conversacion", "nuevo chat", "reiniciar",
    "reinicia", "reiniciar conversación", "reiniciar conversacion", "olvida todo",
    "olvida lo anterior", "borrar historial", "reset", "new conversation",
    "clear history", "start over",
}


def is_transient_error_message(content: str | None) -> bool:
    """Check if message content is a transient system error that should not be saved or sent back to LLM."""
    if not content:
        return False
    c_lower = str(content).lower().strip()
    return (
        c_lower.startswith("error al comunicar")
        or c_lower.startswith("error communicating")
        or c_lower.startswith("límite de peticiones")
        or c_lower.startswith("rate limit reached")
        or c_lower.startswith("request too large")
        or "http 413" in c_lower
        or "http 429" in c_lower
    )


def prune_history_to_token_budget(
    messages: list[ChatMessage], max_tokens: int = 3500
) -> list[ChatMessage]:
    """Ensure conversation history fits safely within the model's input token limits."""
    if not messages:
        return []
    # Strip any transient error messages from history
    cleaned = [m for m in messages if not is_transient_error_message(m.content)]
    if not cleaned:
        cleaned = list(messages)
    # Always keep the latest message
    pruned = [cleaned[-1]]
    current_tokens = max(1, len(cleaned[-1].content or "") // 4) + 20
    for msg in reversed(cleaned[:-1]):
        msg_tokens = max(1, len(msg.content or "") // 4) + 20
        if current_tokens + msg_tokens > max_tokens:
            break
        pruned.insert(0, msg)
        current_tokens += msg_tokens
    return pruned


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nexus MCP conversation entity."""
    entity = NexusMcpConversationEntity(hass, entry)
    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    hass.data[DOMAIN][entry.entry_id]["conversation_entity"] = entity
    async_add_entities([entity])


def _is_user_confirmation(history: list[ChatMessage], current_text: str) -> bool:
    """Check if the user's latest utterance is a confirmation to a previous proposal."""
    affirmative_tokens = {
        "si", "sí", "adelante", "confirmo", "confirmado", "confirmar",
        "créala", "creala", "procede", "proceder", "hazlo", "dale",
        "ok", "vale", "de acuerdo", "perfecto", "correcto", "yes",
        "confirm", "confirmed", "proceed", "sure", "yep", "yeah", "claro",
        "do it", "create it", "go ahead", "approved", "looks good",
        "ja", "bekræft", "fortsæt", "oui", "d'accord", "genau",
    }
    cleaned_lower = current_text.lower().strip()
    words = re.findall(r"[\wáéíóúÁÉÍÓÚñÑ]+", cleaned_lower)
    if not words:
        return False

    # If the user explicitly says "no" without affirmative words, it's not a confirmation
    if "no" in words and "si" not in words and "sí" not in words and "yes" not in words:
        return False

    is_affirmative = any(w in affirmative_tokens for w in words) or cleaned_lower in affirmative_tokens
    if not is_affirmative:
        return False

    # Check if a previous assistant message asked for confirmation or proposed an automation
    confirmation_cues = (
        "confirm", "automatización", "automatizacion", "automation",
        "¿deseas", "deseas que", "quieres que", "¿procedo", "proceda",
        "¿creo", "crear", "procede", "¿te parece", "ha_create_automation",
        "would you like", "should i", "do you want me to", "proceed",
    )
    for msg in reversed(history):
        if msg.role == "assistant" and msg.content:
            content_lower = msg.content.lower()
            if any(cue in content_lower for cue in confirmation_cues):
                return True
            break
    return False


class NexusMcpConversationEntity(ConversationEntity):
    """Nexus MCP Conversation Entity: Ultra-lightweight intercom client with native tools."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the conversation entity."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_conversation"
        merged_config = {**entry.data, **entry.options}
        model_name = merged_config.get(CONF_MODEL) or merged_config.get(CONF_LLM_PROVIDER, "agent")
        self._model_name = model_name
        self._provider = merged_config.get(CONF_LLM_PROVIDER, "")
        self._attr_name = f"Nexus MCP Intercom ({model_name})"

        # Daily telemetry and rate limit tracking
        import datetime
        today_str = datetime.date.today().isoformat()
        self._telemetry: dict[str, Any] = {
            "date": today_str,
            "tokens_today": 0,
            "requests_today": 0,
            "prompt_tokens_today": 0,
            "completion_tokens_today": 0,
            "last_prompt_tokens": 0,
            "last_completion_tokens": 0,
            "last_total_tokens": 0,
            "rate_limit_reset_seconds": 0.0,
            "rate_limit_reset_at": None,
            "rate_limit_status": "ok",
            "model": self._model_name,
            "provider": self._provider,
            "remaining_tokens": None,
            "limit_tokens": None,
            "remaining_requests": None,
            "limit_requests": None,
            "last_updated": None,
        }

        # Conversation history buffer: conversation_id -> list[ChatMessage]
        self._history: dict[str, list[ChatMessage]] = {}
        self._history_loaded = False
        self._last_conversation_id: str | None = None

        if Store is not None:
            self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
        else:
            self._store = None

        # Built-in Home Assistant tools
        self._tools = get_builtin_tools()

        # Resolve MCP Server URL: configured or auto-discovered
        mcp_url = merged_config.get(CONF_MCP_SERVER_URL)
        if not mcp_url or mcp_url == DEFAULT_MCP_SERVER_URL:
            discovered = async_autodiscover_ha_mcp_url(hass)
            if discovered:
                mcp_url = discovered
        self._mcp_url = mcp_url

        # Initialize lightweight engine using shared HA aiohttp session
        session = async_get_clientsession(hass)
        self._engine = create_llm_engine(
            provider=merged_config.get(CONF_LLM_PROVIDER, ""),
            config=merged_config,
            session=session,
        )

        hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
        hass.data[DOMAIN][entry.entry_id]["conversation_entity"] = self

    @property
    def device_info(self) -> dict[str, Any]:
        """Link conversation entity to device in Home Assistant device registry."""
        return {
            "identifiers": {(DOMAIN, self.entry.entry_id)},
            "name": f"Nexus MCP ({self._model_name})",
            "manufacturer": "Nexus MCP",
            "model": self._model_name,
            "sw_version": "1.4.0",
        }

    @property
    def telemetry(self) -> dict[str, Any]:
        """Return live telemetry metrics."""
        return self._telemetry

    def record_usage(self, usage: dict[str, Any], rate_limits: dict[str, Any] | None = None) -> None:
        """Record token usage and rate limits from engine response."""
        import datetime
        today_str = datetime.date.today().isoformat()
        if self._telemetry.get("date") != today_str:
            self._telemetry["date"] = today_str
            self._telemetry["tokens_today"] = 0
            self._telemetry["requests_today"] = 0
            self._telemetry["prompt_tokens_today"] = 0
            self._telemetry["completion_tokens_today"] = 0

        self._telemetry["requests_today"] = int(self._telemetry.get("requests_today", 0)) + 1
        p_tokens = int(usage.get("prompt_tokens") or 0)
        c_tokens = int(usage.get("completion_tokens") or 0)
        t_tokens = int(usage.get("total_tokens") or (p_tokens + c_tokens))

        self._telemetry["tokens_today"] += t_tokens
        self._telemetry["prompt_tokens_today"] += p_tokens
        self._telemetry["completion_tokens_today"] += c_tokens
        self._telemetry["last_prompt_tokens"] = p_tokens
        self._telemetry["last_completion_tokens"] = c_tokens
        self._telemetry["last_total_tokens"] = t_tokens
        self._telemetry["rate_limit_status"] = "ok"
        self._telemetry["rate_limit_reset_seconds"] = 0.0
        self._telemetry["rate_limit_reset_at"] = None
        self._telemetry["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if rate_limits:
            if "x-ratelimit-remaining-tokens" in rate_limits:
                try:
                    self._telemetry["remaining_tokens"] = int(rate_limits["x-ratelimit-remaining-tokens"])
                except (ValueError, TypeError):
                    self._telemetry["remaining_tokens"] = rate_limits["x-ratelimit-remaining-tokens"]
            if "x-ratelimit-limit-tokens" in rate_limits:
                try:
                    self._telemetry["limit_tokens"] = int(rate_limits["x-ratelimit-limit-tokens"])
                except (ValueError, TypeError):
                    self._telemetry["limit_tokens"] = rate_limits["x-ratelimit-limit-tokens"]
            if "x-ratelimit-remaining-requests" in rate_limits:
                try:
                    self._telemetry["remaining_requests"] = int(rate_limits["x-ratelimit-remaining-requests"])
                except (ValueError, TypeError):
                    self._telemetry["remaining_requests"] = rate_limits["x-ratelimit-remaining-requests"]
            if "x-ratelimit-limit-requests" in rate_limits:
                try:
                    self._telemetry["limit_requests"] = int(rate_limits["x-ratelimit-limit-requests"])
                except (ValueError, TypeError):
                    self._telemetry["limit_requests"] = rate_limits["x-ratelimit-limit-requests"]

        if async_dispatcher_send:
            try:
                async_dispatcher_send(
                    self.hass, f"{DOMAIN}_{self.entry.entry_id}_telemetry_updated"
                )
            except Exception:
                pass

    def record_rate_limit(self, reset_seconds: float = 5.0) -> None:
        """Record rate limit hit with countdown unblock timestamp."""
        import datetime
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        reset_at = now_utc + datetime.timedelta(seconds=reset_seconds)
        self._telemetry["rate_limit_status"] = "throttled"
        self._telemetry["rate_limit_reset_seconds"] = round(reset_seconds, 2)
        self._telemetry["rate_limit_reset_at"] = reset_at.isoformat()
        self._telemetry["last_updated"] = now_utc.isoformat()

        if async_dispatcher_send:
            try:
                async_dispatcher_send(
                    self.hass, f"{DOMAIN}_{self.entry.entry_id}_telemetry_updated"
                )
            except Exception:
                pass

    async def async_added_to_hass(self) -> None:
        """Load persistent conversation history from storage when entity is added."""
        if hasattr(super(), "async_added_to_hass"):
            await super().async_added_to_hass()
        await self._async_load_history()

    async def _async_load_history(self) -> None:
        """Load persistent conversation histories from Home Assistant storage."""
        if self._history_loaded:
            return
        if self._store is not None:
            try:
                data = await self._store.async_load()
                if data and isinstance(data, dict):
                    raw_history = data.get("history", {})
                    self._last_conversation_id = data.get("last_conversation_id")
                    stored_telemetry = data.get("telemetry")
                    if isinstance(stored_telemetry, dict):
                        import datetime
                        today_str = datetime.date.today().isoformat()
                        if stored_telemetry.get("date") == today_str:
                            self._telemetry.update(stored_telemetry)
                        else:
                            self._telemetry["date"] = today_str
                            self._telemetry["tokens_today"] = 0
                            self._telemetry["requests_today"] = 0
                            self._telemetry["prompt_tokens_today"] = 0
                            self._telemetry["completion_tokens_today"] = 0
                            self._telemetry["last_total_tokens"] = stored_telemetry.get("last_total_tokens", 0)

                    for conv_id, msgs in raw_history.items():
                        if isinstance(msgs, list):
                            chat_msgs = []
                            for m in msgs:
                                if isinstance(m, dict) and "role" in m and "content" in m:
                                    if m["role"] in ("user", "assistant"):
                                        # Skip transient server communication errors from polluting long-term history
                                        if not is_transient_error_message(m.get("content")):
                                            chat_msgs.append(
                                                ChatMessage(role=m["role"], content=m["content"])
                                            )
                            if chat_msgs:
                                self._history[conv_id] = chat_msgs[-MAX_HISTORY_MESSAGES:]
                    _LOGGER.debug(
                        "Nexus MCP loaded %d persistent conversations from storage (last: %s)",
                        len(self._history),
                        self._last_conversation_id,
                    )
            except Exception as err:
                _LOGGER.warning("Could not load persistent conversation history: %s", err)
        self._history_loaded = True
        if async_dispatcher_send:
            try:
                async_dispatcher_send(
                    self.hass, f"{DOMAIN}_{self.entry.entry_id}_history_updated"
                )
                async_dispatcher_send(
                    self.hass, f"{DOMAIN}_{self.entry.entry_id}_telemetry_updated"
                )
            except Exception:
                pass

    async def _async_save_history(self) -> None:
        """Save persistent conversation histories to Home Assistant storage."""
        if self._store is None:
            if async_dispatcher_send:
                try:
                    async_dispatcher_send(
                        self.hass, f"{DOMAIN}_{self.entry.entry_id}_history_updated"
                    )
                    async_dispatcher_send(
                        self.hass, f"{DOMAIN}_{self.entry.entry_id}_telemetry_updated"
                    )
                except Exception:
                    pass
            return
        try:
            # Prune older conversations to keep storage light (max MAX_STORED_CONVERSATIONS)
            if len(self._history) > MAX_STORED_CONVERSATIONS:
                keys_to_remove = list(self._history.keys())[:-MAX_STORED_CONVERSATIONS]
                for k in keys_to_remove:
                    if k != self._last_conversation_id:
                        self._history.pop(k, None)

            serializable = {
                "last_conversation_id": self._last_conversation_id,
                "history": {
                    conv_id: [
                        {"role": msg.role, "content": msg.content}
                        for msg in msgs[-MAX_HISTORY_MESSAGES:]
                        if msg.role in ("user", "assistant") and msg.content and not is_transient_error_message(msg.content)
                    ]
                    for conv_id, msgs in self._history.items()
                },
                "telemetry": self._telemetry,
            }
            await self._store.async_save(serializable)
        except Exception as err:
            _LOGGER.warning("Could not persist conversation history: %s", err)
        finally:
            if async_dispatcher_send:
                try:
                    async_dispatcher_send(
                        self.hass, f"{DOMAIN}_{self.entry.entry_id}_history_updated"
                    )
                    async_dispatcher_send(
                        self.hass, f"{DOMAIN}_{self.entry.entry_id}_telemetry_updated"
                    )
                except Exception:
                    pass

    @property
    def supported_features(self) -> ConversationEntityFeature:
        """Return supported features."""
        return ConversationEntityFeature.CONTROL

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return supported languages."""
        return "*"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes for frontend discovery."""
        is_vision = False
        if hasattr(self._engine, "_is_vision_model"):
            is_vision = bool(self._engine._is_vision_model())
        elif isinstance(self._engine, GeminiEngine):
            is_vision = True

        return {
            "has_vision": is_vision,
            "provider": self.entry.options.get(
                CONF_LLM_PROVIDER, self.entry.data.get(CONF_LLM_PROVIDER, "")
            ),
            "model": self.entry.options.get(
                CONF_MODEL, self.entry.data.get(CONF_MODEL, "")
            ),
        }

    async def async_chat_process(
        self,
        text: str,
        image_data: str | None = None,
        conversation_id: str = "default",
    ) -> str:
        """Process chat message with optional multimodal image data."""
        if not self._history_loaded:
            await self._async_load_history()

        history = self._history.setdefault(conversation_id, [])
        history.append(ChatMessage(role="user", content=text, image_data=image_data))
        if len(history) > MAX_HISTORY_MESSAGES:
            history = history[-MAX_HISTORY_MESSAGES:]
            self._history[conversation_id] = history

        system_prompt = (
            "You are Nexus MCP, an autonomous AI assistant embedded directly inside Home Assistant. "
            "You can analyze images, inspect entities, and assist the user in their smart home.\n"
            "Whenever you provide YAML configurations, Lovelace card configs, scripts, automations, templates, or code, you MUST always enclose them in Markdown code blocks with the language tag (e.g. ```yaml ... ```, ```json ... ```, or ```python ... ```). Never output bare code or bare YAML without code blocks."
        )

        try:
            resp = await self._engine.generate_response(
                messages=prune_history_to_token_budget(history, max_tokens=3500),
                tools=self._tools,
                system_prompt=system_prompt,
            )
            if hasattr(resp, "usage") and resp.usage:
                self.record_usage(resp.usage, getattr(resp, "rate_limits", None))
            reply = resp.content or "No response from AI."
        except LlmRateLimitError as err:
            reset_sec = getattr(err, "reset_seconds", 5.0) or 5.0
            self.record_rate_limit(reset_sec)
            raise err
        except Exception as err:
            err_str = str(err)
            if image_data and any(w in err_str.lower() for w in ("image", "vision", "multimodal", "support", "400")):
                is_spanish = any(
                    w in text.lower()
                    for w in ("hola", "¿", "qué", "que", "cómo", "como", "cuál", "enciende", "apaga", "luz", "imagen", "foto")
                )
                reply = (
                    "El modelo actual no admite análisis de imágenes. "
                    "Por favor, selecciona un modelo con visión como Google Gemini en el selector superior."
                    if is_spanish
                    else (
                        "The current model does not support image analysis. "
                        "Please select a vision-capable model like Google Gemini in the model selector above."
                    )
                )
            else:
                raise err

        history.append(ChatMessage(role="assistant", content=reply))
        self._last_conversation_id = conversation_id
        await self._async_save_history()
        return reply

    async def async_process(
        self, user_input: ConversationInput
    ) -> ConversationResult:
        """Process a conversational utterance and forward to the external server with tool support."""
        if not self._history_loaded:
            await self._async_load_history()

        conversation_id = user_input.conversation_id or "default"
        text = user_input.text.strip()

        _LOGGER.debug(
            "Nexus MCP Intercom query [%s]: %s",
            conversation_id,
            text,
        )

        # Check for explicit conversation reset commands
        if text.lower().strip() in RESET_COMMANDS:
            self._history.pop(conversation_id, None)
            if self._last_conversation_id:
                self._history.pop(self._last_conversation_id, None)
                self._last_conversation_id = None
            await self._async_save_history()
            intent_response = intent.IntentResponse(language=user_input.language)
            reply = (
                "Conversación reiniciada. ¿En qué puedo ayudarte?"
                if user_input.language.startswith("es")
                else "Conversation reset. How can I help you?"
            )
            intent_response.async_set_speech(reply)
            return ConversationResult(
                response=intent_response,
                conversation_id=conversation_id,
            )

        # Automatic continuity: If starting a new session (unknown conversation_id),
        # inherit recent context from the previous conversation so the user can
        # seamlessly resume where they left off!
        if conversation_id not in self._history:
            if self._last_conversation_id and self._last_conversation_id in self._history:
                prev_history = self._history[self._last_conversation_id]
                if prev_history:
                    # Seed with up to last 4 messages from previous conversation pruned to 2000 tokens
                    seeded = prune_history_to_token_budget(prev_history, max_tokens=2000)[-4:]
                    self._history[conversation_id] = list(seeded)
                    _LOGGER.debug(
                        "Nexus MCP resumed context from previous conversation [%s] (%d messages) into [%s]",
                        self._last_conversation_id,
                        len(self._history[conversation_id]),
                        conversation_id,
                    )

        history = self._history.setdefault(conversation_id, [])
        history.append(ChatMessage(role="user", content=text))

        # Trim history to keep it lightweight
        if len(history) > MAX_HISTORY_MESSAGES:
            history = history[-MAX_HISTORY_MESSAGES:]
            self._history[conversation_id] = history

        # Check dynamic configuration for autonomous mode
        # entry.options takes precedence over entry.data (updated live when user saves options flow)
        autonomous_mode = bool(
            self.entry.options.get(
                CONF_AUTONOMOUS_MODE,
                self.entry.data.get(CONF_AUTONOMOUS_MODE, DEFAULT_AUTONOMOUS_MODE),
            )
        )
        user_confirmed = _is_user_confirmation(history, text)

        user_lang = getattr(user_input, "language", "") or "en"
        is_spanish = user_lang.lower().startswith("es") or any(
            w in text.lower() for w in ("hola", "¿", "qué", "que", "cómo", "como", "cuál", "enciende", "apaga", "luz", "crea")
        )

        base_system_prompt = (
            "You are Nexus MCP, an autonomous AI assistant embedded directly inside Home Assistant. "
            "You have direct access to tools to search entities (ha_search_entities), read states (ha_get_entity_state), "
            "control devices (ha_call_service), and create/activate automations (ha_create_automation).\n"
            "Rules for creating automations with ha_create_automation:\n"
            "1. In 'trigger', for time intervals use: [{'platform': 'time_pattern', 'seconds': '/5'}]. Never use 'pattern'.\n"
            "2. In 'action', call services using: [{'service': 'domain.service_name', 'target': {'entity_id': '...'}}]. Never use 'domain' as a separate key.\n"
            "3. Tool argument formatting: You must provide strictly valid JSON in all tool arguments. Never include unescaped characters, backticks, conversational filler, or malformed tags inside tool calls.\n"
            "4. Code & YAML formatting: Whenever you provide YAML configurations, Lovelace card configs, scripts, automations, templates, or code, you MUST always enclose them in Markdown code blocks with the language tag (e.g. ```yaml ... ```, ```json ... ```, or ```python ... ```). Never output bare code or bare YAML without code blocks.\n"
        )

        if autonomous_mode:
            autonomy_prompt = (
                "AUTONOMOUS MODE: ENABLED.\n"
                "You have full permission to execute actions and create automations directly without asking for confirmation. "
                "When the user asks you to create an automation or control a device, do not ask them for confirmation: "
                "use your tools to search entities if needed and create the automation or execute the service directly!"
            )
        elif user_confirmed:
            autonomy_prompt = (
                "AUTONOMOUS MODE: DISABLED, BUT USER HAS CONFIRMED.\n"
                "The user has explicitly confirmed the creation of the proposed automation. "
                "You MUST now proceed to create the automation using the ha_create_automation tool directly. "
                "Once created, inform the user that it has been successfully created and activated."
            )
        else:
            confirm_example = (
                "¿Deseas que proceda a crear esta automatización? Responde 'sí' para confirmar."
                if is_spanish
                else "Would you like me to proceed with creating this automation? Reply 'yes' to confirm (in user's language)."
            )
            autonomy_prompt = (
                "AUTONOMOUS MODE: DISABLED (CONFIRMATION REQUIRED BEFORE CREATING AUTOMATIONS).\n"
                "When the user asks to create or modify an automation, you MUST NOT call ha_create_automation yet.\n"
                "Instead, perform the following steps:\n"
                "1. If needed, use ha_search_entities or ha_get_entity_state to find the correct entity IDs and verify devices.\n"
                "2. Explain clearly to the user what you understood from their request.\n"
                "3. Describe the exact automation you plan to create: specify the trigger(s), condition(s), action(s), and entity IDs.\n"
                f"4. Ask the user for explicit confirmation before proceeding (for example: '{confirm_example}').\n"
                "5. Wait for their confirmation in the next turn. DO NOT call ha_create_automation until the user confirms."
            )

        lang_prompt = (
            "LANGUAGE DIRECTIVE:\n"
            f"Always detect and formulate ALL your responses, explanations, and questions strictly in the language used by the user in their query "
            f"(user query language / locale: '{user_lang}'). If the user writes in Danish, reply in Danish; if in Spanish, reply in Spanish; "
            f"if in English, reply in English; if in French/German, reply in French/German. Never reply in an unrelated language."
        )

        system_prompt = f"{base_system_prompt}\n{autonomy_prompt}\n{lang_prompt}"

        assistant_reply = "OK."

        try:
            # Multi-turn tool execution loop (up to 4 turns)
            for _ in range(4):
                response = await self._engine.generate_response(
                    messages=prune_history_to_token_budget(history, max_tokens=2200),
                    tools=self._tools,
                    system_prompt=system_prompt,
                )
                if hasattr(response, "usage") and response.usage:
                    self.record_usage(response.usage, getattr(response, "rate_limits", None))

                if response.tool_calls:
                    # Record model's tool calls in history
                    history.append(
                        ChatMessage(
                            role="assistant",
                            content=response.content,
                            tool_calls=response.tool_calls,
                        )
                    )

                    # Execute each requested tool
                    for tc in response.tool_calls:
                        if (
                            tc.name == "ha_create_automation"
                            and not autonomous_mode
                            and not user_confirmed
                        ):
                            _LOGGER.info(
                                "Intercepted ha_create_automation: Autonomous Mode is OFF and user has not confirmed yet."
                            )
                            intercept_err = (
                                "El modo autónomo está desactivado. No debes crear la automatización todavía. "
                                "Explica al usuario lo que has entendido, describe la automatización exacta (disparador, condición, acción, entidades) "
                                "y pide explícitamente su confirmación (por ejemplo: '¿Deseas que proceda a crear esta automatización? Responde \"sí\" para confirmar.'). "
                                "NO vuelvas a llamar a ha_create_automation hasta que el usuario confirme en el siguiente turno."
                                if is_spanish
                                else (
                                    "Autonomous Mode is disabled. You must NOT create the automation yet. "
                                    "Tell the user what you understood, describe the exact automation (trigger, condition, action, entities), "
                                    "and explicitly ask for their confirmation (e.g. 'Would you like me to proceed with creating this automation? Reply \"yes\" to confirm.'). "
                                    "DO NOT call ha_create_automation again until the user confirms in the next turn."
                                )
                            )
                            tool_result = {
                                "status": "confirmation_required",
                                "error": intercept_err,
                            }
                        else:
                            tool_result = await execute_builtin_tool(
                                self.hass, tc.name, tc.arguments
                            )

                        history.append(
                            ChatMessage(
                                role="tool",
                                content=json.dumps(tool_result, ensure_ascii=False, default=str),
                                tool_call_id=tc.call_id,
                                tool_name=tc.name,
                            )
                        )
                    # Loop continues: send tool results back to LLM for final explanation
                    continue

                # When no tool calls are returned, we have the final assistant answer
                assistant_reply = response.content or ("Acción completada." if is_spanish else "Action completed.")
                history.append(ChatMessage(role="assistant", content=assistant_reply))
                break

        except LlmRateLimitError as err:
            _LOGGER.warning("Nexus MCP rate limit/high demand: %s", err)
            reset_sec = getattr(err, "reset_seconds", 5.0) or 5.0
            self.record_rate_limit(reset_sec)
            m_name = (self._model_name or "").lower()
            if "120b" in m_name:
                tip = (
                    "Consejo: Para comandos con muchas acciones encadenadas en ráfaga sin límite de tokens por minuto, puedes cambiar a Google Gemini ('gemini-3.1-flash-lite'), que ofrece 1.000.000 TPM gratuitos."
                    if is_spanish
                    else "Tip: For long chained multi-action commands without TPM constraints, switch to Google Gemini ('gemini-3.1-flash-lite') with 1,000,000 free TPM."
                )
            else:
                tip = (
                    "Consejo: En Groq puedes usar 'openai/gpt-oss-120b' o en Google 'gemini-3.1-flash-lite' para límites mucho más amplios."
                    if is_spanish
                    else "Tip: On Groq you can use 'openai/gpt-oss-120b' or on Google 'gemini-3.1-flash-lite' for generous limits."
                )
            assistant_reply = (
                f"Límite de peticiones alcanzado ({err}). "
                f"Espera aproximadamente {round(reset_sec, 1)}s para la renovación de tokens por minuto (TPM). "
                f"{tip}"
                if is_spanish
                else (
                    f"Rate limit reached ({err}). "
                    f"Please wait approximately {round(reset_sec, 1)}s for tokens-per-minute (TPM) renewal. "
                    f"{tip}"
                )
            )
        except LlmAuthError as err:
            _LOGGER.error("Nexus MCP authentication error: %s", err)
            assistant_reply = (
                f"Error de autenticación ({err}). "
                "Verifica tu clave de API en Ajustes > Dispositivos y Servicios."
                if is_spanish
                else (
                    f"Authentication error ({err}). "
                    "Please verify your API key in Settings > Devices & Services."
                )
            )
        except Exception as err:
            _LOGGER.error("Nexus MCP Intercom error communicating with server: %s", err)
            assistant_reply = (
                f"Error al comunicar con el servidor de IA ({err}). "
                "Verifica la conexión y configuración en Ajustes > Dispositivos y Servicios."
                if is_spanish
                else (
                    f"Error communicating with AI server ({err}). "
                    "Please verify your connection and settings in Settings > Devices & Services."
                )
            )

        # Only store assistant reply if not a transient error message to prevent recursion/history bloat
        if not is_transient_error_message(assistant_reply):
            if not history or history[-1].role != "assistant":
                history.append(ChatMessage(role="assistant", content=assistant_reply))
        else:
            # If an error occurred, pop the failed user message so the next attempt starts clean
            if history and history[-1].role == "user":
                history.pop()

        self._last_conversation_id = conversation_id
        await self._async_save_history()

        # Build Home Assistant intent response
        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(assistant_reply)

        return ConversationResult(
            response=intent_response,
            conversation_id=conversation_id,
        )
