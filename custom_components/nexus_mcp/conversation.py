"""Conversation entity for Nexus MCP (Ultra-lightweight intercom for Home Assistant)."""
from __future__ import annotations

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

from .const import CONF_LLM_PROVIDER, DOMAIN
from .llm_engine import ChatMessage, LlmAuthError, LlmRateLimitError, create_llm_engine

_LOGGER = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nexus MCP conversation entity."""
    async_add_entities([NexusMcpConversationEntity(hass, entry)])


class NexusMcpConversationEntity(ConversationEntity):
    """Nexus MCP Conversation Entity: Ultra-lightweight intercom client."""

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
        """Process a conversational utterance and forward to the external server."""
        conversation_id = user_input.conversation_id or "default"
        text = user_input.text.strip()

        _LOGGER.debug(
            "Nexus MCP Intercom forwarding query for session %s: %s",
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
            "You are Nexus MCP, an expert AI assistant connected to Home Assistant. "
            "Help the user monitor devices, create automations, and diagnose issues. "
            "Respond in the user's language clearly and concisely."
        )

        try:
            # Ultra-lightweight asynchronous forward to the external server
            response = await self._engine.generate_response(
                messages=history,
                system_prompt=system_prompt,
            )

            assistant_reply = response.content or "OK."
            history.append(ChatMessage(role="assistant", content=assistant_reply))

        except LlmRateLimitError as err:
            _LOGGER.warning("Nexus MCP rate limit/high demand: %s", err)
            assistant_reply = str(err)
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
