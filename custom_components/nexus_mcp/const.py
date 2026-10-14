"""Constants for the Nexus MCP integration."""

DOMAIN = "nexus_mcp"

# LLM Providers
CONF_LLM_PROVIDER = "llm_provider"
PROVIDER_GEMINI_FREE = "gemini_free"
PROVIDER_QWEN_FREE = "qwen_free"
PROVIDER_OLLAMA_LOCAL = "ollama_local"
PROVIDER_CUSTOM_OPENAI = "custom_openai"

CONF_API_KEY = "api_key"
CONF_MODEL = "model"
CONF_BASE_URL = "base_url"

# MCP Server Configuration
CONF_MCP_SERVER_URL = "mcp_server_url"
CONF_AUTONOMOUS_MODE = "autonomous_mode"

# Defaults
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
DEFAULT_QWEN_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen-plus-latest"
DEFAULT_OLLAMA_URL = "http://localhost:11434/v1"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"
DEFAULT_MCP_SERVER_URL = "http://localhost:8000/sse"
DEFAULT_AUTONOMOUS_MODE = False
