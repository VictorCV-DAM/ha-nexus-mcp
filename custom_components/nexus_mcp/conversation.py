"""Conversation entity for Nexus MCP (Ultra-lightweight intercom for Home Assistant)."""
from __future__ import annotations

import json
import logging
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

from .const import CONF_LLM_PROVIDER, CONF_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL, DOMAIN
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


class NexusMcpConversationEntity(ConversationEntity):
    """Nexus MCP Conversation Entity: Ultra-lightweight intercom client with native tools."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the conversation entity."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_conversation"
        self._attr_name = f"Nexus MCP Intercom ({entry.data.get(CONF_LLM_PROVIDER, 'agent')})"

        # Conversation history buffer: conversation_id -> list[ChatMessage]
        self._history: dict[str, list[ChatMessage]] = {}

        # Built-in Home Assistant tools
        self._tools = get_builtin_tools()

        # Resolve MCP Server URL: configured or auto-discovered
        mcp_url = entry.data.get(CONF_MCP_SERVER_URL)
        if not mcp_url or mcp_url == DEFAULT_MCP_SERVER_URL:
            discovered = async_autodiscover_ha_mcp_url(hass)
            if discovered:
                mcp_url = discovered
        self._mcp_url = mcp_url

        # Initialize lightweight engine using shared HA aiohttp session
        session = async_get_clientsession(hass)
        self._engine = create_llm_engine(
            provider=entry.data.get(CONF_LLM_PROVIDER, ""),
            config=entry.data,
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

        system_prompt = (
            "You are Nexus MCP, an autonomous AI assistant embedded directly inside Home Assistant. "
            "You have direct access to tools to search entities (ha_search_entities), read states (ha_get_entity_state), "
            "control devices (ha_call_service), and create/activate automations (ha_create_automation).\n"
            "Rules for creating automations with ha_create_automation:\n"
            "1. In 'trigger', for time intervals use: [{'platform': 'time_pattern', 'seconds': '/5'}]. Never use 'pattern'.\n"
            "2. In 'action', call services using: [{'service': 'domain.service_name', 'target': {'entity_id': '...'}}]. Never use 'domain' as a separate key.\n"
            "3. When the user asks you to create an automation or control a device, do not ask them to do it manually: "
            "use your tools to search for the entity if needed and create the automation directly! "
            "Respond clearly, concisely, and helpfully in the user's language."
        )

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
