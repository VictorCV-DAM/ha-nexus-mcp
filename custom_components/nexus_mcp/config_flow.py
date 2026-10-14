"""Config flow for Nexus MCP integration."""
from __future__ import annotations

import logging
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_LLM_PROVIDER,
    PROVIDER_GEMINI_FREE,
    PROVIDER_QWEN_FREE,
    PROVIDER_OLLAMA_LOCAL,
    PROVIDER_CUSTOM_OPENAI,
    CONF_API_KEY,
    CONF_MODEL,
    CONF_BASE_URL,
    CONF_MCP_SERVER_URL,
    CONF_AUTONOMOUS_MODE,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_QWEN_URL,
    DEFAULT_QWEN_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_MCP_SERVER_URL,
    DEFAULT_AUTONOMOUS_MODE,
)
from .discovery import async_autodiscover_ha_mcp_url

_LOGGER = logging.getLogger(__name__)


class NexusMcpConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nexus MCP."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._provider: str | None = None
        self._llm_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Select the LLM inference provider."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._provider = user_input[CONF_LLM_PROVIDER]
            if self._provider == PROVIDER_GEMINI_FREE:
                return await self.async_step_gemini()
            if self._provider == PROVIDER_QWEN_FREE:
                return await self.async_step_qwen()
            if self._provider == PROVIDER_OLLAMA_LOCAL:
                return await self.async_step_ollama()
            return await self.async_step_custom_openai()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LLM_PROVIDER, default=PROVIDER_GEMINI_FREE
                ): vol.In(
                    {
                        PROVIDER_GEMINI_FREE: "Google Gemini (Free Tier / Gratis)",
                        PROVIDER_QWEN_FREE: "Qwen Cloud / DashScope (API Gratuita / Millones de tokens)",
                        PROVIDER_OLLAMA_LOCAL: "Ollama Local (Qwen 2.5 Coder / Gratis Local)",
                        PROVIDER_CUSTOM_OPENAI: "OpenAI / Custom BYOK",
                    }
                )
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_gemini(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure Google Gemini Free Tier."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._llm_data = {
                CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE,
                CONF_API_KEY: user_input[CONF_API_KEY].strip(),
                CONF_MODEL: user_input.get(CONF_MODEL, DEFAULT_GEMINI_MODEL).strip(),
            }
            return await self.async_step_mcp_server()

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
                vol.Optional(CONF_MODEL, default=DEFAULT_GEMINI_MODEL): str,
            }
        )

        return self.async_show_form(
            step_id="gemini",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "api_key_url": "https://aistudio.google.com/app/apikey",
            },
        )

    async def async_step_qwen(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure Qwen Cloud / DashScope Free Tier."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._llm_data = {
                CONF_LLM_PROVIDER: PROVIDER_QWEN_FREE,
                CONF_BASE_URL: user_input[CONF_BASE_URL].strip(),
                CONF_API_KEY: user_input[CONF_API_KEY].strip(),
                CONF_MODEL: user_input[CONF_MODEL].strip(),
            }
            return await self.async_step_mcp_server()

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
                vol.Optional(CONF_MODEL, default=DEFAULT_QWEN_MODEL): str,
                vol.Optional(CONF_BASE_URL, default=DEFAULT_QWEN_URL): str,
            }
        )

        return self.async_show_form(
            step_id="qwen",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "qwen_api_url": "https://modelstudio.console.alibabacloud.com/",
            },
        )

    async def async_step_ollama(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure local Ollama instance."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._llm_data = {
                CONF_LLM_PROVIDER: PROVIDER_OLLAMA_LOCAL,
                CONF_BASE_URL: user_input[CONF_BASE_URL],
                CONF_MODEL: user_input[CONF_MODEL],
            }
            return await self.async_step_mcp_server()

        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL, default=DEFAULT_OLLAMA_URL): str,
                vol.Required(CONF_MODEL, default=DEFAULT_OLLAMA_MODEL): str,
            }
        )

        return self.async_show_form(
            step_id="ollama", data_schema=schema, errors=errors
        )

    async def async_step_custom_openai(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure custom OpenAI-compatible endpoint (DashScope / OpenAI)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._llm_data = {
                CONF_LLM_PROVIDER: PROVIDER_CUSTOM_OPENAI,
                CONF_BASE_URL: user_input[CONF_BASE_URL],
                CONF_API_KEY: user_input[CONF_API_KEY],
                CONF_MODEL: user_input[CONF_MODEL],
            }
            return await self.async_step_mcp_server()

        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL): str,
                vol.Required(CONF_API_KEY): str,
                vol.Required(CONF_MODEL): str,
            }
        )

        return self.async_show_form(
            step_id="custom_openai", data_schema=schema, errors=errors
        )

    async def async_step_mcp_server(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Final step: Configure connection to ha-mcp server and autonomy."""
        errors: dict[str, str] = {}

        # Auto-discover HA-MCP Server URL if ha_mcp_tools is installed
        detected_url = async_autodiscover_ha_mcp_url(self.hass)
        default_url = detected_url or DEFAULT_MCP_SERVER_URL

        if user_input is not None:
            config_data = {
                **self._llm_data,
                CONF_MCP_SERVER_URL: user_input[CONF_MCP_SERVER_URL].strip(),
                CONF_AUTONOMOUS_MODE: user_input[CONF_AUTONOMOUS_MODE],
            }
            return self.async_create_entry(
                title=f"Nexus MCP ({self._provider})", data=config_data
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MCP_SERVER_URL, default=default_url
                ): str,
                vol.Required(
                    CONF_AUTONOMOUS_MODE, default=DEFAULT_AUTONOMOUS_MODE
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="mcp_server",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "ha_mcp_repo_url": "https://github.com/homeassistant-ai/ha-mcp",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return NexusMcpOptionsFlow(config_entry)


class NexusMcpOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Nexus MCP."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_autonomous = self.config_entry.options.get(
            CONF_AUTONOMOUS_MODE,
            self.config_entry.data.get(CONF_AUTONOMOUS_MODE, DEFAULT_AUTONOMOUS_MODE),
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_AUTONOMOUS_MODE, default=current_autonomous
                ): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
