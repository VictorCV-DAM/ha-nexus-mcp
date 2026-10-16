"""Constants for the Nexus MCP integration."""

DOMAIN = "nexus_mcp"

# LLM Providers
CONF_LLM_PROVIDER = "llm_provider"
PROVIDER_GEMINI_FREE = "gemini_free"
PROVIDER_GROQ_FREE = "groq_free"
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
DEFAULT_GROQ_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_QWEN_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen-plus-latest"
DEFAULT_OLLAMA_URL = "http://localhost:11434/v1"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"
DEFAULT_MCP_SERVER_URL = "http://localhost:8000/sse"
DEFAULT_AUTONOMOUS_MODE = False

# Entity Descriptions (Bilingual Support for Tooltips & Attributes)
ENTITY_DESCRIPTIONS_EN = {
    "conversation_history": "Most recent conversation message and activity preview.",
    "daily_tokens": "Total prompt and completion tokens used today across all requests.",
    "daily_requests_used": "Total number of queries submitted to the AI model today.",
    "daily_requests_remaining": "Remaining requests available today before hitting the daily quota.",
    "daily_quota_percent": "Percentage of daily provider requests quota remaining until midnight UTC reset.",
    "daily_requests_limit": "Maximum allowable queries per day (RPD) in the provider's free tier.",
    "model_limit": "Maximum input tokens per minute (ITPM/TPM) allowed by the provider.",
    "rpm_limit": "Maximum queries allowed within any 60-second window.",
    "max_wait_time": "Sliding window duration in seconds required for per-minute tokens to replenish.",
    "rate_limit_reset": "Live real-time cooldown seconds remaining if throttled by the provider.",
}

ENTITY_DESCRIPTIONS_ES = {
    "conversation_history": "Vista previa del último mensaje y actividad de la conversación.",
    "daily_tokens": "Total de tokens (prompt y respuesta) consumidos hoy en todas las consultas.",
    "daily_requests_used": "Número total de consultas enviadas al modelo de IA hoy.",
    "daily_requests_remaining": "Peticiones restantes disponibles hoy antes de alcanzar el tope diario.",
    "daily_quota_percent": "Porcentaje de cuota diaria de peticiones disponible hasta el reseteo de medianoche UTC.",
    "daily_requests_limit": "Límite máximo de peticiones al día (RPD) en el tier gratuito del proveedor.",
    "model_limit": "Límite máximo de tokens de entrada por minuto (ITPM/TPM) permitido por el proveedor.",
    "rpm_limit": "Límite máximo de peticiones permitidas en cualquier ventana de 60 segundos.",
    "max_wait_time": "Duración en segundos de la ventana deslizante para recuperar los tokens por minuto.",
    "rate_limit_reset": "Segundos restantes en tiempo real de bloqueo temporal si se excede el límite del proveedor.",
}


def get_entity_description(key: str, hass=None) -> str:
    """Retrieve entity functional description localized to the user's Home Assistant language."""
    if not key:
        return ""
    lang = "en"
    if hass and hasattr(hass, "config") and getattr(hass.config, "language", None):
        lang = str(hass.config.language).lower()
    if lang.startswith("es"):
        return ENTITY_DESCRIPTIONS_ES.get(key, ENTITY_DESCRIPTIONS_EN.get(key, ""))
    return ENTITY_DESCRIPTIONS_EN.get(key, ENTITY_DESCRIPTIONS_ES.get(key, ""))


# Known theoretical specifications and default tier limits
MODEL_THEORETICAL_SPECS = {
    # Groq Cloud models (Free Dev Tier)
    "openai/gpt-oss-120b": {
        "tpm": 8000,
        "rpm": 30,
        "rpd": 14400,
        "context_window": 131072,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 0,
        "reset_tz": "UTC",
    },
    "openai/gpt-oss-20b": {
        "tpm": 8000,
        "rpm": 30,
        "rpd": 14400,
        "context_window": 131072,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 0,
        "reset_tz": "UTC",
    },
    "qwen/qwen3.8-27b": {
        "tpm": 7000,
        "rpm": 30,
        "rpd": 14400,
        "context_window": 131072,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 0,
        "reset_tz": "UTC",
    },
    # Google Gemini models (Free Tier)
    "gemini-3.1-flash-lite": {
        "tpm": 250000,
        "rpm": 15,
        "rpd": 500,
        "context_window": 1048576,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 8,  # Midnight PST = 08:00 UTC
        "reset_tz": "PST (08:00 UTC)",
    },
    "gemini-flash-latest": {
        "tpm": 250000,
        "rpm": 5,
        "rpd": 20,
        "context_window": 1048576,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 8,
        "reset_tz": "PST (08:00 UTC)",
    },
    "gemini-3.8-flash": {
        "tpm": 250000,
        "rpm": 5,
        "rpd": 20,
        "context_window": 1048576,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 8,
        "reset_tz": "PST (08:00 UTC)",
    },
    # Qwen Cloud models
    "qwen-plus-latest": {
        "tpm": 60000,
        "rpm": 30,
        "rpd": 10000,
        "context_window": 131072,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 0,
        "reset_tz": "UTC",
    },
}


def get_model_specs(model: str, provider: str = "") -> dict:
    """Retrieve theoretical specifications and maximum limits for a given model."""
    clean_model = (model or "").strip()
    if clean_model.startswith("models/"):
        clean_model = clean_model[len("models/"):]
    if clean_model in MODEL_THEORETICAL_SPECS:
        return MODEL_THEORETICAL_SPECS[clean_model]

    # Model name substring matching
    lower_m = clean_model.lower()
    if "120b" in lower_m:
        return MODEL_THEORETICAL_SPECS["openai/gpt-oss-120b"]
    if "20b" in lower_m:
        return MODEL_THEORETICAL_SPECS["openai/gpt-oss-20b"]
    if "27b" in lower_m:
        return MODEL_THEORETICAL_SPECS["qwen/qwen3.8-27b"]
    if "gemini" in lower_m:
        return MODEL_THEORETICAL_SPECS["gemini-3.1-flash-lite"]

    # Defaults based on provider
    if provider == PROVIDER_GROQ_FREE:
        return {
            "tpm": 8000,
            "rpm": 30,
            "rpd": 14400,
            "context_window": 131072,
            "tpm_window_seconds": 60,
            "daily_reset_hour_utc": 0,
            "reset_tz": "UTC",
        }
    if provider == PROVIDER_GEMINI_FREE:
        return {
            "tpm": 250000,
            "rpm": 15,
            "rpd": 500,
            "context_window": 1048576,
            "tpm_window_seconds": 60,
            "daily_reset_hour_utc": 8,
            "reset_tz": "PST (08:00 UTC)",
        }
    return {
        "tpm": 60000,
        "rpm": 30,
        "rpd": 10000,
        "context_window": 128000,
        "tpm_window_seconds": 60,
        "daily_reset_hour_utc": 0,
        "reset_tz": "UTC",
    }


