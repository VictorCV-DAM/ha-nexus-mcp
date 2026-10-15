/**
 * Nexus MCP Plug & Play Card for Home Assistant
 * Interactive Chat, Conversation History, and Quick Assist Integration.
 */

// Register card in Home Assistant Card Picker
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "nexus-mcp-card")) {
  window.customCards.push({
    type: "nexus-mcp-card",
    name: "Nexus MCP Chat & Historial",
    description: "Tarjeta interactiva para chatear, ver el historial y retomar conversaciones con Nexus MCP.",
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
    this._isSending = false;
  }

  static getStubConfig() {
    return {
      title: "Nexus MCP Intercom",
      entity: "sensor.nexus_mcp_historial_de_conversaciones",
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
      entity: "sensor.nexus_mcp_historial_de_conversaciones",
      ...config,
    };
    this._render();
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;

    // Auto-discover sensor if configured entity doesn't exist
    if (this._config.entity && !hass.states[this._config.entity]) {
      const candidates = Object.keys(hass.states).filter(
        (e) => e.startsWith("sensor.nexus_mcp_") && e.includes("historial")
      );
      if (candidates.length > 0) {
        this._config.entity = candidates[0];
      }
    }

    const entityId = this._config.entity;
    const currentState = entityId ? hass.states[entityId] : null;
    const oldState = oldHass && entityId ? oldHass.states[entityId] : null;

    if (!oldHass || currentState !== oldState) {
      this._updateContent();
    }
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
          background: var(--card-background-color, #fff);
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,0.08));
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color, #e0e0e0));
          font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
        }
        .header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 14px 16px;
          border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
          background: var(--app-header-background-color, transparent);
        }
        .header-title {
          display: flex;
          align-items: center;
          gap: 10px;
          font-size: 1.1rem;
          font-weight: 600;
          color: var(--primary-text-color, #212121);
        }
        .header-title ha-icon {
          color: var(--primary-color, #03a9f4);
          --mdc-icon-size: 24px;
        }
        .header-actions {
          display: flex;
          align-items: center;
          gap: 6px;
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
          color: var(--secondary-text-color, #757575);
          transition: background 0.2s, color 0.2s;
        }
        .icon-btn:hover {
          background: var(--secondary-background-color, rgba(0, 0, 0, 0.05));
          color: var(--primary-text-color, #212121);
        }
        .messages-container {
          flex: 1;
          overflow-y: auto;
          max-height: 380px;
          min-height: 200px;
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
          background: var(--card-background-color, #fff);
        }
        .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100%;
          min-height: 160px;
          color: var(--secondary-text-color, #757575);
          text-align: center;
          gap: 8px;
        }
        .empty-state ha-icon {
          --mdc-icon-size: 40px;
          opacity: 0.6;
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
          color: var(--secondary-text-color, #757575);
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
          line-height: 1.4;
          white-space: pre-wrap;
          word-break: break-word;
        }
        .message-bubble.user .bubble-content {
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
          border-bottom-right-radius: 4px;
        }
        .message-bubble.assistant .bubble-content {
          background: var(--secondary-background-color, #f5f5f5);
          color: var(--primary-text-color, #212121);
          border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
          border-bottom-left-radius: 4px;
        }
        .input-bar {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 14px;
          border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
          background: var(--card-background-color, #fff);
        }
        .chat-input {
          flex: 1;
          border: 1px solid var(--divider-color, #ccc);
          border-radius: 20px;
          padding: 10px 16px;
          font-size: 0.92rem;
          outline: none;
          background: var(--secondary-background-color, #fff);
          color: var(--primary-text-color, #212121);
          transition: border-color 0.2s;
        }
        .chat-input:focus {
          border-color: var(--primary-color, #03a9f4);
        }
        .action-btn {
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
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
        .action-btn.secondary {
          background: var(--secondary-background-color, #f0f0f0);
          color: var(--primary-text-color, #212121);
          border: 1px solid var(--divider-color, #ccc);
        }
      </style>

      <ha-card>
        <div class="header">
          <div class="header-title">
            <ha-icon icon="mdi:robot-happy-outline"></ha-icon>
            <span id="title">${this._config.title || "Nexus MCP Intercom"}</span>
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

        <div class="messages-container" id="messages-container">
          <div class="empty-state">
            <ha-icon icon="mdi:forum-outline"></ha-icon>
            <div>Cargando historial de Nexus MCP...</div>
          </div>
        </div>

        <div class="input-bar">
          <input
            type="text"
            class="chat-input"
            id="chat-input"
            placeholder="Escribe a Nexus MCP..."
            autocomplete="off"
          />
          <button class="action-btn" id="btn-send" title="Enviar">
            <ha-icon icon="mdi:send"></ha-icon>
          </button>
        </div>
      </ha-card>
    `;

    this._setupListeners();
    this._updateContent();
  }

  _setupListeners() {
    const input = this.shadowRoot.getElementById("chat-input");
    const sendBtn = this.shadowRoot.getElementById("btn-send");
    const resetBtn = this.shadowRoot.getElementById("btn-reset");
    const assistBtn = this.shadowRoot.getElementById("btn-assist");

    if (input && sendBtn) {
      const handleSend = () => {
        const text = input.value.trim();
        if (text) {
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

  _updateContent() {
    if (!this.shadowRoot || !this._hass) return;

    const titleEl = this.shadowRoot.getElementById("title");
    if (titleEl) {
      titleEl.textContent = this._config.title || "Nexus MCP Intercom";
    }

    const container = this.shadowRoot.getElementById("messages-container");
    if (!container) return;

    const entityId = this._config.entity;
    const stateObj = entityId ? this._hass.states[entityId] : null;

    if (!stateObj) {
      container.innerHTML = `
        <div class="empty-state">
          <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
          <div>Esperando entidad <code>${entityId || "sensor"}</code></div>
          <small>Nexus MCP creará el historial al recibir mensajes.</small>
        </div>
      `;
      return;
    }

    const history = stateObj.attributes?.history || [];

    if (history.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <ha-icon icon="mdi:chat-outline"></ha-icon>
          <div>Sin conversaciones recientes.</div>
          <small>Escribe abajo o pulsa el micrófono para hablar con Nexus MCP.</small>
        </div>
      `;
      return;
    }

    let html = "";
    for (const msg of history) {
      const role = msg.role || "user";
      const content = (msg.content || "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const isUser = role === "user";
      const label = isUser ? "🧑 Tú" : "🤖 Nexus MCP";

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
    if (!this._hass || !text) return;

    // Optimistically render user message
    const container = this.shadowRoot.getElementById("messages-container");
    if (container) {
      const emptyState = container.querySelector(".empty-state");
      if (emptyState) emptyState.remove();

      const userBubble = document.createElement("div");
      userBubble.className = "message-bubble user";
      userBubble.innerHTML = `
        <div class="bubble-label">🧑 Tú</div>
        <div class="bubble-content">${text.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</div>
      `;
      container.appendChild(userBubble);

      const waitingBubble = document.createElement("div");
      waitingBubble.className = "message-bubble assistant waiting-bubble";
      waitingBubble.innerHTML = `
        <div class="bubble-label">🤖 Nexus MCP</div>
        <div class="bubble-content" style="font-style: italic; opacity: 0.7;">Pensando...</div>
      `;
      container.appendChild(waitingBubble);
      container.scrollTop = container.scrollHeight;
    }

    const sendBtn = this.shadowRoot.getElementById("btn-send");
    if (sendBtn) sendBtn.disabled = true;

    try {
      // Find the Nexus MCP conversation agent if present
      const agentId = Object.keys(this._hass.states).find(
        (e) => e.startsWith("conversation.nexus_mcp_")
      );

      const serviceData = { text };
      if (agentId) {
        serviceData.agent_id = agentId;
      }

      await this._hass.callService("conversation", "process", serviceData);
    } catch (err) {
      console.error("Nexus MCP Card error sending utterance:", err);
      if (container) {
        const errorBubble = document.createElement("div");
        errorBubble.className = "message-bubble assistant";
        errorBubble.innerHTML = `
          <div class="bubble-label">⚠️ Error</div>
          <div class="bubble-content" style="color: var(--error-color, red);">No se pudo enviar el mensaje: ${err.message || err}</div>
        `;
        container.appendChild(errorBubble);
      }
    } finally {
      if (sendBtn) sendBtn.disabled = false;
      const waiting = container?.querySelector(".waiting-bubble");
      if (waiting) waiting.remove();
    }
  }

  async _clearHistory() {
    if (!this._hass) return;
    try {
      await this._hass.callService("nexus_mcp", "clear_history", {});
      const container = this.shadowRoot.getElementById("messages-container");
      if (container) {
        container.innerHTML = `
          <div class="empty-state">
            <ha-icon icon="mdi:check-circle-outline"></ha-icon>
            <div>Conversación reiniciada.</div>
            <small>La memoria de Nexus MCP se ha restablecido correctamente.</small>
          </div>
        `;
      }
    } catch (err) {
      console.error("Nexus MCP Card error clearing history:", err);
    }
  }

  _openAssist() {
    // Triggers standard Home Assistant Assist popup dialog
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
  }

  _render() {
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
          Entidad de Historial (Sensor)
          <input
            type="text"
            id="cfg-entity"
            value="${this._config.entity || "sensor.nexus_mcp_historial_de_conversaciones"}"
            style="padding: 8px 12px; border-radius: 6px; border: 1px solid var(--divider-color, #ccc);"
          />
        </label>
        <small style="color: var(--secondary-text-color, #666);">
          La tarjeta detecta automáticamente el sensor de Nexus MCP y muestra los mensajes en tiempo real.
        </small>
      </div>
    `;

    const titleInput = this.querySelector("#cfg-title");
    const entityInput = this.querySelector("#cfg-entity");

    const handleChange = () => {
      const newConfig = {
        ...this._config,
        title: titleInput.value,
        entity: entityInput.value,
      };
      const event = new CustomEvent("config-changed", {
        detail: { config: newConfig },
        bubbles: true,
        composed: true,
      });
      this.dispatchEvent(event);
    };

    if (titleInput && entityInput) {
      titleInput.oninput = handleChange;
      entityInput.oninput = handleChange;
    }
  }
}

customElements.define("nexus-mcp-card", NexusMcpCard);
customElements.define("nexus-mcp-card-editor", NexusMcpCardEditor);
console.info(
  "%c NEXUS MCP CARD %c v1.2.0 Loaded Successfully ",
  "color: white; background: #03a9f4; font-weight: bold; padding: 2px 6px; border-radius: 4px 0 0 4px;",
  "color: #03a9f4; background: #e1f5fe; font-weight: bold; padding: 2px 6px; border-radius: 0 4px 4px 0;"
);
