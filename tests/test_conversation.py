"""Unit tests for the Nexus MCP Conversation Entity (Intercom)."""
import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

if "homeassistant" not in sys.modules:
    ha_mock = MagicMock()
    sys.modules["homeassistant"] = ha_mock
    sys.modules["homeassistant.config_entries"] = ha_mock
    sys.modules["homeassistant.core"] = ha_mock
    sys.modules["homeassistant.exceptions"] = ha_mock
    sys.modules["homeassistant.helpers"] = ha_mock
    sys.modules["homeassistant.helpers.config_validation"] = ha_mock
    sys.modules["homeassistant.helpers.aiohttp_client"] = ha_mock
    sys.modules["homeassistant.helpers.entity_platform"] = ha_mock
    sys.modules["homeassistant.helpers.intent"] = ha_mock
    sys.modules["homeassistant.components"] = ha_mock
    sys.modules["homeassistant.components.conversation"] = ha_mock
else:
    ha_mock = sys.modules["homeassistant"]

class FakeConversationEntity:
    pass

sys.modules["homeassistant.components.conversation"].ConversationEntity = FakeConversationEntity
ha_mock.components.conversation.ConversationEntity = FakeConversationEntity

class FakeIntentResponse:
    def __init__(self, language="en"):
        self.language = language
        self.speech_text = None

    def async_set_speech(self, text):
        self.speech_text = text

class FakeConversationResult:
    def __init__(self, response, conversation_id):
        self.response = response
        self.conversation_id = conversation_id

from custom_components.nexus_mcp.const import CONF_LLM_PROVIDER, PROVIDER_GEMINI_FREE
from custom_components.nexus_mcp.conversation import NexusMcpConversationEntity
from custom_components.nexus_mcp.llm_engine import LlmResponse


class TestConversationIntercom(unittest.IsolatedAsyncioTestCase):
    """Test conversation entity intercom behavior."""

    async def test_async_process_success(self) -> None:
        """Test processing user utterance and forwarding to LLM engine."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_1"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            mock_engine.generate_response.return_value = LlmResponse(
                content="¡Hola! Estoy listo para ayudarte con tu hogar inteligente."
            )
            mock_factory.return_value = mock_engine

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            user_input = MagicMock()
            user_input.text = "Hola, ¿qué puedes hacer?"
            user_input.conversation_id = "conv_1"
            user_input.language = "es"

            result = await entity.async_process(user_input)

            self.assertEqual(result.conversation_id, "conv_1")
            self.assertEqual(result.response.speech_text, "¡Hola! Estoy listo para ayudarte con tu hogar inteligente.")
            mock_engine.generate_response.assert_awaited_once()

    async def test_async_process_hallucination_interception(self) -> None:
        """Test that assistant claims of physical action without tools are intercepted."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_hallucinate"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            # First turn: model hallucinates execution text with no tool calls
            # Second turn: model is forced to call tool
            mock_engine.generate_response.side_effect = [
                LlmResponse(content="¡Listo! He ejecutado la secuencia completa y encendí la bombilla."),
                LlmResponse(content="Acción confirmada tras ejecutar las herramientas."),
            ]
            mock_factory.return_value = mock_engine

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            user_input = MagicMock()
            user_input.text = "Enciende la bombilla y cámbiala a verde"
            user_input.conversation_id = "conv_hallucinate"
            user_input.language = "es"

            result = await entity.async_process(user_input)

            # Verification: generate_response was called twice due to anti-hallucination retry
            self.assertEqual(mock_engine.generate_response.await_count, 2)
            self.assertEqual(result.response.speech_text, "Acción confirmada tras ejecutar las herramientas.")

    async def test_async_process_terse_ack_interception(self) -> None:
        """Test that model replying 'ok' to an action command is intercepted and forced to call tools."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_terse_ok"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            # First turn: model responds "ok" without any tool calls
            # Second turn: model is forced to call tools and returns confirmation
            mock_engine.generate_response.side_effect = [
                LlmResponse(content="ok"),
                LlmResponse(content="He encendido la luz del taller y la bombilla izquierda."),
            ]
            mock_factory.return_value = mock_engine

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            user_input = MagicMock()
            user_input.text = "enciende la luz del taller, enciende el aire acondicionado y enciende la bombilla izquierda"
            user_input.conversation_id = "conv_terse_ok"
            user_input.language = "es"

            result = await entity.async_process(user_input)

            # Verification: generate_response was called twice because turn 0 'ok' was intercepted
            self.assertEqual(mock_engine.generate_response.await_count, 2)
            # Turn 0 was called with tool_choice="required" because input was an action command
            first_call_kwargs = mock_engine.generate_response.await_args_list[0].kwargs
            self.assertEqual(first_call_kwargs.get("tool_choice"), "required")
            self.assertIn("He encendido", result.response.speech_text)

    async def test_async_process_conversational_no_tool_choice(self) -> None:
        """Test that a conversational query does NOT force tool_choice and returns in 1 turn."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_conversational"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            mock_engine.generate_response.return_value = LlmResponse(content="Soy el modelo GPT-4 de OpenAI.")
            mock_factory.return_value = mock_engine

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            user_input = MagicMock()
            user_input.text = "que modelo me esta respondiendo"
            user_input.conversation_id = "conv_model_query"
            user_input.language = "es"

            result = await entity.async_process(user_input)

            # Verification: exactly 1 turn, tool_choice is None (auto)
            self.assertEqual(mock_engine.generate_response.await_count, 1)
            first_call_kwargs = mock_engine.generate_response.await_args_list[0].kwargs
            self.assertIsNone(first_call_kwargs.get("tool_choice"))
            self.assertEqual(result.response.speech_text, "Soy el modelo GPT-4 de OpenAI.")

    async def test_async_process_error_handling(self) -> None:
        """Test error handling when the server fails in Spanish."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_2"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            mock_engine.generate_response.side_effect = RuntimeError("Connection refused")
            mock_factory.return_value = mock_engine

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            user_input = MagicMock()
            user_input.text = "¿Qué hora es?"
            user_input.conversation_id = "conv_2"
            user_input.language = "es"

            result = await entity.async_process(user_input)

            self.assertIn("Error al comunicar con el servidor de IA", result.response.speech_text)

    async def test_async_process_error_handling_english(self) -> None:
        """Test error handling when the server fails in English."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_en"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            mock_engine.generate_response.side_effect = RuntimeError("Connection refused")
            mock_factory.return_value = mock_engine

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            user_input = MagicMock()
            user_input.text = "What is the status of my lights?"
            user_input.conversation_id = "conv_en"
            user_input.language = "en"

            result = await entity.async_process(user_input)

            self.assertIn("Error communicating with AI server", result.response.speech_text)

    def test_is_user_confirmation(self) -> None:
        """Test detection of user confirmation based on history."""
        from custom_components.nexus_mcp.conversation import _is_user_confirmation
        from custom_components.nexus_mcp.llm_engine import ChatMessage

        proposal_history = [
            ChatMessage(role="user", content="Crea una automatización para el salón"),
            ChatMessage(
                role="assistant",
                content=(
                    "He entendido que quieres encender la luz del salón al atardecer. "
                    "¿Deseas que proceda a crear esta automatización? Responde 'sí' para confirmar."
                ),
            ),
        ]

        self.assertTrue(_is_user_confirmation(proposal_history, "sí"))
        self.assertTrue(_is_user_confirmation(proposal_history, "si"))
        self.assertTrue(_is_user_confirmation(proposal_history, "adelante por favor"))
        self.assertTrue(_is_user_confirmation(proposal_history, "créala ya"))
        self.assertTrue(_is_user_confirmation(proposal_history, "confirmo"))
        self.assertTrue(_is_user_confirmation(proposal_history, "vale"))
        self.assertFalse(_is_user_confirmation(proposal_history, "no, cancela"))
        self.assertFalse(_is_user_confirmation(proposal_history, "cambia la hora a las 10"))

        # English proposal & confirmation
        proposal_en = [
            ChatMessage(role="user", content="Turn off living room light at 11pm"),
            ChatMessage(
                role="assistant",
                content="I understood you want to turn off the living room light at 23:00. Would you like me to proceed with creating this automation? Reply 'yes' to confirm.",
            ),
        ]
        self.assertTrue(_is_user_confirmation(proposal_en, "yes"))
        self.assertTrue(_is_user_confirmation(proposal_en, "sure, proceed"))
        self.assertTrue(_is_user_confirmation(proposal_en, "confirm"))
        self.assertTrue(_is_user_confirmation(proposal_en, "do it"))
        self.assertFalse(_is_user_confirmation(proposal_en, "no, wait"))

        # First request without prior assistant proposal should be False
        first_turn_history = [
            ChatMessage(role="user", content="Crea una automatización para la luz"),
        ]
        self.assertFalse(_is_user_confirmation(first_turn_history, "Crea una automatización"))

        # General question with no proposal should be False even if user says "sí"
        general_history = [
            ChatMessage(role="user", content="¿La luz está encendida?"),
            ChatMessage(role="assistant", content="Sí, está encendida al 100%."),
        ]
        self.assertFalse(_is_user_confirmation(general_history, "sí"))

    async def test_autonomous_mode_disabled_intercepts_automation(self) -> None:
        """Test that ha_create_automation is intercepted when autonomous mode is OFF and unconfirmed."""
        from custom_components.nexus_mcp.const import CONF_AUTONOMOUS_MODE
        from custom_components.nexus_mcp.llm_engine import LlmToolCall

        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_auto_off"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}
        mock_entry.options = {CONF_AUTONOMOUS_MODE: False}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.execute_builtin_tool") as mock_exec_tool, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            # Turn 1: Model tries to call ha_create_automation directly
            # Turn 2: After seeing intercepted confirmation_required tool result, model asks for confirmation
            mock_engine.generate_response.side_effect = [
                LlmResponse(
                    content=None,
                    tool_calls=[
                        LlmToolCall(
                            call_id="call_auto_1",
                            name="ha_create_automation",
                            arguments={"alias": "Luz Salón", "trigger": [], "action": []},
                        )
                    ],
                ),
                LlmResponse(
                    content=(
                        "He preparado la automatización para encender la luz del salón. "
                        "¿Deseas que proceda a crearla? Responde 'sí' para confirmar."
                    )
                ),
            ]
            mock_factory.return_value = mock_engine

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            user_input = MagicMock()
            user_input.text = "Crea una automatización para encender la luz del salón"
            user_input.conversation_id = "conv_interception"
            user_input.language = "es"

            result = await entity.async_process(user_input)

            # execute_builtin_tool must NOT have been called because it was intercepted by guardrail
            mock_exec_tool.assert_not_called()
            self.assertIn("¿Deseas que proceda a crearla?", result.response.speech_text)

    async def test_autonomous_mode_disabled_with_user_confirmation(self) -> None:
        """Test that ha_create_automation is executed once the user confirms."""
        from custom_components.nexus_mcp.const import CONF_AUTONOMOUS_MODE
        from custom_components.nexus_mcp.llm_engine import LlmToolCall

        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_confirmed"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}
        mock_entry.options = {CONF_AUTONOMOUS_MODE: False}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.execute_builtin_tool") as mock_exec_tool, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            # Turn 1: Model asks for confirmation
            mock_engine.generate_response.return_value = LlmResponse(
                content="¿Deseas que proceda a crear la automatización del salón? Responde 'sí'."
            )
            mock_factory.return_value = mock_engine
            mock_exec_tool.return_value = {"status": "success", "entity_id": "automation.luz_salon"}

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            # Turn 1: Initial request
            user_input_1 = MagicMock()
            user_input_1.text = "Crea una automatización para el salón"
            user_input_1.conversation_id = "conv_conf_flow"
            user_input_1.language = "es"
            await entity.async_process(user_input_1)

            # Turn 2: User confirms with "Sí, adelante"
            mock_engine.generate_response.side_effect = [
                LlmResponse(
                    content=None,
                    tool_calls=[
                        LlmToolCall(
                            call_id="call_auto_2",
                            name="ha_create_automation",
                            arguments={"alias": "Luz Salón", "trigger": [], "action": []},
                        )
                    ],
                ),
                LlmResponse(content="Automatización creada y activada correctamente."),
            ]

            user_input_2 = MagicMock()
            user_input_2.text = "Sí, adelante"
            user_input_2.conversation_id = "conv_conf_flow"
            user_input_2.language = "es"

            result = await entity.async_process(user_input_2)

            # Now execute_builtin_tool MUST have been called for ha_create_automation
            mock_exec_tool.assert_called_once_with(
                mock_hass,
                "ha_create_automation",
                {"alias": "Luz Salón", "trigger": [], "action": []},
            )
            self.assertIn("Automatización creada", result.response.speech_text)

    async def test_autonomous_mode_enabled_executes_immediately(self) -> None:
        """Test that ha_create_automation executes immediately when autonomous mode is ON."""
        from custom_components.nexus_mcp.const import CONF_AUTONOMOUS_MODE
        from custom_components.nexus_mcp.llm_engine import LlmToolCall

        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_auto_on"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}
        mock_entry.options = {CONF_AUTONOMOUS_MODE: True}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.execute_builtin_tool") as mock_exec_tool, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            mock_engine.generate_response.side_effect = [
                LlmResponse(
                    content=None,
                    tool_calls=[
                        LlmToolCall(
                            call_id="call_auto_direct",
                            name="ha_create_automation",
                            arguments={"alias": "Direct Auto", "trigger": [], "action": []},
                        )
                    ],
                ),
                LlmResponse(content="Automatización creada directamente."),
            ]
            mock_factory.return_value = mock_engine
            mock_exec_tool.return_value = {"status": "success", "entity_id": "automation.direct_auto"}

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            user_input = MagicMock()
            user_input.text = "Crea una automatización para apagar todo a las 23:00"
            user_input.conversation_id = "conv_auto_direct"
            user_input.language = "es"

            result = await entity.async_process(user_input)

            # execute_builtin_tool was called immediately without asking
            mock_exec_tool.assert_called_once_with(
                mock_hass,
                "ha_create_automation",
                {"alias": "Direct Auto", "trigger": [], "action": []},
            )
            self.assertIn("Automatización creada directamente", result.response.speech_text)

    async def test_conversation_continuity_resumes_context(self) -> None:
        """Test that a new conversation session automatically inherits recent context from the previous session."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_continuity"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            mock_engine.generate_response.return_value = LlmResponse(content="Entendido, temperatura guardada.")
            mock_factory.return_value = mock_engine

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            # Turn 1 in session_A
            input_1 = MagicMock()
            input_1.text = "La temperatura deseada es 21 grados"
            input_1.conversation_id = "session_A"
            input_1.language = "es"
            await entity.async_process(input_1)

            self.assertEqual(entity._last_conversation_id, "session_A")

            # Turn 2 starts in a brand new session_B (e.g. user closed dialog and reopened Assist)
            input_2 = MagicMock()
            input_2.text = "¿Cuál era la temperatura?"
            input_2.conversation_id = "session_B"
            input_2.language = "es"
            await entity.async_process(input_2)

            # Verify session_B contains the inherited messages from session_A + the new user message
            history_b = entity._history["session_B"]
            # session_A had 1 user + 1 assistant = 2 messages. session_B now has 2 inherited + 1 user + 1 assistant = 4 messages
            self.assertEqual(len(history_b), 4)
            self.assertEqual(history_b[0].content, "La temperatura deseada es 21 grados")
            self.assertEqual(history_b[1].content, "Entendido, temperatura guardada.")
            self.assertEqual(history_b[2].content, "¿Cuál era la temperatura?")

    async def test_conversation_reset_command(self) -> None:
        """Test explicit conversation reset clears memory."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_reset"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            mock_engine.generate_response.return_value = LlmResponse(content="Respuesta normal.")
            mock_factory.return_value = mock_engine

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            # Pre-populate history
            input_1 = MagicMock()
            input_1.text = "Hola, recuérdame comprar pan"
            input_1.conversation_id = "session_reset_test"
            input_1.language = "es"
            await entity.async_process(input_1)

            self.assertIn("session_reset_test", entity._history)

            # User commands to start a new conversation
            input_reset = MagicMock()
            input_reset.text = "nueva conversación"
            input_reset.conversation_id = "session_reset_test"
            input_reset.language = "es"

            result = await entity.async_process(input_reset)

            self.assertIn("Conversación reiniciada", result.response.speech_text)
            self.assertNotIn("session_reset_test", entity._history)
            self.assertIsNone(entity._last_conversation_id)

    async def test_storage_persistence_load_and_save(self) -> None:
        """Test persistent storage loading and saving of conversation histories."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_store"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}

        mock_store = AsyncMock()
        mock_store.async_load.return_value = {
            "last_conversation_id": "loaded_session",
            "history": {
                "loaded_session": [
                    {"role": "user", "content": "Hola anterior"},
                    {"role": "assistant", "content": "Hola, te recuerdo"},
                ]
            },
        }

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine"), \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)
            entity._store = mock_store

            # Load history
            await entity.async_added_to_hass()

            self.assertEqual(entity._last_conversation_id, "loaded_session")
            self.assertIn("loaded_session", entity._history)
            self.assertEqual(len(entity._history["loaded_session"]), 2)
            self.assertEqual(entity._history["loaded_session"][0].content, "Hola anterior")

            # Save history is called when saving
            await entity._async_save_history()
            mock_store.async_save.assert_awaited()

    async def test_prune_history_to_token_budget_and_transient_error_detection(self) -> None:
        """Test token budget pruning and transient error identification."""
        from custom_components.nexus_mcp.conversation import (
            ChatMessage,
            is_transient_error_message,
            prune_history_to_token_budget,
        )

        # Transient error checks
        self.assertTrue(is_transient_error_message("Error communicating with AI server (HTTP 413 from ...: Request too large)"))
        self.assertTrue(is_transient_error_message("Error al comunicar con el servidor de IA (HTTP 429)"))
        self.assertTrue(is_transient_error_message("Límite de peticiones alcanzado (Rate limit)"))
        self.assertTrue(is_transient_error_message("Rate limit reached (TPM)"))
        self.assertFalse(is_transient_error_message("Hola, aquí tienes el resumen del tiempo."))
        self.assertFalse(is_transient_error_message(None))

        # Budget pruning
        long_text = "a" * 8000  # ~2000 tokens
        msgs = [
            ChatMessage(role="user", content="msg 1"),
            ChatMessage(role="assistant", content="Error communicating with AI server (HTTP 413)"),
            ChatMessage(role="user", content=long_text),
            ChatMessage(role="assistant", content="Normal reply"),
            ChatMessage(role="user", content="msg 5"),
        ]
        pruned = prune_history_to_token_budget(msgs, max_tokens=1000)
        # Should exclude the transient error message and older messages exceeding 1000 tokens
        self.assertTrue(all("Error communicating" not in (m.content or "") for m in pruned))
        self.assertEqual(pruned[-1].content, "msg 5")

    async def test_async_process_does_not_persist_transient_errors(self) -> None:
        """Test that transient API errors are not saved into conversation history."""
        from custom_components.nexus_mcp.llm_engine import LlmRateLimitError

        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_err"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            mock_engine.generate_response.side_effect = LlmRateLimitError("Rate limit exceeded", reset_seconds=10.0)
            mock_factory.return_value = mock_engine

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            user_input = MagicMock()
            user_input.text = "hi"
            user_input.conversation_id = "test_err_session"
            user_input.language = "en"

            result = await entity.async_process(user_input)

            self.assertIn("Rate limit reached", result.response.speech_text)
            # The failed session should not contain the error message
            session_history = entity._history.get("test_err_session", [])
            self.assertFalse(any("Rate limit" in (m.content or "") for m in session_history))

    def test_resolve_user_language_accuracy(self) -> None:
        """Verify resolve_user_language correctly identifies Spanish, Danish, and HA default."""
        from custom_components.nexus_mcp.conversation import resolve_user_language

        # 1. Complex Spanish command even if caller says 'en'
        lang_es = resolve_user_language(
            "enciende la bombilla izquierda y luego la derecha y cámbialas a color verde y luego apaga ambas tras 5 segundos",
            explicit_lang="en",
        )
        self.assertEqual(lang_es, "es")

        # 2. Short Spanish command with diacritics
        lang_es_acc = resolve_user_language("¿cómo estás?", explicit_lang="en")
        self.assertEqual(lang_es_acc, "es")

        # 3. Danish command
        lang_da = resolve_user_language("tænd lyset i stuen", explicit_lang="en")
        self.assertEqual(lang_da, "da")

        # 4. Fallback to HA config when ambiguous
        mock_hass = MagicMock()
        mock_hass.config.language = "es-ES"
        lang_ha = resolve_user_language("tv", explicit_lang="en", hass=mock_hass)
        self.assertEqual(lang_ha, "es")

    async def test_system_prompt_enforces_user_language(self) -> None:
        """Verify system prompt contains critical language directive matching user query."""
        from custom_components.nexus_mcp.const import CONF_LLM_PROVIDER, PROVIDER_GEMINI_FREE
        from custom_components.nexus_mcp.conversation import NexusMcpConversationEntity
        from custom_components.nexus_mcp.llm_engine import LlmResponse

        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_lang"
        mock_entry.data = {CONF_LLM_PROVIDER: PROVIDER_GEMINI_FREE, "api_key": "fake"}

        with patch("custom_components.nexus_mcp.conversation.create_llm_engine") as mock_factory, \
             patch("custom_components.nexus_mcp.conversation.intent.IntentResponse", side_effect=FakeIntentResponse), \
             patch("custom_components.nexus_mcp.conversation.ConversationResult", side_effect=FakeConversationResult):

            mock_engine = AsyncMock()
            mock_engine.generate_response.return_value = LlmResponse(content="Luz encendida.")
            mock_factory.return_value = mock_engine

            entity = NexusMcpConversationEntity(mock_hass, mock_entry)

            user_input = MagicMock()
            user_input.text = "enciende la luz"
            user_input.conversation_id = "conv_lang_test"
            user_input.language = "en"  # HA passed 'en', but utterance is Spanish!

            await entity.async_process(user_input)

            # Check that generate_response received the Spanish language directive
            _, kwargs = mock_engine.generate_response.call_args
            prompt = kwargs.get("system_prompt", "")
            self.assertIn("CRITICAL LANGUAGE DIRECTIVE (MANDATORY - HIGHEST PRIORITY)", prompt)
            self.assertIn("Spanish (Español)", prompt)

    def test_prune_history_preserves_active_user_and_tools(self) -> None:
        """Verify prune_history_to_token_budget never drops the active user query or tool turn."""
        from custom_components.nexus_mcp.conversation import prune_history_to_token_budget
        from custom_components.nexus_mcp.llm_engine import ChatMessage, LlmToolCall

        messages = [
            ChatMessage(role="user", content="old message 1"),
            ChatMessage(role="assistant", content="old assistant response 1"),
            ChatMessage(role="user", content="old message 2"),
            ChatMessage(role="assistant", content="old assistant response 2"),
            # Active turn with 4 tool calls and responses
            ChatMessage(role="user", content="enciende la bombilla izquierda y luego la derecha"),
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[
                    LlmToolCall(call_id="call_1", name="ha_call_service", arguments={"domain": "light", "service": "turn_on"}),
                    LlmToolCall(call_id="call_2", name="ha_call_service", arguments={"domain": "light", "service": "turn_on"}),
                ],
            ),
            ChatMessage(role="tool", content='{"status": "success"}', tool_call_id="call_1", tool_name="ha_call_service"),
            ChatMessage(role="tool", content='{"status": "success"}', tool_call_id="call_2", tool_name="ha_call_service"),
        ]

        # Prune with a very tight budget (e.g. 150 tokens) that would normally cut off messages
        pruned = prune_history_to_token_budget(messages, max_tokens=150)

        # Invariant 1: The active user message MUST be present
        user_msgs = [m for m in pruned if m.role == "user"]
        self.assertTrue(len(user_msgs) >= 1)
        self.assertEqual(user_msgs[-1].content, "enciende la bombilla izquierda y luego la derecha")

        # Invariant 2: Conversation must start with a user message
        self.assertEqual(pruned[0].role, "user")

        # Invariant 3: Tool messages still have their parent assistant message
        has_assistant_with_tools = any(m.role == "assistant" and len(m.tool_calls) > 0 for m in pruned)
        self.assertTrue(has_assistant_with_tools)

    def test_openai_engine_guarantees_user_query_for_groq_minijinja(self) -> None:
        """Verify OpenAiCompatibleEngine injects a user query if none exists to satisfy Groq minijinja."""
        from custom_components.nexus_mcp.llm_engine import OpenAiCompatibleEngine, ChatMessage

        engine = OpenAiCompatibleEngine(
            session=MagicMock(),
            base_url="https://api.groq.com/openai/v1",
            model="qwen/qwen3.8-27b",
            api_key="gsk-test",
        )

        # Test case: messages with only assistant or tool messages
        messages = [
            ChatMessage(role="assistant", content="Some response without user query"),
        ]

        # Intercept payload inside _session.post
        captured_payloads = []
        def fake_post(url, json=None, headers=None, timeout=None):
            captured_payloads.append(json)
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json.return_value = {
                "choices": [{"message": {"role": "assistant", "content": "Done"}}]
            }
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_resp
            mock_ctx.__aexit__.return_value = None
            return mock_ctx

        engine._session.post = fake_post

        import asyncio
        asyncio.run(engine.generate_response(messages=messages, system_prompt="System prompt"))

        self.assertTrue(len(captured_payloads) > 0)
        payload = captured_payloads[0]
        api_messages = payload["messages"]

        # Invariant: There MUST be at least one user query with content
        user_queries = [m for m in api_messages if m.get("role") == "user" and m.get("content")]
        self.assertTrue(len(user_queries) >= 1)


    def test_extract_candidate_search_terms_compound_command(self) -> None:
        """Verify candidate term extraction isolates clauses and area keywords from compound commands."""
        from custom_components.nexus_mcp.conversation import extract_candidate_search_terms

        text = "enciende la luz del taller, enciende el aire acondicionado y enciende la bombilla izquierda"
        terms = extract_candidate_search_terms(text)

        self.assertIn("taller", terms)
        self.assertIn("aire acondicionado", terms)
        self.assertIn("bombilla izquierda", terms)


if __name__ == "__main__":
    unittest.main()


