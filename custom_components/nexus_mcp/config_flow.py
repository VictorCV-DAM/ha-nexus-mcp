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
    PROVIDER_GROQ_FREE,
    PROVIDER_QWEN_FREE,
    PROVIDER_OLLAMA_LOCAL,
    PROVIDER_CUSTOM_OPENAI,
    CONF_API_KEY,
    CONF_MODEL,
    CONF_BASE_URL,
    CONF_MCP_SERVER_URL,
    CONF_AUTONOMOUS_MODE,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GROQ_URL,
    DEFAULT_GROQ_MODEL,
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
            if self._provider == PROVIDER_GROQ_FREE:
                return await self.async_step_groq()
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
                        PROVIDER_GROQ_FREE: "Groq Cloud (Qwen / Llama - 100% Gratis en Europa, 14.400 req/día)",
                        PROVIDER_QWEN_FREE: "Qwen Cloud / DashScope (Alibaba Model Studio)",
                        PROVIDER_OLLAMA_LOCAL: "Ollama Local (Qwen 2.5 Coder / Gratis Local)",
                        PROVIDER_CUSTOM_OPENAI: "OpenAI / OpenRouter / Custom BYOK",
                    }
                )
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "gemini_api_url": "https://aistudio.google.com/app/apikey",
                "groq_api_url": "https://console.groq.com/keys",
                "qwen_api_url": "https://modelstudio.console.alibabacloud.com/",
                "openrouter_api_url": "https://openrouter.ai/keys",
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguring an existing Nexus MCP entry."""
        return await self.async_step_user()

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

    async def async_step_groq(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure Groq Cloud Free Tier."""
        errors: dict[str, str] = {}

        if user_input is not None:
            raw_model = user_input.get(CONF_MODEL, DEFAULT_GROQ_MODEL).strip()
            if raw_model in ("qwen3.8-27b", "qwen-27b", "qwen3.8", "qwen-3.8-27b"):
                raw_model = "qwen/qwen3.8-27b"
            elif raw_model in ("gpt-oss-120b", "120b", "openai-120b"):
                raw_model = "openai/gpt-oss-120b"
            elif raw_model in ("gpt-oss-20b", "20b", "openai-20b"):
                raw_model = "openai/gpt-oss-20b"
            elif "llama" in raw_model.lower():
                raw_model = "qwen/qwen3.8-27b"

            self._llm_data = {
                CONF_LLM_PROVIDER: PROVIDER_GROQ_FREE,
                CONF_BASE_URL: user_input.get(CONF_BASE_URL, DEFAULT_GROQ_URL).strip(),
                CONF_API_KEY: user_input[CONF_API_KEY].strip(),
                CONF_MODEL: raw_model,
            }
            return await self.async_step_mcp_server()

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
                vol.Optional(CONF_MODEL, default=DEFAULT_GROQ_MODEL): str,
                vol.Optional(CONF_BASE_URL, default=DEFAULT_GROQ_URL): str,
            }
        )

        return self.async_show_form(
            step_id="groq",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "groq_api_url": "https://console.groq.com/keys",
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
            step_id="custom_openai",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "openrouter_api_url": "https://openrouter.ai/keys",
                "openai_api_url": "https://platform.openai.com/api-keys",
                "deepseek_api_url": "https://platform.deepseek.com/api_keys",
            },
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
            model_name = config_data.get(CONF_MODEL) or self._provider
            return self.async_create_entry(
                title=f"Nexus MCP ({model_name})", data=config_data
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


_BaseOptionsFlow = getattr(
    config_entries, "OptionsFlowWithConfigEntry", config_entries.OptionsFlow
)


class NexusMcpOptionsFlow(_BaseOptionsFlow):
    """Handle options flow for Nexus MCP."""

    def __init__(self, config_entry: config_entries.ConfigEntry | None = None) -> None:
        """Initialize options flow."""
        try:
            super().__init__(config_entry)
        except TypeError:
            super().__init__()
        self._config_entry = config_entry

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        """Return the config entry."""
        if getattr(self, "_config_entry", None) is not None:
            return self._config_entry
        return super().config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options: allow updating credentials, tokens, models, and server URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            updated_data = dict(self.config_entry.data or {})
            for k in (
                CONF_API_KEY,
                CONF_MODEL,
                CONF_BASE_URL,
                CONF_MCP_SERVER_URL,
                CONF_AUTONOMOUS_MODE,
            ):
                if k in user_input and user_input[k] is not None:
                    val = user_input[k]
                    updated_data[k] = val.strip() if isinstance(val, str) else val

            if updated_data.get(CONF_LLM_PROVIDER) == PROVIDER_GROQ_FREE or "groq.com" in updated_data.get(CONF_BASE_URL, ""):
                m = updated_data.get(CONF_MODEL, "")
                if m in ("qwen3.8-27b", "qwen-27b", "qwen3.8", "qwen-3.8-27b"):
                    updated_data[CONF_MODEL] = "qwen/qwen3.8-27b"
                elif m in ("gpt-oss-120b", "120b", "openai-120b"):
                    updated_data[CONF_MODEL] = "openai/gpt-oss-120b"
                elif m in ("gpt-oss-20b", "20b", "openai-20b"):
                    updated_data[CONF_MODEL] = "openai/gpt-oss-20b"
                elif "llama" in m.lower():
                    updated_data[CONF_MODEL] = "qwen/qwen3.8-27b"

            model_name = updated_data.get(CONF_MODEL) or updated_data.get(CONF_LLM_PROVIDER)
            new_title = f"Nexus MCP ({model_name})" if model_name else self.config_entry.title

            self.hass.config_entries.async_update_entry(
                self.config_entry, title=new_title, data=updated_data, options=user_input
            )
            return self.async_create_entry(title="", data=user_input)

        data = self.config_entry.data or {}
        options = self.config_entry.options or {}

        provider = data.get(CONF_LLM_PROVIDER, PROVIDER_GEMINI_FREE)
        current_api_key = data.get(CONF_API_KEY, "") or ""
        current_model = data.get(CONF_MODEL, "") or ""
        current_base_url = data.get(CONF_BASE_URL, "") or ""
        current_mcp_url = data.get(CONF_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL) or DEFAULT_MCP_SERVER_URL
        current_autonomous = options.get(
            CONF_AUTONOMOUS_MODE,
            data.get(CONF_AUTONOMOUS_MODE, DEFAULT_AUTONOMOUS_MODE),
        )
        if current_autonomous is None:
            current_autonomous = DEFAULT_AUTONOMOUS_MODE

        fields: dict[Any, Any] = {}
        if provider in (
            PROVIDER_GEMINI_FREE,
            PROVIDER_GROQ_FREE,
            PROVIDER_QWEN_FREE,
            PROVIDER_CUSTOM_OPENAI,
        ):
            fields[vol.Optional(CONF_API_KEY, default=current_api_key)] = str
        if current_model or provider in (
            PROVIDER_GEMINI_FREE,
            PROVIDER_GROQ_FREE,
            PROVIDER_QWEN_FREE,
            PROVIDER_OLLAMA_LOCAL,
            PROVIDER_CUSTOM_OPENAI,
        ):
            fields[vol.Optional(CONF_MODEL, default=current_model)] = str
        if current_base_url or provider in (
            PROVIDER_GROQ_FREE,
            PROVIDER_QWEN_FREE,
            PROVIDER_OLLAMA_LOCAL,
            PROVIDER_CUSTOM_OPENAI,
        ):
            fields[vol.Optional(CONF_BASE_URL, default=current_base_url)] = str

        fields[vol.Required(CONF_MCP_SERVER_URL, default=current_mcp_url)] = str
        fields[vol.Required(CONF_AUTONOMOUS_MODE, default=bool(current_autonomous))] = bool

        schema = vol.Schema(fields)

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "provider": provider,
                "gemini_api_url": "https://aistudio.google.com/app/apikey",
                "groq_api_url": "https://console.groq.com/keys",
                "qwen_api_url": "https://modelstudio.console.alibabacloud.com/",
                "openrouter_api_url": "https://openrouter.ai/keys",
                "openai_api_url": "https://platform.openai.com/api-keys",
                "deepseek_api_url": "https://platform.deepseek.com/api_keys",
                "ha_mcp_repo_url": "https://github.com/homeassistant-ai/ha-mcp",
            },
        )
