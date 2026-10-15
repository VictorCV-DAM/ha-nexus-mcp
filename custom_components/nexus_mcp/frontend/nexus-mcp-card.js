/**
 * Nexus MCP Plug & Play Card for Home Assistant (v1.3.0 Dev)
 * Interactive Multi-Agent AI Selector, Real-Time Chat, History & Assist.
 */

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "nexus-mcp-card")) {
  window.customCards.push({
    type: "nexus-mcp-card",
    name: "Nexus MCP Chat & Historial",
    description: "Tarjeta interactiva para chatear con cualquier IA de Home Assistant, cambiar de modelo en vivo y gestionar historiales.",
    preview: true,
    documentationURL: "https://github.com/VictorCV-DAM/ha-nexus-mcp",
  });
}

class NexusMcpCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._selectedAgent = null;
    this._conversationId = null;
    this._messages = [];
    this._isSending = false;
  }

  static getStubConfig() {
    return {
      title: "Nexus MCP Intercom",
    };
  }

  static async getConfigElement() {
    return document.createElement("nexus-mcp-card-editor");
  }

  getCardSize() {
    return 6;
  }

  setConfig(config) {
    this._config = {
      title: "Nexus MCP Intercom",
      agent_id: null,
      ...config,
    };
    if (this._config.agent_id) {
      this._selectedAgent = this._config.agent_id;
    }
    this._render();
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;

    // Auto-select agent if not already selected
    if (!this._selectedAgent) {
      const agents = this._getAvailableAgents();
      // Prefer Groq 120b or any nexus_mcp agent
      const nexusAgent = agents.find((a) => a.id.includes("nexus_mcp_intercom_openai_gpt_oss_120b"))
        || agents.find((a) => a.id.startsWith("conversation.nexus_mcp_"))
        || agents[0];
      if (nexusAgent) {
        this._selectedAgent = nexusAgent.id;
        this._loadHistoryForAgent(this._selectedAgent);
      }
    }

    if (!oldHass) {
      this._updateAgentDropdown();
      this._updateMessagesView();
    }
  }

  _getAvailableAgents() {
    if (!this._hass) return [];
    return Object.keys(this._hass.states)
      .filter((e) => e.startsWith("conversation."))
      .map((entityId) => {
        const stateObj = this._hass.states[entityId];
        let name = stateObj.attributes?.friendly_name || entityId.replace("conversation.", "");
        name = name.replace("Nexus MCP Intercom (", "").replace(")", "");
        return {
          id: entityId,
          name: name,
        };
      })
      .sort((a, b) => {
        // Put nexus_mcp agents first
        const aNexus = a.id.includes("nexus_mcp");
        const bNexus = b.id.includes("nexus_mcp");
        if (aNexus && !bNexus) return -1;
        if (!aNexus && bNexus) return 1;
        return a.name.localeCompare(b.name);
      });
  }

  _loadHistoryForAgent(agentId) {
    if (!agentId) return;
    try {
      const saved = localStorage.getItem(`nexus_mcp_history_${agentId}`);
      if (saved) {
        this._messages = JSON.parse(saved);
      } else {
        this._messages = [];
      }
    } catch (e) {
      this._messages = [];
    }
    this._updateMessagesView();
  }

  _saveHistoryForAgent(agentId) {
    if (!agentId) return;
    try {
      localStorage.setItem(`nexus_mcp_history_${agentId}`, JSON.stringify(this._messages.slice(-30)));
    } catch (e) {}
  }

  _render() {
    if (!this.shadowRoot) return;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }
        ha-card {
          display: flex;
          flex-direction: column;
          height: 100%;
          overflow: hidden;
          background: var(--card-background-color, #1e1e1e);
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,0.15));
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color, rgba(255,255,255,0.08)));
          font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
        }
        .header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          border-bottom: 1px solid var(--divider-color, rgba(255, 255, 255, 0.08));
          background: var(--app-header-background-color, transparent);
          gap: 12px;
        }
        .header-title-group {
          display: flex;
          align-items: center;
          gap: 10px;
          flex: 1;
          min-width: 0;
        }
        .header-title-group ha-icon {
          color: var(--primary-color, #03a9f4);
          --mdc-icon-size: 26px;
          flex-shrink: 0;
        }
        .agent-select {
          background: var(--secondary-background-color, rgba(255,255,255,0.06));
          color: var(--primary-text-color, #e1e1e1);
          border: 1px solid var(--divider-color, rgba(255,255,255,0.15));
          border-radius: 8px;
          padding: 6px 10px;
          font-size: 0.88rem;
          font-weight: 500;
          outline: none;
          cursor: pointer;
          max-width: 220px;
          text-overflow: ellipsis;
          overflow: hidden;
          white-space: nowrap;
          transition: border-color 0.2s;
        }
        .agent-select:focus {
          border-color: var(--primary-color, #03a9f4);
        }
        .header-actions {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-shrink: 0;
        }
        .icon-btn {
          background: transparent;
          border: none;
          cursor: pointer;
          border-radius: 50%;
          width: 32px;
          height: 32px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--secondary-text-color, #9e9e9e);
          transition: background 0.2s, color 0.2s;
        }
        .icon-btn:hover {
          background: var(--secondary-background-color, rgba(255, 255, 255, 0.08));
          color: var(--primary-text-color, #fff);
        }
        .messages-container {
          flex: 1;
          overflow-y: auto;
          max-height: 380px;
          min-height: 220px;
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
          background: var(--card-background-color, #1a1a1a);
        }
        .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100%;
          min-height: 180px;
          color: var(--secondary-text-color, #888);
          text-align: center;
          gap: 8px;
        }
        .empty-state ha-icon {
          --mdc-icon-size: 42px;
          opacity: 0.5;
        }
        .message-bubble {
          display: flex;
          flex-direction: column;
          max-width: 82%;
          animation: fadeIn 0.2s ease-in-out;
        }
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(6px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .message-bubble.user {
          align-self: flex-end;
        }
        .message-bubble.assistant {
          align-self: flex-start;
        }
        .bubble-label {
          font-size: 0.72rem;
          margin-bottom: 3px;
          font-weight: 500;
          color: var(--secondary-text-color, #888);
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .message-bubble.user .bubble-label {
          justify-content: flex-end;
        }
        .bubble-content {
          padding: 10px 14px;
          border-radius: 14px;
          font-size: 0.92rem;
          line-height: 1.45;
          white-space: pre-wrap;
          word-break: break-word;
        }
        .message-bubble.user .bubble-content {
          background: var(--primary-color, #0288d1);
          color: #fff;
          border-bottom-right-radius: 4px;
        }
        .message-bubble.assistant .bubble-content {
          background: var(--secondary-background-color, #2a2a2a);
          color: var(--primary-text-color, #f0f0f0);
          border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.08));
          border-bottom-left-radius: 4px;
        }
        .input-bar {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 14px;
          border-top: 1px solid var(--divider-color, rgba(255, 255, 255, 0.08));
          background: var(--card-background-color, #1e1e1e);
        }
        .chat-input {
          flex: 1;
          border: 1px solid var(--divider-color, rgba(255,255,255,0.15));
          border-radius: 20px;
          padding: 10px 16px;
          font-size: 0.92rem;
          outline: none;
          background: var(--secondary-background-color, rgba(255,255,255,0.05));
          color: var(--primary-text-color, #fff);
          transition: border-color 0.2s;
        }
        .chat-input:focus {
          border-color: var(--primary-color, #03a9f4);
        }
        .action-btn {
          background: var(--primary-color, #03a9f4);
          color: #fff;
          border: none;
          border-radius: 50%;
          width: 38px;
          height: 38px;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: transform 0.15s, background 0.2s;
        }
        .action-btn:hover {
          transform: scale(1.05);
        }
        .action-btn:active {
          transform: scale(0.95);
        }
        .action-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
      </style>

      <ha-card>
        <div class="header">
          <div class="header-title-group">
            <ha-icon icon="mdi:robot-happy-outline"></ha-icon>
            <select class="agent-select" id="agent-select" title="Seleccionar IA / Modelo"></select>
          </div>
          <div class="header-actions">
            <button class="icon-btn" id="btn-assist" title="Abrir Assist / Voz">
              <ha-icon icon="mdi:microphone"></ha-icon>
            </button>
            <button class="icon-btn" id="btn-reset" title="Reiniciar Conversación">
              <ha-icon icon="mdi:refresh"></ha-icon>
            </button>
          </div>
        </div>

        <div class="messages-container" id="messages-container"></div>

        <div class="input-bar">
          <input
            type="text"
            class="chat-input"
            id="chat-input"
            placeholder="Escribe un mensaje a la IA..."
            autocomplete="off"
          />
          <button class="action-btn" id="btn-send" title="Enviar">
            <ha-icon icon="mdi:send"></ha-icon>
          </button>
        </div>
      </ha-card>
    `;

    this._setupListeners();
    this._updateAgentDropdown();
    this._updateMessagesView();
  }

  _setupListeners() {
    const input = this.shadowRoot.getElementById("chat-input");
    const sendBtn = this.shadowRoot.getElementById("btn-send");
    const resetBtn = this.shadowRoot.getElementById("btn-reset");
    const assistBtn = this.shadowRoot.getElementById("btn-assist");
    const agentSelect = this.shadowRoot.getElementById("agent-select");

    if (input && sendBtn) {
      const handleSend = () => {
        const text = input.value.trim();
        if (text && !this._isSending) {
          this._sendMessage(text);
          input.value = "";
        }
      };

      sendBtn.onclick = handleSend;
      input.onkeydown = (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          handleSend();
        }
      };
    }

    if (agentSelect) {
      agentSelect.onchange = (e) => {
        this._selectedAgent = e.target.value;
        this._conversationId = null;
        this._loadHistoryForAgent(this._selectedAgent);
      };
    }

    if (resetBtn) {
      resetBtn.onclick = () => {
        this._clearHistory();
      };
    }

    if (assistBtn) {
      assistBtn.onclick = () => {
        this._openAssist();
      };
    }
  }

  _updateAgentDropdown() {
    if (!this.shadowRoot) return;
    const select = this.shadowRoot.getElementById("agent-select");
    if (!select) return;

    const agents = this._getAvailableAgents();
    if (agents.length === 0) {
      select.innerHTML = `<option value="">Buscando IAs...</option>`;
      return;
    }

    let html = "";
    for (const ag of agents) {
      const isSelected = ag.id === this._selectedAgent ? "selected" : "";
      html += `<option value="${ag.id}" ${isSelected}>${ag.name}</option>`;
    }
    select.innerHTML = html;
  }

  _updateMessagesView() {
    if (!this.shadowRoot) return;
    const container = this.shadowRoot.getElementById("messages-container");
    if (!container) return;

    if (this._messages.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <ha-icon icon="mdi:chat-outline"></ha-icon>
          <div>Sin mensajes con esta IA.</div>
          <small>Escribe abajo o pulsa el micrófono para hablar.</small>
        </div>
      `;
      return;
    }

    let html = "";
    for (const msg of this._messages) {
      const isUser = msg.role === "user";
      const label = isUser ? "🧑 Tú" : "🤖 " + (msg.agent_name || "IA");
      const content = (msg.content || "").replace(/</g, "&lt;").replace(/>/g, "&gt;");

      html += `
        <div class="message-bubble ${isUser ? "user" : "assistant"}">
          <div class="bubble-label">${label}</div>
          <div class="bubble-content">${content}</div>
        </div>
      `;
    }

    container.innerHTML = html;
    container.scrollTop = container.scrollHeight;
  }

  async _sendMessage(text) {
    if (!this._hass || !text || this._isSending) return;
    this._isSending = true;

    const agentId = this._selectedAgent;
    const agents = this._getAvailableAgents();
    const currentAgent = agents.find((a) => a.id === agentId);
    const agentName = currentAgent ? currentAgent.name : "Nexus MCP";

    // 1. Add user message
    this._messages.push({
      role: "user",
      content: text,
      timestamp: Date.now(),
    });
    this._saveHistoryForAgent(agentId);
    this._updateMessagesView();

    // 2. Add waiting bubble
    const container = this.shadowRoot.getElementById("messages-container");
    if (container) {
      const waitingBubble = document.createElement("div");
      waitingBubble.className = "message-bubble assistant waiting-bubble";
      waitingBubble.innerHTML = `
        <div class="bubble-label">🤖 ${agentName}</div>
        <div class="bubble-content" style="font-style: italic; opacity: 0.7;">Pensando...</div>
      `;
      container.appendChild(waitingBubble);
      container.scrollTop = container.scrollHeight;
    }

    const sendBtn = this.shadowRoot.getElementById("btn-send");
    if (sendBtn) sendBtn.disabled = true;

    try {
      // Direct call via Home Assistant WebSocket conversation/process
      const payload = {
        type: "conversation/process",
        text: text,
      };
      if (agentId) {
        payload.agent_id = agentId;
      }
      if (this._conversationId) {
        payload.conversation_id = this._conversationId;
      }

      const res = await this._hass.callWS(payload);
      
      const reply =
        res?.response?.speech?.plain?.speech ||
        res?.response?.card?.text ||
        "Comando procesado correctamente.";

      if (res?.conversation_id) {
        this._conversationId = res.conversation_id;
      }

      // Add assistant response to history
      this._messages.push({
        role: "assistant",
        agent_name: agentName,
        content: reply,
        timestamp: Date.now(),
      });
      this._saveHistoryForAgent(agentId);
    } catch (err) {
      console.error("Nexus MCP Card execution error:", err);
      this._messages.push({
        role: "assistant",
        agent_name: "Error",
        content: `Error al procesar: ${err.message || JSON.stringify(err)}`,
        timestamp: Date.now(),
      });
      this._saveHistoryForAgent(agentId);
    } finally {
      this._isSending = false;
      if (sendBtn) sendBtn.disabled = false;
      this._updateMessagesView();
    }
  }

  async _clearHistory() {
    const agentId = this._selectedAgent;
    this._messages = [];
    this._conversationId = null;
    if (agentId) {
      try {
        localStorage.removeItem(`nexus_mcp_history_${agentId}`);
      } catch (e) {}
    }

    // Try to notify HA to clear memory
    if (this._hass) {
      if (this._hass.services?.nexus_mcp?.clear_history) {
        try {
          await this._hass.callService("nexus_mcp", "clear_history", {});
        } catch (e) {
          console.debug("Could not call clear_history:", e);
        }
      }

      // Send conversational reset command to active agent via WebSocket
      try {
        await this._hass.callWS({
          type: "conversation/process",
          text: "nueva conversación",
          agent_id: agentId,
        });
      } catch (e) {
        console.debug("Could not send conversational reset:", e);
      }
    }

    this._updateMessagesView();
  }

  _openAssist() {
    const event = new CustomEvent("hass-action", {
      bubbles: true,
      composed: true,
      detail: {
        config: {
          tap_action: {
            action: "assist",
          },
        },
        action: "tap",
      },
    });
    this.dispatchEvent(event);
  }
}

class NexusMcpCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass) return;

    const agents = Object.keys(this._hass.states)
      .filter((e) => e.startsWith("conversation."))
      .map((id) => ({
        id,
        name: this._hass.states[id].attributes?.friendly_name || id,
      }));

    let optionsHtml = `<option value="">(Automático / Selector en vivo)</option>`;
    for (const ag of agents) {
      const isSel = this._config?.agent_id === ag.id ? "selected" : "";
      optionsHtml += `<option value="${ag.id}" ${isSel}>${ag.name}</option>`;
    }

    this.innerHTML = `
      <div style="padding: 16px; display: flex; flex-direction: column; gap: 14px;">
        <label style="display: flex; flex-direction: column; gap: 4px; font-weight: 500;">
          Título de la tarjeta
          <input
            type="text"
            id="cfg-title"
            value="${this._config.title || "Nexus MCP Intercom"}"
            style="padding: 8px 12px; border-radius: 6px; border: 1px solid var(--divider-color, #ccc);"
          />
        </label>
        <label style="display: flex; flex-direction: column; gap: 4px; font-weight: 500;">
          IA / Agente predeterminado (Opcional)
          <select id="cfg-agent" style="padding: 8px 12px; border-radius: 6px; border: 1px solid var(--divider-color, #ccc);">
            ${optionsHtml}
          </select>
        </label>
        <small style="color: var(--secondary-text-color, #666);">
          La tarjeta incluye un selector en su cabecera para cambiar de modelo de IA al vuelo.
        </small>
      </div>
    `;

    const titleInput = this.querySelector("#cfg-title");
    const agentSelect = this.querySelector("#cfg-agent");

    const handleChange = () => {
      const newConfig = {
        ...this._config,
        title: titleInput.value,
        agent_id: agentSelect.value || undefined,
      };
      const event = new CustomEvent("config-changed", {
        detail: { config: newConfig },
        bubbles: true,
        composed: true,
      });
      this.dispatchEvent(event);
    };

    if (titleInput) titleInput.oninput = handleChange;
    if (agentSelect) agentSelect.onchange = handleChange;
  }
}

customElements.define("nexus-mcp-card", NexusMcpCard);
customElements.define("nexus-mcp-card-editor", NexusMcpCardEditor);
console.info(
  "%c NEXUS MCP CARD %c v1.3.0 Multi-Agent Ready ",
  "color: white; background: #03a9f4; font-weight: bold; padding: 2px 6px; border-radius: 4px 0 0 4px;",
  "color: #03a9f4; background: #e1f5fe; font-weight: bold; padding: 2px 6px; border-radius: 0 4px 4px 0;"
);
