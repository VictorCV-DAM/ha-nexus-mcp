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
    PROVIDER_OLLAMA_LOCAL,
    get_model_specs,
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

ACTION_COMMAND_REGEX = re.compile(
    r"\b(enciende|encender|enciéndelas|enciendelas|enciendela|enciéndela|"
    r"apaga|apagar|apágalas|apagalas|apágala|apagala|"
    r"cambia|cambiar|cámbialas|cambialas|cámbiala|cambiala|"
    r"prende|prender|préndelas|prendelas|préndela|prendela|"
    r"pon|poner|ponlas|ponla|"
    r"ajusta|ajustar|ajústalas|ajustalas|"
    r"sube|subir|baja|bajar|"
    r"activa|activar|desactiva|desactivar|"
    r"abre|abrir|cierra|cerrar|"
    r"turn on|turn off|toggle)\b",
    re.IGNORECASE,
)


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
        or c_lower.startswith("[error:")
        or "[error:" in c_lower
        or "http 413" in c_lower
        or "http 429" in c_lower
        or "http 400" in c_lower
    )


def extract_candidate_search_terms(text: str) -> list[str]:
    """Extract candidate entity names / search keywords from action prompt or assistant text."""
    if not text:
        return []
    terms: list[str] = []
    clean = re.sub(r"[!?,.:;\(\)\[\]]", " ", text)
    keywords = [
        "taller", "aire acondicionado", "aire", "bombilla izquierda", "bombilla derecha",
        "bombilla", "monitor", "salon", "cocina", "ventilador", "enchufe", "calefactor",
        "luces", "luz", "interruptor"
    ]
    for kw in keywords:
        if kw in clean.lower() and kw not in terms:
            terms.append(kw)

    # Split compound commands separated by commas, 'y', or 'luego'
    clauses = re.split(r"[,;]|\s+y\s+|\s+luego\s+", text, flags=re.IGNORECASE)
    for clause in clauses:
        clause_clean = clause.strip()
        m = re.search(
            r"(?:enciende|apaga|cambia|ajusta|pon|busca|id de|dispositivo|dispositivos)\s+(?:el|la|los|las|del|de)?\s*([a-záéíóúñ0-9_\s]{2,30})",
            clause_clean,
            re.IGNORECASE,
        )
        if m:
            cand = m.group(1).strip().lower()
            cand = re.sub(r"^(?:de|del|la|el|los|las)\s+", "", cand).strip()
            if cand and len(cand) >= 2 and cand not in terms and cand not in ("todo", "todas", "dispositivo", "dispositivos", "automatización", "automatizacion"):
                terms.append(cand)
                # If term has "luz del taller" -> also add "taller"
                for sep in (" del ", " de "):
                    if sep in cand:
                        sub = cand.split(sep)[-1].strip()
                        if sub and len(sub) >= 3 and sub not in terms:
                            terms.append(sub)

    return terms[:6]


def prune_history_to_token_budget(
    messages: list[ChatMessage], max_tokens: int = 3500
) -> list[ChatMessage]:
    """Ensure conversation history fits safely within the model's input token limits.

    Guarantees:
    1. The active turn (from the latest user message to the end, including tool calls and responses)
       is NEVER pruned or separated, guaranteeing a valid 'user' query is ALWAYS present.
    2. Older historical turns are pruned from oldest to newest if budget is exceeded.
    3. The pruned message list always starts with a 'user' message (never starting with an orphan 'tool' or 'assistant').
    4. Consecutive user messages are merged into a single user message to maintain valid dialogue alternation.
    """
    if not messages:
        return []

    # Strip any transient error messages from history
    cleaned = [m for m in messages if not is_transient_error_message(m.content)]
    if not cleaned:
        cleaned = list(messages)

    # Merge consecutive user messages to maintain valid turn alternation
    merged: list[ChatMessage] = []
    for m in cleaned:
        if m.role == "user" and merged and merged[-1].role == "user":
            prev_txt = merged[-1].content or ""
            curr_txt = m.content or ""
            merged[-1].content = f"{prev_txt}\n\n{curr_txt}".strip()
            if m.image_data and not merged[-1].image_data:
                merged[-1].image_data = m.image_data
        else:
            merged.append(m)
    cleaned = merged

    # 1. Identify the active turn: from the latest user message to the end
    last_user_idx = -1
    for idx in range(len(cleaned) - 1, -1, -1):
        if cleaned[idx].role == "user":
            last_user_idx = idx
            break

    if last_user_idx == -1:
        # Fallback: No user message found in cleaned; use last message
        active_turn = [cleaned[-1]]
        older_messages = cleaned[:-1]
    else:
        active_turn = cleaned[last_user_idx:]
        older_messages = cleaned[:last_user_idx]

    def estimate_tokens(msg: ChatMessage) -> int:
        content_len = len(msg.content or "")
        tc_len = sum(len(tc.name) + len(json.dumps(tc.arguments, default=str)) for tc in msg.tool_calls) if msg.tool_calls else 0
        return max(1, (content_len + tc_len) // 4) + 20

    active_tokens = sum(estimate_tokens(m) for m in active_turn)

    # If the active turn alone exceeds budget, trim tool responses inside active turn
    # but NEVER drop the user message or the assistant tool_calls
    if active_tokens > max_tokens:
        for m in active_turn:
            if m.role == "tool" and m.content and len(m.content) > 600:
                m.content = m.content[:600] + "... [trimmed]"

    # 2. Add older messages from newest to oldest as budget permits
    pruned_older: list[ChatMessage] = []
    budget_remaining = max_tokens - sum(estimate_tokens(m) for m in active_turn)

    for msg in reversed(older_messages):
        msg_tokens = estimate_tokens(msg)
        if budget_remaining - msg_tokens < 0:
            break
        pruned_older.insert(0, msg)
        budget_remaining -= msg_tokens

    result = pruned_older + active_turn

    # 3. Clean boundary: Ensure the conversation starts with a 'user' message
    # Drop any leading 'tool' or 'assistant' messages from pruned older history
    while result and result[0].role in ("tool", "assistant") and any(m.role == "user" for m in result):
        result.pop(0)

    # 4. Final guarantee: Ensure there is at least one non-empty 'user' message
    if not any(m.role == "user" and bool(m.content) for m in result):
        if last_user_idx != -1:
            result.insert(0, cleaned[last_user_idx])
        else:
            result.insert(0, ChatMessage(role="user", content="Execute requested command."))

    return result


COMMON_LANG_PATTERNS = {
    "es": {
        "words": {
            "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "en", "y", "o", "a",
            "que", "qué", "por", "para", "con", "no", "si", "sí", "enciende", "apaga", "luz", "luces",
            "bombilla", "bombillas", "habitacion", "habitación", "salon", "salón", "casa", "dispositivo",
            "dispositivos", "cambia", "cámbialas", "cambialas", "pon", "ponlas", "como", "cómo", "hola",
            "cuál", "color", "verde", "rojo", "azul", "ambas", "ambos", "tras", "después", "despues",
            "segundos", "minutos", "deseas", "crea", "muestra", "dime", "cuéntame", "ayuda", "temperatura",
            "nueva", "conversación", "conversacion", "reiniciar", "reinicia", "olvida", "borrar",
        },
        "chars": {"á", "é", "í", "ó", "ú", "ñ", "¿", "¡"},
        "name": "Spanish (Español)",
    },
    "da": {
        "words": {
            "og", "i", "jeg", "det", "på", "den", "til", "er", "som", "de", "med", "han",
            "af", "for", "ikke", "der", "var", "mig", "sig", "men", "et", "har", "om", "vi", "min",
            "havde", "ham", "hun", "nu", "over", "da", "fra", "du", "ud", "sin", "dem", "os", "op",
            "man", "hans", "hvor", "eller", "hvad", "skal", "selv", "her", "tænd", "sluk", "lys", "stue",
        },
        "chars": {"æ", "ø", "å"},
        "name": "Danish (Dansk)",
    },
    "fr": {
        "words": {
            "le", "la", "les", "un", "une", "des", "du", "de", "dans", "en", "et", "ou", "où", "pour",
            "avec", "sur", "est", "sont", "allume", "éteins", "lumière", "maison", "chambre", "comment",
            "pourquoi", "salut", "bonjour", "merci",
        },
        "chars": {"é", "è", "ê", "à", "ç", "ù", "œ"},
        "name": "French (Français)",
    },
    "de": {
        "words": {
            "der", "die", "das", "ein", "eine", "einen", "und", "oder", "in", "den", "dem", "des",
            "mit", "auf", "für", "ist", "sind", "schalte", "ein", "aus", "licht", "lampe", "zimmer",
            "haus", "wie", "hallo", "danke",
        },
        "chars": {"ä", "ö", "ü", "ß"},
        "name": "German (Deutsch)",
    },
    "it": {
        "words": {
            "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "a", "da", "in", "con",
            "su", "per", "tra", "fra", "è", "sono", "accendi", "spegni", "luce", "luci", "casa", "ciao",
        },
        "chars": {"à", "è", "é", "ì", "ò", "ù"},
        "name": "Italian (Italiano)",
    },
}


def resolve_user_language(
    text: str, explicit_lang: str | None = None, hass: HomeAssistant | None = None
) -> str:
    """Accurately detect the conversation language from user utterance and HA configuration."""
    clean_text = (text or "").lower().strip()
    words = set(re.findall(r"[\wáéíóúÁÉÍÓÚñÑæøåÆØÅäöüÄÖÜßàèêùç]+", clean_text))

    # 1. First, check unique language-specific characters in the text
    for lang, data in COMMON_LANG_PATTERNS.items():
        if any(ch in clean_text for ch in data["chars"]):
            return lang

    # 2. Count keyword hits for candidate languages
    best_lang = None
    best_score = 0
    for lang, data in COMMON_LANG_PATTERNS.items():
        matches = len(words.intersection(data["words"]))
        if matches > best_score:
            best_score = matches
            best_lang = lang

    # If we have keyword hits, use that language
    if best_score >= 1 and best_lang:
        return best_lang

    # 3. Check explicit language provided by caller (if not generic English)
    if explicit_lang:
        clean_exp = explicit_lang.lower().split("-")[0].split("_")[0].strip()
        if clean_exp and clean_exp != "en":
            return clean_exp

    # 4. Check Home Assistant instance UI language
    if hass and hasattr(hass, "config") and getattr(hass.config, "language", None):
        ha_lang = str(hass.config.language).lower().split("-")[0].split("_")[0].strip()
        if ha_lang and ha_lang in COMMON_LANG_PATTERNS:
            return ha_lang
        if ha_lang:
            return ha_lang

    # 5. Default fallback to caller explicit language or Spanish if Spanish keywords detected, else English
    if explicit_lang:
        return explicit_lang.lower().split("-")[0].split("_")[0].strip()
    return "es"


def build_language_directive(lang_code: str) -> str:
    """Build a powerful, unequivocal system prompt instruction enforcing the user's language."""
    lang_info = {
        "es": "Spanish (Español)",
        "da": "Danish (Dansk)",
        "fr": "French (Français)",
        "de": "German (Deutsch)",
        "it": "Italian (Italiano)",
        "pt": "Portuguese (Português)",
        "nl": "Dutch (Nederlands)",
        "ca": "Catalan (Català)",
        "gl": "Galician (Galego)",
        "eu": "Basque (Euskara)",
        "en": "English",
    }
    lang_name = lang_info.get(lang_code, lang_code)
    if lang_code == "es":
        return (
            "CRITICAL LANGUAGE DIRECTIVE (MANDATORY - HIGHEST PRIORITY):\n"
            "You MUST formulate ALL your responses, explanations, device feedback, and questions EXCLUSIVELY in Spanish (Español).\n"
            "The user is speaking Spanish. NEVER answer in English or any other language, even though tool names, entity IDs, "
            "and system instructions are in English. Always communicate with the user purely in Spanish (e.g. 'He encendido las luces')."
        )
    return (
        f"CRITICAL LANGUAGE DIRECTIVE (MANDATORY - HIGHEST PRIORITY):\n"
        f"You MUST formulate ALL your responses, explanations, device feedback, and questions EXCLUSIVELY in {lang_name}.\n"
        f"The user is speaking {lang_name}. NEVER answer in English or any other language, even though tool names, entity IDs, "
        f"and system instructions are in English. Always communicate with the user purely in {lang_name}."
    )



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
            "sw_version": "1.4.2",
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
        try:
            self.async_write_ha_state()
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
        try:
            self.async_write_ha_state()
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

                    # If the user changed the AI model, do not inherit old conversations from the previous model
                    stored_model = stored_telemetry.get("model") if isinstance(stored_telemetry, dict) else None
                    current_model = self._model_name
                    if stored_model and current_model and stored_model != current_model:
                        _LOGGER.info(
                            "Nexus MCP model changed from '%s' to '%s'; resetting conversation history.",
                            stored_model,
                            current_model,
                        )
                        raw_history = {}
                        self._last_conversation_id = None
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
        """Return extra state attributes for frontend discovery and live telemetry."""
        is_vision = False
        if hasattr(self._engine, "_is_vision_model"):
            is_vision = bool(self._engine._is_vision_model())
        elif isinstance(self._engine, GeminiEngine):
            is_vision = True

        model_name = self.entry.options.get(
            CONF_MODEL, self.entry.data.get(CONF_MODEL, "")
        )
        provider = self.entry.options.get(
            CONF_LLM_PROVIDER, self.entry.data.get(CONF_LLM_PROVIDER, "")
        )
        specs = get_model_specs(model_name, provider)
        limit_tpm = self._telemetry.get("limit_tokens") or specs.get("tpm", 8000)

        return {
            "has_vision": is_vision,
            "provider": provider,
            "model": model_name,
            "entry_id": self.entry.entry_id,
            "tokens_today": self._telemetry.get("tokens_today", 0),
            "last_total_tokens": self._telemetry.get("last_total_tokens", 0),
            "limit_tokens_minute": limit_tpm,
            "remaining_tokens_minute": self._telemetry.get("remaining_tokens"),
            "rate_limit_status": self._telemetry.get("rate_limit_status", "ok"),
            "rate_limit_reset_seconds": self._telemetry.get("rate_limit_reset_seconds", 0.0),
        }

    async def async_chat_process(
        self,
        text: str,
        image_data: str | None = None,
        conversation_id: str = "default",
        language: str | None = None,
    ) -> str:
        """Process chat message with optional multimodal image data and enforce user language."""
        if not self._history_loaded:
            await self._async_load_history()

        history = self._history.setdefault(conversation_id, [])
        history.append(ChatMessage(role="user", content=text, image_data=image_data))
        if len(history) > MAX_HISTORY_MESSAGES:
            history = history[-MAX_HISTORY_MESSAGES:]
            self._history[conversation_id] = history

        user_lang = resolve_user_language(text, language, self.hass)
        lang_prompt = build_language_directive(user_lang)

        system_prompt = (
            f"{lang_prompt}\n\n"
            "You are Nexus MCP, an autonomous AI assistant embedded directly inside Home Assistant. "
            "You can analyze images, inspect entities, and assist the user in their smart home.\n"
            "Whenever you provide YAML configurations, Lovelace card configs, scripts, automations, templates, or code, you MUST always enclose them in Markdown code blocks with the language tag (e.g. ```yaml ... ```, ```json ... ```, or ```python ... ```). Never output bare code or bare YAML without code blocks.\n\n"
            f"{lang_prompt}"
        )

        try:
            resp = await self._engine.generate_response(
                messages=prune_history_to_token_budget(history, max_tokens=3500),
                tools=self._tools,
                system_prompt=system_prompt,
            )
            if hasattr(resp, "usage") and resp.usage:
                self.record_usage(resp.usage, getattr(resp, "rate_limits", None))
            reply = resp.content or ("Acción completada." if user_lang == "es" else "Action completed.")
        except LlmRateLimitError as err:
            if history and history[-1].role == "user":
                history.pop()
            reset_sec = getattr(err, "reset_seconds", 5.0) or 5.0
            self.record_rate_limit(reset_sec)
            raise err
        except Exception as err:
            err_str = str(err)
            if image_data and any(w in err_str.lower() for w in ("image", "vision", "multimodal", "support", "400")):
                is_spanish = user_lang == "es"
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
                if history and history[-1].role == "user":
                    history.pop()
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
            reset_lang = resolve_user_language(text, getattr(user_input, "language", None), self.hass)
            intent_response = intent.IntentResponse(language=reset_lang)
            reply = (
                "Conversación reiniciada. ¿En qué puedo ayudarte?"
                if reset_lang == "es"
                else "Conversation reset. How can I help you?"
            )
            intent_response.async_set_speech(reply)
            return ConversationResult(
                response=intent_response,
                conversation_id=conversation_id,
            )

        history = self._history.setdefault(conversation_id, [])
        initial_history_len = len(history)
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
        is_action_request = bool(ACTION_COMMAND_REGEX.search(text))

        # Check if the user is giving an affirmative continuation (e.g. 'dale', 'vale', 'adelante', 'hazlo', 'procede', 'ok')
        clean_text_lower = text.lower().strip()
        is_affirmative_continuation = clean_text_lower in (
            "dale", "vale", "adelante", "hazlo", "procede", "proceder", "continua",
            "continúa", "ok", "de acuerdo", "perfecto", "sí", "si", "yes", "do it",
            "go ahead", "proceed", "claro", "por supuesto", "venga"
        )
        if is_affirmative_continuation:
            # Check if any recent assistant message discussed searching, controlling devices or automations
            has_pending_action = any(
                m.role == "assistant" and any(
                    k in (m.content or "").lower() for k in ("buscar", "encender", "apagar", "cambiar", "automatiz", "dispositivo", "entidad", "taller", "bombilla", "aire")
                )
                for m in history[-4:]
            )
            if has_pending_action:
                is_action_request = True
                user_confirmed = True

        user_lang = resolve_user_language(text, getattr(user_input, "language", None), self.hass)
        is_spanish = user_lang == "es"
        lang_prompt = build_language_directive(user_lang)

        model_identity = f"You are Nexus MCP, an autonomous AI assistant powered by '{self._model_name}' ({self._provider}) embedded directly inside Home Assistant.\n"
        base_system_prompt = (
            f"{model_identity}"
            "You have direct access to tools to search entities (ha_search_entities), read states (ha_get_entity_state), "
            "control devices (ha_call_service), and create/activate automations (ha_create_automation).\n"
            "CRITICAL DEVICE CONTROL MANDATE (PHYSICAL HARDWARE EXECUTION):\n"
            "- You CANNOT control physical hardware with text or words alone. The ONLY way devices turn on/off or change color in the real world is by invoking `ha_call_service` in a tool call.\n"
            "- ALWAYS prioritize immediate execution using `ha_call_service` when the user asks to turn on/off, toggle, "
            "dim, adjust, change colors, run sequences, or control devices/lights (even with multiple devices or short delays).\n"
            "- ENTITY RESOLUTION MANDATE:\n"
            "  If the user names devices, rooms, or areas (e.g. 'luz del taller', 'aire acondicionado', 'bombilla izquierda') "
            "  and you do not know their exact entity_id, you MUST immediately call `ha_search_entities` (e.g. with query: 'taller', 'aire', 'bombilla', etc.) to discover them. "
            "  NEVER output 'ok', 'listo', or text claiming completion without calling tools!\n"
            "- SINGLE-TURN EXECUTION MANDATE FOR SEQUENCES AND TIMED ACTIONS:\n"
            "  1. When turning on lights and changing color (e.g. 'enciende las bombillas y cámbialas a color púrpura'), combine them into a single `ha_call_service` with domain: 'light', service: 'turn_on', data: {'rgb_color': [128, 0, 128]}. Do NOT make a separate call or turn just to set the color!\n"
            "  2. `ha_call_service` supports an optional 'delay' parameter in seconds (e.g. delay: 5 for 5 seconds).\n"
            "  3. Emit ALL sequence steps as multiple tool calls in ONE SINGLE TURN (e.g., call 1: turn_on with rgb_color; call 2: turn_off with delay: 5). Do NOT wait across multiple turns to execute each step!\n"
            "- MULTI-DEVICE EXECUTION MANDATE:\n"
            "  When the user asks to control multiple devices (e.g. 'enciende la luz del taller, enciende el aire acondicionado y enciende la bombilla izquierda'), you MUST execute `ha_call_service` for EVERY device that you can identify. NEVER abort or stop execution for the other devices just because one device is missing or not found. Control the devices you found first, and then in your conversational response inform the user which devices were controlled and ask for clarification only on the missing device.\n"
            "- LIGHTS AS SMART PLUGS / SWITCHES:\n"
            "  In Home Assistant, lights are frequently controlled via smart plugs or relays in the 'switch' domain (e.g. `switch.luz_taller_enchufe_1`). When searching for or controlling lights or lamps, if an entity is not found under `light`, check the `switch` domain as well. `ha_call_service` with service 'turn_on' works seamlessly for both switches and lights.\n"
            "- Direct commands (`ha_call_service`), searching (`ha_search_entities`), and reading states (`ha_get_entity_state`) "
            "NEVER require confirmation and MUST be executed immediately without asking!\n"
            "- NEVER call `ha_create_automation` unless the user explicitly requests a persistent or recurring automation "
            "(e.g., using words like 'crea una automatización', 'automatiza', 'todos los días a las...', or 'cuando ocurra X haz Y').\n"
            "Rules for creating automations with ha_create_automation (ONLY when explicitly requested):\n"
            "1. In 'trigger', for time intervals use: [{'platform': 'time_pattern', 'seconds': '/5'}]. Never use 'pattern'.\n"
            "2. In 'action', call services using: [{'service': 'domain.service_name', 'target': {'entity_id': '...'}}]. Never use 'domain' as a separate key.\n"
            "3. Tool argument formatting: You must provide strictly valid JSON in all tool arguments. Never include unescaped characters, backticks, conversational filler, or malformed tags inside tool calls.\n"
            "4. Code & YAML formatting: Whenever you provide YAML configurations, Lovelace card configs, scripts, automations, templates, or code, you MUST always enclose them in Markdown code blocks with the language tag (e.g. ```yaml ... ```, ```json ... ```, or ```python ... ```). Never output bare code or bare YAML without code blocks.\n"
        )

        if self._provider == PROVIDER_OLLAMA_LOCAL:
            base_system_prompt += (
                "- LOCAL MODEL / OLLAMA TOOL CALL FORMAT:\n"
                "  When invoking tools, you may use standard tool calls or output strictly valid JSON within <tools>...</tools> or <tool_call>...</tool_call> tags:\n"
                "  <tools>\n"
                "  {\"name\": \"ha_call_service\", \"arguments\": {\"domain\": \"light\", \"service\": \"turn_on\", \"service_data\": {\"entity_id\": \"...\"}}}\n"
                "  </tools>\n"
            )

        if autonomous_mode:
            autonomy_prompt = (
                "AUTONOMOUS MODE: ENABLED.\n"
                "You have full permission to execute actions and create automations directly without asking for confirmation. "
                "Execute the requested service or create the automation directly using your tools."
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
                "CONFIRMATION POLICY FOR AUTOMATIONS:\n"
                "- Device control (`ha_call_service`), searching (`ha_search_entities`), and reading states (`ha_get_entity_state`) "
                "NEVER require confirmation and MUST be executed immediately without asking!\n"
                "- Confirmation is ONLY required when the user explicitly asked to create a persistent automation with `ha_create_automation`.\n"
                "- If the user asks to create an automation:\n"
                "  1. If needed, use ha_search_entities or ha_get_entity_state to find the correct entity IDs.\n"
                "  2. Describe the exact automation you plan to create (trigger, condition, action, entity IDs).\n"
                "  3. Ask the user for explicit confirmation (for example: '{confirm_example}').\n"
                "  4. DO NOT call ha_create_automation until the user confirms in the next turn."
            )

        system_prompt = f"{lang_prompt}\n\n{base_system_prompt}\n\n{autonomy_prompt}\n\n{lang_prompt}"

        assistant_reply = "OK."
        executed_any_tool = False
        force_tool_choice = "required" if is_action_request else None
        hallucination_retried = False

        try:
            # Multi-turn tool execution loop (up to 5 turns)
            for turn_idx in range(5):
                response = await self._engine.generate_response(
                    messages=prune_history_to_token_budget(history, max_tokens=1500),
                    tools=self._tools,
                    system_prompt=system_prompt,
                    tool_choice=force_tool_choice,
                )
                force_tool_choice = None

                if hasattr(response, "usage") and response.usage:
                    self.record_usage(response.usage, getattr(response, "rate_limits", None))

                if response.tool_calls:
                    executed_any_tool = True
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
                            is_explicit_automation_request = any(
                                w in text.lower()
                                for w in (
                                    "automatiza", "automatizacion", "automatización", "automation",
                                    "crea una automatización", "crear automatizacion", "crea la regla",
                                    "programa una", "schedule", "todos los días a las", "todas las mañanas",
                                )
                            )
                            if not is_explicit_automation_request:
                                intercept_err = (
                                    "El usuario NO ha pedido crear una automatización persistente, sino controlar dispositivos directamente. "
                                    "NO utilices ha_create_automation. Ejecuta la acción inmediatamente usando ha_call_service "
                                    "(puedes usar el parámetro 'delay' en segundos si hay esperas temporales, por ejemplo delay: 5 para apagar tras 5s)."
                                    if is_spanish
                                    else (
                                        "The user did NOT request to create a persistent automation; they asked for direct device control. "
                                        "DO NOT use ha_create_automation. Execute the action immediately using ha_call_service "
                                        "(use the 'delay' parameter in seconds for timed waits, e.g. delay: 5 to turn off after 5s)."
                                    )
                                )
                            else:
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

                # Anti-hallucination / unexecuted-action check: If no tools were called in this session,
                # but the model's text claims execution or the user gave a direct action command:
                content_lower = (response.content or "").lower().strip()
                claims_action = any(
                    p in content_lower
                    for p in (
                        "he ejecutado", "he encendido", "he apagado", "he cambiado",
                        "encendí", "apagué", "cambié", "he puesto", "puse",
                        "secuencia completa", "deberían estar ahora", "deberian estar ahora",
                        "i've turned", "i have turned", "i turned off", "i turned on",
                        "i've executed", "i have executed", "done! i've",
                    )
                )
                claims_intent_to_search_or_act = any(
                    p in content_lower
                    for p in (
                        "vamos a buscar", "buscaremos", "voy a buscar", "debo buscar", "primero buscaremos",
                        "primero buscaré", "primero voy a", "buscar el id", "buscaremos el id",
                        "vamos a encender", "voy a encender", "vamos a apagar", "voy a apagar",
                        "i will search", "let me search", "let's search", "i will turn", "let me turn",
                    )
                )
                is_terse_ack = content_lower.rstrip("!.,") in (
                    "ok", "listo", "hecho", "entendido", "de acuerdo", "claro", "done", "perfecto", "ya está", "ya esta"
                )
                is_unexecuted = False
                if not executed_any_tool and not hallucination_retried:
                    if claims_action or claims_intent_to_search_or_act or is_terse_ack:
                        is_unexecuted = True
                    elif is_action_request and "?" not in content_lower and not any(
                        err_word in content_lower
                        for err_word in ("no encuentro", "no encontré", "no pude", "no existe", "could not find", "unable to")
                    ):
                        is_unexecuted = True

                if is_unexecuted:
                    _LOGGER.warning(
                        "Nexus MCP intercepted unexecuted action command without tool calls: '%s'. Forcing ha_call_service/ha_search_entities execution.",
                        (response.content or "")[:120],
                    )
                    hallucination_retried = True
                    force_tool_choice = "required"

                    # Proactive entity resolution: If the model is talking about searching or needing IDs,
                    # automatically query Home Assistant for entities matching terms from the user request and assistant text!
                    extracted_terms = extract_candidate_search_terms(f"{text} {response.content or ''}")
                    found_entities_summary: list[str] = []
                    if extracted_terms and self.hass:
                        for term in extracted_terms:
                            try:
                                s_res = await execute_builtin_tool(self.hass, "ha_search_entities", {"query": term})
                                matches = s_res.get("results") or s_res.get("matches") or []
                                if matches:
                                    for m in matches[:3]:
                                        found_entities_summary.append(
                                            f"- {m.get('entity_id')} (Nombre: {m.get('name') or m.get('friendly_name')}, estado: {m.get('state')})"
                                        )
                            except Exception as ex:
                                _LOGGER.debug("Auto-search error for '%s': %s", term, ex)

                    if response.content:
                        history.append(ChatMessage(role="assistant", content=response.content))

                    if found_entities_summary:
                        entities_text = "\n".join(found_entities_summary)
                        correction_prompt = (
                            f"[ENTIDADES ENCONTRADAS AUTOMÁTICAMENTE EN HOME ASSISTANT:\n"
                            f"{entities_text}\n\n"
                            "INSTRUCCIÓN OBLIGATORIA: Las entidades de arriba corresponden a lo que el usuario pidió. "
                            "NO vuelvas a decir que vas a buscar ni pidas confirmación. "
                            "Emite INMEDIATAMENTE las llamadas a `ha_call_service` utilizando los `entity_id` encontrados.]"
                            if is_spanish
                            else (
                                f"[AUTOMATICALLY RESOLVED ENTITIES FROM HOME ASSISTANT:\n"
                                f"{entities_text}\n\n"
                                "MANDATORY INSTRUCTION: The entities above match what the user requested. "
                                "DO NOT say you will search or ask again. "
                                "Emit `ha_call_service` calls immediately using the found entity IDs.]"
                            )
                        )
                    else:
                        correction_prompt = (
                            "[ERROR: No has llamado a ninguna herramienta (`ha_call_service` o `ha_search_entities`). "
                            "Tus palabras o responder con 'ok' NO controlan dispositivos físicos en Home Assistant. "
                            "Para ejecutar la petición del usuario debes emitir OBLIGATORIAMENTE las llamadas a herramientas "
                            "(`ha_call_service` para controlar dispositivos o `ha_search_entities` para encontrar sus IDs). "
                            "Emite las llamadas a herramientas AHORA.]"
                            if is_spanish
                            else (
                                "[ERROR: You have not called any tool (`ha_call_service` or `ha_search_entities`). "
                                "Words or saying 'ok' DO NOT control physical devices in Home Assistant. "
                                "You MUST emit the required tool calls (`ha_call_service` or `ha_search_entities`) NOW.]"
                            )
                        )
                    history.append(ChatMessage(role="user", content=correction_prompt))
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
        if is_transient_error_message(assistant_reply):
            # If an error occurred, revert history to clean state before this request
            del history[initial_history_len:]
        else:
            # Clean up any temporary internal hallucination error retry messages before saving
            cleaned_history = [
                m for m in history if not (m.role == "user" and m.content and m.content.startswith("[ERROR:"))
            ]
            self._history[conversation_id] = cleaned_history
            history = cleaned_history
            if not history or history[-1].role != "assistant":
                history.append(ChatMessage(role="assistant", content=assistant_reply))

        self._last_conversation_id = conversation_id
        await self._async_save_history()

        # Build Home Assistant intent response
        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(assistant_reply)

        return ConversationResult(
            response=intent_response,
            conversation_id=conversation_id,
        )
