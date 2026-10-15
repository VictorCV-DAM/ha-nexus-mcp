/**
 * Nexus MCP Plug & Play Card for Home Assistant (v1.3.6)
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
    this._attachedImage = null;
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
    } else {
      try {
        const saved = localStorage.getItem("nexus_mcp_selected_agent");
        if (saved) {
          this._selectedAgent = saved;
        }
      } catch (e) {}
    }
    this._render();
  }

  connectedCallback() {
    this._scrollToBottom(false);
  }

  _scrollToBottom(smooth = false) {
    const doScroll = () => {
      if (!this.shadowRoot) return;
      const container = this.shadowRoot.getElementById("messages-container");
      if (!container) return;
      if (smooth) {
        container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
      } else {
        container.scrollTop = container.scrollHeight;
      }
    };

    doScroll();
    requestAnimationFrame(() => {
      doScroll();
      setTimeout(doScroll, 40);
      setTimeout(doScroll, 120);
      setTimeout(doScroll, 300);
      setTimeout(doScroll, 600);
    });
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;

    // Auto-select agent if not already selected
    if (!this._selectedAgent) {
      const agents = this._getAvailableAgents();
      let savedAgent = null;
      try {
        savedAgent = localStorage.getItem("nexus_mcp_selected_agent");
      } catch (e) {}
      const matchedSaved = savedAgent && agents.find((a) => a.id === savedAgent);
      // Prefer saved agent from localStorage, then Groq 120b, then any nexus_mcp agent
      const nexusAgent = matchedSaved
        || agents.find((a) => a.id.includes("nexus_mcp_intercom_openai_gpt_oss_120b"))
        || agents.find((a) => a.id.startsWith("conversation.nexus_mcp_"))
        || agents[0];
      if (nexusAgent) {
        this._selectedAgent = nexusAgent.id;
        this._loadHistoryForAgent(this._selectedAgent);
      }
    }

    if (!oldHass) {
      this._updateAgentDropdown();
      this._updateVisionBadge();
      if (this._selectedAgent) {
        this._loadHistoryForAgent(this._selectedAgent);
      }
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

  async _loadHistoryForAgent(agentId) {
    if (!agentId) return;

    // 1. Instant local render from localStorage if available
    try {
      const saved = localStorage.getItem(`nexus_mcp_history_${agentId}`);
      if (saved) {
        this._messages = JSON.parse(saved);
        this._updateMessagesView();
      } else {
        this._messages = [];
      }
    } catch (e) {
      this._messages = [];
    }

    // 2. Sync with Home Assistant backend history via WebSocket so all browsers/devices share conversations
    if (this._hass && this._hass.callWS) {
      try {
        const res = await this._hass.callWS({
          type: "nexus_mcp/get_history",
          agent_id: agentId,
        });
        if (res && Array.isArray(res.messages) && res.messages.length > 0) {
          const agents = this._getAvailableAgents();
          const currentAgent = agents.find((a) => a.id === agentId);
          const agentName = currentAgent ? currentAgent.name : "Nexus MCP";
          if (res.conversation_id) {
            this._conversationId = res.conversation_id;
          }
          this._messages = res.messages.map((m) => ({
            role: m.role,
            content: m.content,
            agent_name: m.role === "assistant" ? agentName : undefined,
            timestamp: Date.now(),
          }));
          this._saveHistoryForAgent(agentId);
          this._updateMessagesView();
          return;
        }
      } catch (err) {
        console.debug("Could not fetch backend history:", err);
      }
    }

    this._updateMessagesView();
  }

  _saveHistoryForAgent(agentId) {
    if (!agentId) return;
    try {
      const historyToSave = this._messages.slice(-30).map((m) => {
        if (m.image && m.image.length > 50000) {
          return { ...m, image: null, has_image: true };
        }
        return m;
      });
      localStorage.setItem(`nexus_mcp_history_${agentId}`, JSON.stringify(historyToSave));
    } catch (e) {
      console.warn("Could not save history to localStorage:", e);
    }
  }

  _isSpanish() {
    const lang = String(
      this._hass?.locale?.language ||
      this._hass?.language ||
      this._hass?.selectedLanguage ||
      navigator.language ||
      "es"
    ).toLowerCase();
    return lang.startsWith("es");
  }

  _render() {
    if (!this.shadowRoot) return;

    const isEs = this._isSpanish();
    const txtConfig = isEs ? "Configurar Nexus MCP" : "Configure Nexus MCP";
    const txtSelectModel = isEs ? "Seleccionar IA / Modelo" : "Select AI / Model";
    const txtAssist = isEs ? "Abrir Assist / Voz" : "Open Assist / Voice";
    const txtReset = isEs ? "Reiniciar Conversación" : "Reset Conversation";
    const txtRemoveImg = isEs ? "Eliminar imagen" : "Remove image";
    const txtAttached = isEs ? "Imagen adjunta (lista para enviar)" : "Attached image (ready to send)";
    const txtAttach = isEs ? "Adjuntar imagen (o pega con Ctrl+V)" : "Attach image (or paste with Ctrl+V)";
    const txtPlaceholder = isEs ? "Escribe un mensaje o pega una imagen (Ctrl+V)..." : "Type a message or paste an image (Ctrl+V)...";
    const txtSend = isEs ? "Enviar" : "Send";

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
          padding: 10px 14px;
          border-bottom: 1px solid var(--divider-color, rgba(255, 255, 255, 0.08));
          background: var(--app-header-background-color, transparent);
          gap: 8px;
          min-width: 0;
        }
        .header-title-group {
          display: flex;
          align-items: center;
          gap: 8px;
          flex: 1;
          min-width: 0;
          overflow: hidden;
        }
        .header-icon-btn {
          background: transparent;
          border: none;
          padding: 0;
          margin: 0;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 50%;
          transition: transform 0.15s, opacity 0.2s;
          flex-shrink: 0;
        }
        .header-icon-btn:hover {
          transform: scale(1.1);
          opacity: 0.85;
        }
        .header-icon-btn:active {
          transform: scale(0.95);
        }
        .header-icon-btn ha-icon {
          color: var(--primary-color, #03a9f4);
          --mdc-icon-size: 24px;
          flex-shrink: 0;
        }
        .agent-select {
          background: var(--secondary-background-color, rgba(255,255,255,0.06));
          color: var(--primary-text-color, #e1e1e1);
          border: 1px solid var(--divider-color, rgba(255,255,255,0.15));
          border-radius: 8px;
          padding: 5px 8px;
          font-size: 0.85rem;
          font-weight: 500;
          outline: none;
          cursor: pointer;
          width: 100%;
          min-width: 0;
          flex: 1;
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
        .vision-badge {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 3px 7px;
          border-radius: 12px;
          font-size: 0.72rem;
          font-weight: 600;
          cursor: default;
          user-select: none;
          transition: background 0.2s, color 0.2s, border-color 0.2s;
          flex-shrink: 0;
          white-space: nowrap;
        }
        .vision-badge.has-vision {
          background: rgba(76, 175, 80, 0.16);
          color: #81c784;
          border: 1px solid rgba(76, 175, 80, 0.4);
        }
        .vision-badge.has-vision ha-icon {
          --mdc-icon-size: 14px;
          color: #81c784;
        }
        .vision-badge.no-vision {
          background: rgba(255, 255, 255, 0.05);
          color: var(--secondary-text-color, #9e9e9e);
          border: 1px solid rgba(255, 255, 255, 0.12);
        }
        .vision-badge.no-vision ha-icon {
          --mdc-icon-size: 14px;
          color: var(--secondary-text-color, #9e9e9e);
        }
        @media (max-width: 360px) {
          .vision-badge span {
            display: none;
          }
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
        .bubble-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 4px;
        }
        .message-bubble.user .bubble-header {
          flex-direction: row-reverse;
        }
        .bubble-label {
          font-size: 0.72rem;
          font-weight: 500;
          color: var(--secondary-text-color, #888);
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .bubble-copy-btn {
          background: transparent;
          border: none;
          padding: 2px 4px;
          cursor: pointer;
          opacity: 0.5;
          transition: opacity 0.2s, color 0.2s, transform 0.15s;
          color: var(--secondary-text-color, #9e9e9e);
          display: inline-flex;
          align-items: center;
          justify-content: center;
          border-radius: 4px;
        }
        .bubble-copy-btn:hover {
          opacity: 1;
          color: var(--primary-text-color, #fff);
          transform: scale(1.1);
        }
        .bubble-copy-btn.copied {
          color: #4caf50 !important;
          opacity: 1 !important;
        }
        .bubble-copy-btn ha-icon {
          --mdc-icon-size: 15px;
        }
        .bubble-image {
          max-width: 100%;
          max-height: 220px;
          border-radius: 8px;
          margin-bottom: 8px;
          display: block;
          object-fit: contain;
          background: rgba(0, 0, 0, 0.2);
        }
        .bubble-content {
          padding: 10px 14px;
          border-radius: 14px;
          font-size: 0.92rem;
          line-height: 1.45;
          white-space: pre-wrap;
          word-break: break-word;
          user-select: text;
          -webkit-user-select: text;
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
        .code-block-container {
          margin: 8px 0;
          border-radius: 8px;
          overflow: hidden;
          background: #151515;
          border: 1px solid rgba(255, 255, 255, 0.12);
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
          text-align: left;
          white-space: normal;
        }
        .code-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 5px 10px;
          background: #222;
          border-bottom: 1px solid rgba(255, 255, 255, 0.08);
          font-family: var(--code-font-family, Consolas, Monaco, monospace);
          font-size: 0.74rem;
          color: var(--secondary-text-color, #aaa);
          text-transform: uppercase;
          font-weight: 600;
          letter-spacing: 0.5px;
        }
        .code-copy-btn {
          background: transparent;
          border: none;
          color: var(--secondary-text-color, #bbb);
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 0.74rem;
          font-weight: 500;
          padding: 2px 6px;
          border-radius: 4px;
          transition: background 0.15s, color 0.15s;
        }
        .code-copy-btn:hover {
          background: rgba(255, 255, 255, 0.12);
          color: #fff;
        }
        .code-copy-btn.copied {
          color: #4caf50 !important;
        }
        .code-copy-btn ha-icon {
          --mdc-icon-size: 14px;
        }
        .code-content {
          margin: 0;
          padding: 10px 12px;
          overflow-x: auto;
          font-family: var(--code-font-family, Consolas, Monaco, "Courier New", monospace);
          font-size: 0.86rem;
          line-height: 1.45;
          color: #e0e0e0;
          background: transparent;
          white-space: pre;
          word-break: normal;
        }
        .inline-code {
          background: rgba(255, 255, 255, 0.1);
          color: #ffb74d;
          padding: 2px 5px;
          border-radius: 4px;
          font-family: var(--code-font-family, Consolas, Monaco, monospace);
          font-size: 0.88em;
        }
        .image-preview-bar {
          display: none;
          align-items: center;
          padding: 8px 14px;
          background: var(--secondary-background-color, #232323);
          border-top: 1px solid var(--divider-color, rgba(255, 255, 255, 0.08));
          gap: 12px;
        }
        .image-preview-bar.active {
          display: flex;
        }
        .preview-box {
          position: relative;
          display: inline-block;
        }
        .preview-box img {
          max-height: 56px;
          max-width: 90px;
          border-radius: 6px;
          border: 1px solid var(--primary-color, #03a9f4);
          display: block;
          object-fit: cover;
        }
        .preview-remove-btn {
          position: absolute;
          top: -6px;
          right: -6px;
          background: rgba(30, 30, 30, 0.9);
          color: #ff5252;
          border: 1px solid rgba(255, 255, 255, 0.2);
          border-radius: 50%;
          width: 18px;
          height: 18px;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          padding: 0;
          transition: transform 0.15s;
        }
        .preview-remove-btn:hover {
          transform: scale(1.15);
        }
        .preview-remove-btn ha-icon {
          --mdc-icon-size: 14px;
        }
        .preview-caption {
          font-size: 0.78rem;
          color: var(--secondary-text-color, #aaa);
          font-style: italic;
        }
        .input-bar {
          display: flex;
          align-items: flex-end;
          gap: 8px;
          padding: 8px 12px;
          border-top: 1px solid var(--divider-color, rgba(255, 255, 255, 0.08));
          background: var(--card-background-color, #1e1e1e);
        }
        .action-btn-attach {
          background: transparent;
          color: var(--secondary-text-color, #9e9e9e);
          border: none;
          border-radius: 50%;
          width: 36px;
          height: 36px;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: color 0.2s, background 0.2s;
          flex-shrink: 0;
          margin-bottom: 7px;
        }
        .action-btn-attach:hover {
          color: var(--primary-text-color, #fff);
          background: var(--secondary-background-color, rgba(255, 255, 255, 0.08));
        }
        .action-btn-attach ha-icon {
          --mdc-icon-size: 22px;
        }
        .chat-input {
          flex: 1;
          border: 1px solid var(--divider-color, rgba(255,255,255,0.15));
          border-radius: 16px;
          padding: 8px 14px;
          font-size: 0.92rem;
          font-family: inherit;
          line-height: 1.35;
          outline: none;
          background: var(--secondary-background-color, rgba(255,255,255,0.05));
          color: var(--primary-text-color, #fff);
          transition: border-color 0.2s;
          resize: none;
          overflow: hidden;
          box-sizing: border-box;
          min-height: 52px;
          height: 52px;
          max-height: 140px;
        }
        .chat-input:focus {
          border-color: var(--primary-color, #03a9f4);
        }
        .chat-input::-webkit-scrollbar {
          width: 4px;
        }
        .chat-input::-webkit-scrollbar-thumb {
          background: rgba(255, 255, 255, 0.2);
          border-radius: 4px;
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
          flex-shrink: 0;
          margin-bottom: 7px;
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
            <button class="header-icon-btn" id="btn-config" title="${txtConfig}">
              <ha-icon icon="mdi:robot-happy-outline"></ha-icon>
            </button>
            <select class="agent-select" id="agent-select" title="${txtSelectModel}"></select>
          </div>
          <div class="header-actions">
            <div class="vision-badge" id="vision-badge"></div>
            <button class="icon-btn" id="btn-assist" title="${txtAssist}">
              <ha-icon icon="mdi:microphone"></ha-icon>
            </button>
            <button class="icon-btn" id="btn-reset" title="${txtReset}">
              <ha-icon icon="mdi:refresh"></ha-icon>
            </button>
          </div>
        </div>

        <div class="messages-container" id="messages-container"></div>

        <div class="image-preview-bar" id="image-preview-bar">
          <div class="preview-box">
            <img id="preview-img" src="" alt="Vista previa" />
            <button class="preview-remove-btn" id="btn-remove-image" title="${txtRemoveImg}">
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </div>
          <span class="preview-caption">${txtAttached}</span>
        </div>

        <div class="input-bar">
          <input type="file" id="file-input" accept="image/*" style="display: none;" />
          <button class="action-btn-attach" id="btn-attach" title="${txtAttach}">
            <ha-icon icon="mdi:paperclip"></ha-icon>
          </button>
          <textarea
            class="chat-input"
            id="chat-input"
            rows="1"
            placeholder="${txtPlaceholder}"
            autocomplete="off"
          ></textarea>
          <button class="action-btn" id="btn-send" title="${txtSend}">
            <ha-icon icon="mdi:send"></ha-icon>
          </button>
        </div>
      </ha-card>
    `;

    this._setupListeners();
    this._updateAgentDropdown();
    this._updateVisionBadge();
    this._updateMessagesView();
  }

  _setupListeners() {
    const input = this.shadowRoot.getElementById("chat-input");
    const sendBtn = this.shadowRoot.getElementById("btn-send");
    const resetBtn = this.shadowRoot.getElementById("btn-reset");
    const assistBtn = this.shadowRoot.getElementById("btn-assist");
    const agentSelect = this.shadowRoot.getElementById("agent-select");
    const attachBtn = this.shadowRoot.getElementById("btn-attach");
    const fileInput = this.shadowRoot.getElementById("file-input");
    const removeImgBtn = this.shadowRoot.getElementById("btn-remove-image");

    if (input && sendBtn) {
      const adjustHeight = () => {
        input.style.height = "auto";
        const newHeight = Math.min(input.scrollHeight, 140);
        input.style.height = `${Math.max(newHeight, 52)}px`;
        input.style.overflowY = input.scrollHeight > 140 ? "auto" : "hidden";
      };

      input.addEventListener("input", adjustHeight);

      const handleSend = () => {
        const text = input.value.trim();
        if ((text || this._attachedImage) && !this._isSending) {
          this._sendMessage(text);
          input.value = "";
          input.style.height = "52px";
          input.style.overflowY = "hidden";
        }
      };

      sendBtn.onclick = handleSend;
      input.onkeydown = (e) => {
        if (e.key === "Enter") {
          if (e.ctrlKey || e.shiftKey) {
            // Newline on Ctrl+Enter or Shift+Enter
            if (e.ctrlKey && !e.shiftKey) {
              e.preventDefault();
              const start = input.selectionStart;
              const end = input.selectionEnd;
              const val = input.value;
              input.value = val.substring(0, start) + "\n" + val.substring(end);
              input.selectionStart = input.selectionEnd = start + 1;
              adjustHeight();
            }
          } else {
            // Standard Enter sends message
            e.preventDefault();
            handleSend();
          }
        }
      };
    }

    // Attachment file input
    if (attachBtn && fileInput) {
      attachBtn.onclick = () => fileInput.click();
      fileInput.onchange = (e) => {
        const file = e.target.files && e.target.files[0];
        if (file) {
          const reader = new FileReader();
          reader.onload = (ev) => {
            this._setAttachedImage(ev.target.result);
          };
          reader.readAsDataURL(file);
        }
        fileInput.value = "";
      };
    }

    // Remove attached image
    if (removeImgBtn) {
      removeImgBtn.onclick = () => {
        this._setAttachedImage(null);
      };
    }

    // Paste image from clipboard (Ctrl+V) anywhere on input or card
    const handlePaste = (e) => {
      const items = (e.clipboardData || window.clipboardData)?.items;
      if (!items) return;
      for (let i = 0; i < items.length; i++) {
        if (items[i].type && items[i].type.startsWith("image/")) {
          e.preventDefault();
          const file = items[i].getAsFile();
          if (file) {
            const reader = new FileReader();
            reader.onload = (ev) => {
              this._setAttachedImage(ev.target.result);
            };
            reader.readAsDataURL(file);
          }
          break;
        }
      }
    };

    if (input) {
      input.addEventListener("paste", handlePaste);
    }
    const cardEl = this.shadowRoot.querySelector("ha-card");
    if (cardEl) {
      cardEl.addEventListener("paste", handlePaste);
    }

    if (agentSelect) {
      agentSelect.onchange = (e) => {
        this._selectedAgent = e.target.value;
        try {
          localStorage.setItem("nexus_mcp_selected_agent", this._selectedAgent);
        } catch (err) {
          console.warn("Could not save selected agent to localStorage:", err);
        }
        this._updateVisionBadge();
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

    const configBtn = this.shadowRoot.getElementById("btn-config");
    if (configBtn) {
      configBtn.onclick = () => {
        this._openConfiguration();
      };
    }
  }

  _setAttachedImage(dataUrl) {
    this._attachedImage = dataUrl;
    if (!this.shadowRoot) return;
    const previewBar = this.shadowRoot.getElementById("image-preview-bar");
    const previewImg = this.shadowRoot.getElementById("preview-img");
    if (previewBar && previewImg) {
      if (dataUrl) {
        previewImg.src = dataUrl;
        previewBar.classList.add("active");
      } else {
        previewImg.src = "";
        previewBar.classList.remove("active");
      }
    }
  }

  _agentHasVision(agentId) {
    if (!this._hass || !agentId) return false;
    const stateObj = this._hass.states[agentId];
    if (stateObj?.attributes?.has_vision !== undefined) {
      return Boolean(stateObj.attributes.has_vision);
    }
    const str = `${agentId} ${stateObj?.attributes?.friendly_name || ""}`.toLowerCase();
    if (str.includes("gpt-oss") || str.includes("120b") || str.includes("20b")) {
      return false;
    }
    const visionKeywords = [
      "vision", "-vl", "vl-", "_vl", "vl:", "/vl",
      "gemini", "gpt-4o", "omni", "claude-3", "qwen",
      "llava", "bakllava", "moondream", "minicpm",
      "pixtral", "paligemma", "cogvlm", "internvl",
      "glm-4v", "multimodal", "clip", "mllama"
    ];
    return visionKeywords.some((kw) => str.includes(kw));
  }

  _updateVisionBadge() {
    if (!this.shadowRoot) return;
    const badge = this.shadowRoot.getElementById("vision-badge");
    if (!badge) return;

    const hasVision = this._agentHasVision(this._selectedAgent);
    const isEs = this._isSpanish();

    badge.className = `vision-badge ${hasVision ? "has-vision" : "no-vision"}`;
    const iconName = hasVision ? "mdi:eye-outline" : "mdi:eye-off-outline";
    const label = hasVision ? (isEs ? "Visión" : "Vision") : (isEs ? "Texto" : "Text");
    const title = hasVision
      ? (isEs ? "Modelo con visión: admite análisis de imágenes" : "Vision model: supports image analysis")
      : (isEs ? "Modelo solo de texto: no admite imágenes" : "Text-only model: does not support images");

    badge.title = title;
    badge.innerHTML = `
      <ha-icon icon="${iconName}"></ha-icon>
      <span class="vision-badge-text">${label}</span>
    `;
  }

  _updateAgentDropdown() {
    if (!this.shadowRoot) return;
    const select = this.shadowRoot.getElementById("agent-select");
    if (!select) return;

    const isEs = this._isSpanish();
    const agents = this._getAvailableAgents();
    if (agents.length === 0) {
      select.innerHTML = `<option value="">${isEs ? "Buscando IAs..." : "Searching for AIs..."}</option>`;
      return;
    }

    let html = "";
    for (const ag of agents) {
      const isSelected = ag.id === this._selectedAgent ? "selected" : "";
      const hasVision = this._agentHasVision(ag.id);
      const prefix = hasVision ? "👁️ " : "";
      html += `<option value="${ag.id}" ${isSelected}>${prefix}${ag.name}</option>`;
    }
    select.innerHTML = html;
  }

  _formatContent(rawContent) {
    if (!rawContent) return "";

    let text = rawContent;

    // 1. If message ends with unclosed code block, auto-close it
    const backtickCount = (text.match(/```/g) || []).length;
    if (backtickCount % 2 !== 0) {
      text += "\n```";
    }

    // 2. Extract triple-backtick code blocks and protect them with placeholders
    const codeBlocks = [];
    const codeBlockRegex = /```([a-zA-Z0-9_\-\.\+]*)[^\S\r\n]*\r?\n?([\s\S]*?)```/g;
    text = text.replace(codeBlockRegex, (match, lang, code) => {
      const id = `__NEXUS_CODE_BLOCK_${codeBlocks.length}__`;
      codeBlocks.push({ lang: (lang || "yaml").trim(), code: code });
      return id;
    });

    // 3. Escape HTML on surrounding text
    text = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

    // 4. Convert markdown bold **text** to <strong>text</strong>
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

    // 5. Convert markdown inline code `code` to <code class="inline-code">
    text = text.replace(/`([^`\n]+)`/g, '<code class="inline-code">$1</code>');

    // 6. Reinsert formatted code boxes (using split/join to safely preserve all code content without $ escaping issues)
    codeBlocks.forEach((block, i) => {
      const placeholder = `__NEXUS_CODE_BLOCK_${i}__`;
      const cleanCode = block.code.trim();
      const escapedCode = cleanCode
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
      const langLabel = block.lang || "yaml";
      const isEs = this._isSpanish();
      const copyLabel = isEs ? "Copiar código" : "Copy code";
      const dataCode = encodeURIComponent(cleanCode);

      const boxHtml = `
        <div class="code-block-container">
          <div class="code-header">
            <span class="code-lang">${langLabel}</span>
            <button class="code-copy-btn" data-code="${dataCode}" title="${copyLabel}">
              <ha-icon icon="mdi:content-copy"></ha-icon>
              <span class="copy-text">${copyLabel}</span>
            </button>
          </div>
          <pre class="code-content"><code>${escapedCode}</code></pre>
        </div>
      `;
      text = text.split(placeholder).join(boxHtml);
    });

    return text;
  }

  _updateMessagesView(smooth = false) {
    if (!this.shadowRoot) return;
    const container = this.shadowRoot.getElementById("messages-container");
    if (!container) return;

    const isEs = this._isSpanish();

    if (this._messages.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <ha-icon icon="mdi:chat-outline"></ha-icon>
          <div>${isEs ? "Sin mensajes con esta IA." : "No messages with this AI yet."}</div>
          <small>${isEs ? "Escribe abajo, pega una imagen (Ctrl+V) o pulsa el micrófono." : "Type below, paste an image (Ctrl+V), or press the microphone."}</small>
        </div>
      `;
      return;
    }

    let html = "";
    this._messages.forEach((msg, idx) => {
      const isUser = msg.role === "user";
      const label = isUser ? (isEs ? "🧑 Tú" : "🧑 You") : "🤖 " + (msg.agent_name || (isEs ? "IA" : "AI"));
      const formattedContent = this._formatContent(msg.content || "");
      const imageHtml = msg.image
        ? `<img class="bubble-image" src="${msg.image}" alt="${isEs ? "Imagen adjunta" : "Attached image"}" />`
        : "";
      const copyTitle = isEs ? "Copiar texto al portapapeles" : "Copy text to clipboard";

      html += `
        <div class="message-bubble ${isUser ? "user" : "assistant"}">
          <div class="bubble-header">
            <div class="bubble-label">${label}</div>
            <button class="bubble-copy-btn" data-index="${idx}" title="${copyTitle}">
              <ha-icon icon="mdi:content-copy"></ha-icon>
            </button>
          </div>
          <div class="bubble-content">${imageHtml}${formattedContent}</div>
        </div>
      `;
    });

    container.innerHTML = html;
    this._scrollToBottom(smooth);

    // Ensure images triggering layout expansion keep the scroll anchored at bottom
    const images = container.querySelectorAll(".bubble-image");
    images.forEach((img) => {
      if (!img.complete) {
        img.addEventListener("load", () => this._scrollToBottom(smooth), { once: true });
      }
    });

    // Attach copy button click events for entire bubble
    const copyButtons = container.querySelectorAll(".bubble-copy-btn");
    copyButtons.forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.getAttribute("data-index"), 10);
        const msg = this._messages[idx];
        if (!msg) return;
        const textToCopy = msg.content || "";
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(textToCopy);
          } else {
            const textarea = document.createElement("textarea");
            textarea.value = textToCopy;
            textarea.style.position = "fixed";
            textarea.style.opacity = "0";
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand("copy");
            document.body.removeChild(textarea);
          }
          btn.classList.add("copied");
          btn.innerHTML = `<ha-icon icon="mdi:check"></ha-icon>`;
          setTimeout(() => {
            btn.classList.remove("copied");
            btn.innerHTML = `<ha-icon icon="mdi:content-copy"></ha-icon>`;
          }, 1800);
        } catch (err) {
          console.error("Nexus MCP Card: Failed to copy text:", err);
        }
      };
    });

    // Attach copy button click events for code blocks
    const codeButtons = container.querySelectorAll(".code-copy-btn");
    codeButtons.forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const rawCode = decodeURIComponent(btn.getAttribute("data-code") || "");
        if (!rawCode) return;
        const isEs = this._isSpanish();
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(rawCode);
          } else {
            const textarea = document.createElement("textarea");
            textarea.value = rawCode;
            textarea.style.position = "fixed";
            textarea.style.opacity = "0";
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand("copy");
            document.body.removeChild(textarea);
          }
          btn.classList.add("copied");
          btn.innerHTML = `<ha-icon icon="mdi:check"></ha-icon><span class="copy-text">${isEs ? "¡Copiado!" : "Copied!"}</span>`;
          setTimeout(() => {
            btn.classList.remove("copied");
            btn.innerHTML = `<ha-icon icon="mdi:content-copy"></ha-icon><span class="copy-text">${isEs ? "Copiar código" : "Copy code"}</span>`;
          }, 1800);
        } catch (err) {
          console.error("Nexus MCP Card: Failed to copy code:", err);
        }
      };
    });
  }

  async _sendMessage(text) {
    if (!this._hass || (!text && !this._attachedImage) || this._isSending) return;
    this._isSending = true;

    const agentId = this._selectedAgent;
    const agents = this._getAvailableAgents();
    const currentAgent = agents.find((a) => a.id === agentId);
    const agentName = currentAgent ? currentAgent.name : "Nexus MCP";

    const imageToSend = this._attachedImage;
    this._setAttachedImage(null);

    const messageText = text || (imageToSend ? "Analiza esta imagen adjunta." : "");

    // 1. Add user message
    this._messages.push({
      role: "user",
      content: messageText,
      image: imageToSend,
      timestamp: Date.now(),
    });
    this._saveHistoryForAgent(agentId);
    this._updateMessagesView(true);

    // 2. Add waiting bubble
    const container = this.shadowRoot.getElementById("messages-container");
    if (container) {
      const waitingBubble = document.createElement("div");
      waitingBubble.className = "message-bubble assistant waiting-bubble";
      waitingBubble.innerHTML = `
        <div class="bubble-header">
          <div class="bubble-label">🤖 ${agentName}</div>
        </div>
        <div class="bubble-content" style="font-style: italic; opacity: 0.7;">${imageToSend ? "Analizando imagen y pensando..." : "Pensando..."}</div>
      `;
      container.appendChild(waitingBubble);
      this._scrollToBottom(true);
    }

    const sendBtn = this.shadowRoot.getElementById("btn-send");
    if (sendBtn) sendBtn.disabled = true;

    try {
      const callWithTimeout = (promise, ms = 45000) =>
        Promise.race([
          promise,
          new Promise((_, reject) =>
            setTimeout(
              () =>
                reject(
                  new Error(
                    "Tiempo de espera agotado. El modelo o servidor tardó demasiado en responder."
                  )
                ),
              ms
            )
          ),
        ]);

      let reply = "";
      if (imageToSend) {
        // Direct call via custom multimodal WebSocket nexus_mcp/chat
        const payload = {
          type: "nexus_mcp/chat",
          text: messageText,
          image: imageToSend,
          agent_id: agentId,
          conversation_id: this._conversationId || undefined,
        };
        const res = await callWithTimeout(this._hass.callWS(payload), 50000);
        reply =
          res?.response?.speech?.plain?.speech ||
          res?.response?.card?.text ||
          "Imagen procesada correctamente.";
        if (res?.conversation_id) {
          this._conversationId = res.conversation_id;
        }
      } else {
        // Direct call via standard Home Assistant WebSocket conversation/process
        const payload = {
          type: "conversation/process",
          text: messageText,
        };
        if (agentId) {
          payload.agent_id = agentId;
        }
        if (this._conversationId) {
          payload.conversation_id = this._conversationId;
        }

        const res = await callWithTimeout(this._hass.callWS(payload), 45000);
        reply =
          res?.response?.speech?.plain?.speech ||
          res?.response?.card?.text ||
          "Comando procesado correctamente.";

        if (res?.conversation_id) {
          this._conversationId = res.conversation_id;
        }
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
      this._updateMessagesView(true);
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

  _openConfiguration() {
    // 1. Dispatch official Home Assistant navigation action
    const event = new CustomEvent("hass-action", {
      bubbles: true,
      composed: true,
      detail: {
        config: {
          tap_action: {
            action: "navigate",
            navigation_path: "/config/integrations/integration/nexus_mcp",
          },
        },
        action: "tap",
      },
    });
    this.dispatchEvent(event);

    // 2. Direct browser navigation fallback for single-page router
    try {
      window.history.pushState(null, "", "/config/integrations/integration/nexus_mcp");
      window.dispatchEvent(new CustomEvent("location-changed"));
    } catch (e) {
      window.location.href = "/config/integrations/integration/nexus_mcp";
    }
  }
}

class NexusMcpCardEditor extends HTMLElement {
  constructor() {
    super();
    this._config = {};
    this._hass = null;
  }

  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _isSpanish() {
    const lang = this._hass?.locale?.language || this._hass?.language || navigator.language || "en";
    return String(lang).toLowerCase().startsWith("es");
  }

  _render() {
    if (!this._hass || !this._config) return;

    const isEs = this._isSpanish();
    const agents = Object.keys(this._hass.states)
      .filter((e) => e.startsWith("conversation."))
      .map((id) => ({
        id,
        name: this._hass.states[id].attributes?.friendly_name || id,
      }));

    const autoLabel = isEs ? "(Automático / Selector en vivo)" : "(Automatic / Live Selector)";
    let optionsHtml = `<option value="">${autoLabel}</option>`;
    for (const ag of agents) {
      const isSel = this._config?.agent_id === ag.id ? "selected" : "";
      optionsHtml += `<option value="${ag.id}" ${isSel}>${ag.name}</option>`;
    }

    const titleLabel = isEs ? "Título de la tarjeta" : "Card Title";
    const agentLabel = isEs ? "IA / Agente predeterminado (Opcional)" : "Default AI / Agent (Optional)";
    const tipLabel = isEs
      ? "La tarjeta incluye un selector en su cabecera para cambiar de modelo de IA al vuelo."
      : "The card includes a live selector in its header to switch AI models on the fly.";

    this.innerHTML = `
      <div style="padding: 16px; display: flex; flex-direction: column; gap: 14px;">
        <label style="display: flex; flex-direction: column; gap: 4px; font-weight: 500;">
          ${titleLabel}
          <input
            type="text"
            id="cfg-title"
            value="${(this._config && this._config.title) || "Nexus MCP Intercom"}"
            style="padding: 8px 12px; border-radius: 6px; border: 1px solid var(--divider-color, #ccc);"
          />
        </label>
        <label style="display: flex; flex-direction: column; gap: 4px; font-weight: 500;">
          ${agentLabel}
          <select id="cfg-agent" style="padding: 8px 12px; border-radius: 6px; border: 1px solid var(--divider-color, #ccc);">
            ${optionsHtml}
          </select>
        </label>
        <small style="color: var(--secondary-text-color, #666);">
          ${tipLabel}
        </small>
      </div>
    `;

    const titleInput = this.querySelector("#cfg-title");
    const agentSelect = this.querySelector("#cfg-agent");

    const handleChange = () => {
      const newConfig = {
        ...this._config,
        title: titleInput ? titleInput.value : (this._config.title || "Nexus MCP Intercom"),
        agent_id: agentSelect && agentSelect.value ? agentSelect.value : undefined,
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
  "%c NEXUS MCP CARD %c v1.3.2 Auto-Scroll & Synced History Ready ",
  "color: white; background: #03a9f4; font-weight: bold; padding: 2px 6px; border-radius: 4px 0 0 4px;",
  "color: #03a9f4; background: #e1f5fe; font-weight: bold; padding: 2px 6px; border-radius: 0 4px 4px 0;"
);
