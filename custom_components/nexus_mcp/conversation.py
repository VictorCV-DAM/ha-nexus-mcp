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
from .llm_engine import ChatMessage, LlmAuthError, LlmRateLimitError, create_llm_engine
from .tools import execute_builtin_tool, get_builtin_tools

_LOGGER = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 25


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nexus MCP conversation entity."""
    async_add_entities([NexusMcpConversationEntity(hass, entry)])


def _is_user_confirmation(history: list[ChatMessage], current_text: str) -> bool:
    """Check if the user's latest utterance is a confirmation to a previous proposal."""
    affirmative_tokens = {
        "si", "sí", "adelante", "confirmo", "confirmado", "confirmar",
        "créala", "creala", "procede", "proceder", "hazlo", "dale",
        "ok", "vale", "de acuerdo", "perfecto", "correcto", "yes",
        "confirm", "proceed", "sure", "yep", "yeah", "claro",
    }
    words = re.findall(r"[\wáéíóúÁÉÍÓÚñÑ]+", current_text.lower())
    if not words:
        return False

    # If the user explicitly says "no" without affirmative words, it's not a confirmation
    if "no" in words and "si" not in words and "sí" not in words:
        return False

    is_affirmative = any(w in affirmative_tokens for w in words)
    if not is_affirmative:
        return False

    # Check if a previous assistant message asked for confirmation or proposed an automation
    confirmation_cues = (
        "confirm", "automatización", "automatizacion", "automation",
        "¿deseas", "deseas que", "quieres que", "¿procedo", "proceda",
        "¿creo", "crear", "procede", "¿te parece", "ha_create_automation",
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
        self._attr_name = f"Nexus MCP Intercom ({model_name})"

        # Conversation history buffer: conversation_id -> list[ChatMessage]
        self._history: dict[str, list[ChatMessage]] = {}

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

    @property
    def supported_features(self) -> ConversationEntityFeature:
        """Return supported features."""
        return ConversationEntityFeature.CONTROL

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return supported languages."""
        return "*"

    async def async_process(
        self, user_input: ConversationInput
    ) -> ConversationResult:
        """Process a conversational utterance and forward to the external server with tool support."""
        conversation_id = user_input.conversation_id or "default"
        text = user_input.text.strip()

        _LOGGER.debug(
            "Nexus MCP Intercom query [%s]: %s",
            conversation_id,
            text,
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

        base_system_prompt = (
            "You are Nexus MCP, an autonomous AI assistant embedded directly inside Home Assistant. "
            "You have direct access to tools to search entities (ha_search_entities), read states (ha_get_entity_state), "
            "control devices (ha_call_service), and create/activate automations (ha_create_automation).\n"
            "Rules for creating automations with ha_create_automation:\n"
            "1. In 'trigger', for time intervals use: [{'platform': 'time_pattern', 'seconds': '/5'}]. Never use 'pattern'.\n"
            "2. In 'action', call services using: [{'service': 'domain.service_name', 'target': {'entity_id': '...'}}]. Never use 'domain' as a separate key.\n"
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
            autonomy_prompt = (
                "AUTONOMOUS MODE: DISABLED (CONFIRMATION REQUIRED BEFORE CREATING AUTOMATIONS).\n"
                "When the user asks to create or modify an automation, you MUST NOT call ha_create_automation yet.\n"
                "Instead, perform the following steps:\n"
                "1. If needed, use ha_search_entities or ha_get_entity_state to find the correct entity IDs and verify devices.\n"
                "2. Explain clearly to the user what you understood from their request.\n"
                "3. Describe the exact automation you plan to create: specify the trigger(s), condition(s), action(s), and entity IDs.\n"
                "4. Ask the user for explicit confirmation before proceeding (for example: '¿Deseas que proceda a crear esta automatización? Responde \"sí\" para confirmar.').\n"
                "5. Wait for their confirmation in the next turn. DO NOT call ha_create_automation until the user confirms."
            )

        system_prompt = f"{base_system_prompt}\n{autonomy_prompt}\nRespond clearly, concisely, and helpfully in the user's language."

        assistant_reply = "OK."

        try:
            # Multi-turn tool execution loop (up to 4 turns)
            for _ in range(4):
                response = await self._engine.generate_response(
                    messages=history,
                    tools=self._tools,
                    system_prompt=system_prompt,
                )

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
                            tool_result = {
                                "status": "confirmation_required",
                                "error": (
                                    "Autonomous Mode is disabled. You must NOT create the automation yet. "
                                    "Tell the user what you understood, describe the exact automation (trigger, condition, action, entities), "
                                    "and explicitly ask for their confirmation (e.g. '¿Deseas que proceda a crear esta automatización? Responde \"sí\" para confirmar.'). "
                                    "DO NOT call ha_create_automation again until the user confirms in the next turn."
                                ),
                            }
                        else:
                            tool_result = await execute_builtin_tool(
                                self.hass, tc.name, tc.arguments
                            )

                        history.append(
                            ChatMessage(
                                role="tool",
                                content=json.dumps(tool_result, ensure_ascii=False),
                                tool_call_id=tc.call_id,
                                tool_name=tc.name,
                            )
                        )
                    # Loop continues: send tool results back to LLM for final explanation
                    continue

                # When no tool calls are returned, we have the final assistant answer
                assistant_reply = response.content or "Acción completada."
                history.append(ChatMessage(role="assistant", content=assistant_reply))
                break

        except LlmRateLimitError as err:
            _LOGGER.warning("Nexus MCP rate limit/high demand: %s", err)
            assistant_reply = (
                f"Límite de peticiones alcanzado ({err}). "
                "Los servidores gratuitos tienen un límite temporal de tokens por minuto (TPM). "
                "Por favor, espera unos segundos antes de volver a intentarlo. "
                "Consejo: En Groq puedes usar 'llama-3.3-70b-versatile' o en Google 'gemini-3.1-flash-lite' para límites mucho más amplios."
            )
        except LlmAuthError as err:
            _LOGGER.error("Nexus MCP authentication error: %s", err)
            assistant_reply = (
                f"Error de autenticación ({err}). "
                "Verifica tu clave de API en Ajustes > Dispositivos y Servicios."
            )
        except Exception as err:
            _LOGGER.error("Nexus MCP Intercom error communicating with server: %s", err)
            assistant_reply = (
                f"Error al comunicar con el servidor de IA ({err}). "
                "Verifica la conexión y configuración en Ajustes > Dispositivos y Servicios."
            )

        # Build Home Assistant intent response
        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(assistant_reply)

        return ConversationResult(
            response=intent_response,
            conversation_id=conversation_id,
        )
