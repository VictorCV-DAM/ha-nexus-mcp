/**
 * Nexus MCP Plug & Play Card for Home Assistant (v1.6.7)
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

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
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
    this._aborted = false;
    this._queryCounter = 0;
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
    if (!this.shadowRoot || !this.shadowRoot.innerHTML) {
      this._render();
    } else {
      this._updateTranslations();
      this._updateVisionBadge();
    }
  }

  connectedCallback() {
    this._updateTranslations();
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

    if (!this._cachedLovelaceConfig && hass) {
      this._loadDashboardConfig();
    }

    if (!oldHass || oldHass.language !== hass.language || oldHass.locale?.language !== hass.locale?.language) {
      this._updateTranslations();
      this._updateAgentDropdown();
      this._updateVisionBadge();
      if (!oldHass && this._selectedAgent) {
        this._loadHistoryForAgent(this._selectedAgent);
      }
      this._updateMessagesView();
    }
  }

  async _loadDashboardConfig() {
    if (!this._hass) return;
    const pathname = window.location.pathname || "";
    const pathParts = pathname.split("/").filter(Boolean);
    let urlPath = (pathParts.length > 0 && pathParts[0] !== "lovelace") ? pathParts[0] : null;
    try {
      let res = await this._hass.callWS({ type: "lovelace/config", url_path: urlPath });
      if (!res || !Array.isArray(res.views) || res.views.length === 0) {
        res = await this._hass.callWS({ type: "lovelace/config", url_path: "mi-casa" });
      }
      if (res && Array.isArray(res.views)) {
        this._cachedLovelaceConfig = res;
      }
    } catch (_) {}
  }

  _tokenize(str) {
    if (!str) return [];
    const clean = String(str).toLowerCase().replace(/[_.\-]/g, " ");
    const stopWords = new Set(["el", "la", "los", "las", "de", "del", "un", "una", "en", "para", "por", "con", "al", "the", "a", "an", "and", "or"]);
    return clean.split(/\s+/).filter(w => w.length >= 2 && !stopWords.has(w));
  }

  _isFuzzyMatch(target, candidate) {
    if (!target || !candidate) return false;
    const t = String(target).trim().toLowerCase();
    const c = String(candidate).trim().toLowerCase();
    if (t === c || t.includes(c) || c.includes(t)) return true;
    const tTokens = this._tokenize(t);
    const cTokens = this._tokenize(c);
    if (tTokens.length === 0 || cTokens.length === 0) return false;
    const cSet = new Set(cTokens);
    const common = tTokens.filter(tok => cSet.has(tok));
    if (common.length === tTokens.length || common.length === cTokens.length) return true;
    const ratio = common.length / Math.min(tTokens.length, cTokens.length);
    return common.length >= 2 && ratio >= 0.5;
  }

  _checkResourceExists(resType, cleanCode) {
    if (!this._hass) return false;
    const states = this._hass.states || {};

    if (resType === "helper") {
      const HELPER_DOMAINS = [
        "input_boolean", "input_number", "input_select", "input_text",
        "input_datetime", "input_button", "counter", "timer", "schedule"
      ];
      let foundDomain = null;
      let slug = null;
      for (const hd of HELPER_DOMAINS) {
        const domainRegex = new RegExp(`(?:^|\\n)\\s*${hd}:(?:\\s*\\n\\s*([a-z0-9_]+):)?`, "i");
        const m = cleanCode.match(domainRegex);
        if (m) {
          foundDomain = hd;
          if (m[1]) slug = m[1].trim().toLowerCase();
          break;
        }
      }
      if (!foundDomain) {
        const typeMatch = cleanCode.match(/(?:type|domain|platform):\s*['"]?([a-z0-9_]+)['"]?/i);
        if (typeMatch && HELPER_DOMAINS.includes(typeMatch[1].toLowerCase())) {
          foundDomain = typeMatch[1].toLowerCase();
        }
      }
      if (!foundDomain) return false;

      // Check explicit entity_id
      const entMatch = cleanCode.match(/entity_id:\s*['"]?([a-z0-9_]+\.[a-z0-9_]+)['"]?/i);
      if (entMatch && states[entMatch[1].toLowerCase()]) return true;

      // Check target slug
      const idMatch = cleanCode.match(/(?:^|\n)\s*(?:id|helper_id):\s*['"]?([a-z0-9_]+)['"]?/i);
      const targetSlug = slug || (idMatch ? idMatch[1].trim().toLowerCase() : null);
      if (targetSlug && states[`${foundDomain}.${targetSlug}`]) return true;

      // Check by friendly_name and slug with fuzzy match
      const nameMatch = cleanCode.match(/(?:^|\n)\s*name:\s*['"]?([^'"\n]+)['"]?/i);
      const targetName = nameMatch ? nameMatch[1].trim() : null;

      for (const entityId in states) {
        if (entityId.startsWith(`${foundDomain}.`)) {
          const fn = states[entityId]?.attributes?.friendly_name;
          const eSlug = entityId.substring(foundDomain.length + 1);
          if (targetName && fn && this._isFuzzyMatch(targetName, fn)) return true;
          if (targetSlug && (eSlug === targetSlug || this._isFuzzyMatch(targetSlug, eSlug))) return true;
          if (targetName && this._isFuzzyMatch(targetName, eSlug)) return true;
        }
      }

      // Check session memory of recently created entities
      if (Array.isArray(this._lastCreatedEntities)) {
        for (const created of this._lastCreatedEntities) {
          if (created.domain === foundDomain) {
            if (targetSlug && (created.id === targetSlug || this._isFuzzyMatch(targetSlug, created.id))) return true;
            if (targetName && (created.name === targetName || this._isFuzzyMatch(targetName, created.name))) return true;
          }
        }
      }

      return false;
    }

    if (resType === "automation") {
      const idMatch = cleanCode.match(/(?:^|\n)\s*id:\s*['"]?([^'"\n]+)['"]?/i);
      const autoId = idMatch ? idMatch[1].trim() : null;
      if (autoId) {
        if (states[`automation.${autoId}`]) return true;
        for (const eid in states) {
          if (eid.startsWith("automation.")) {
            if (states[eid]?.attributes?.id === autoId) return true;
          }
        }
      }

      const aliasMatch = cleanCode.match(/(?:^|\n)\s*alias:\s*['"]?([^'"\n]+)['"]?/i);
      const targetAlias = aliasMatch ? aliasMatch[1].trim() : null;
      for (const eid in states) {
        if (eid.startsWith("automation.")) {
          const fn = states[eid]?.attributes?.friendly_name;
          const aId = states[eid]?.attributes?.id;
          if (autoId && (eid === `automation.${autoId}` || aId === autoId || this._isFuzzyMatch(autoId, eid.substring(11)))) return true;
          if (targetAlias && fn && this._isFuzzyMatch(targetAlias, fn)) return true;
        }
      }
      return false;
    }

    if (resType === "script") {
      const slugMatch = cleanCode.match(/(?:^|\n)\s*script:\s*\n\s*([a-z0-9_]+):/i);
      const idMatch = cleanCode.match(/(?:^|\n)\s*id:\s*['"]?([^'"\n]+)['"]?/i);
      const targetSlug = (slugMatch && slugMatch[1]) || (idMatch && idMatch[1]);
      if (targetSlug && states[`script.${targetSlug.trim().toLowerCase()}`]) return true;

      const aliasMatch = cleanCode.match(/(?:^|\n)\s*alias:\s*['"]?([^'"\n]+)['"]?/i);
      const targetAlias = aliasMatch ? aliasMatch[1].trim() : null;
      for (const eid in states) {
        if (eid.startsWith("script.")) {
          const fn = states[eid]?.attributes?.friendly_name;
          const sSlug = eid.substring(7);
          if (targetSlug && (sSlug === targetSlug || this._isFuzzyMatch(targetSlug, sSlug))) return true;
          if (targetAlias && fn && this._isFuzzyMatch(targetAlias, fn)) return true;
        }
      }
      return false;
    }

    if (resType === "scene") {
      const slugMatch = cleanCode.match(/(?:^|\n)\s*scene:\s*\n\s*([a-z0-9_]+):/i);
      const idMatch = cleanCode.match(/(?:^|\n)\s*id:\s*['"]?([^'"\n]+)['"]?/i);
      const targetSlug = (slugMatch && slugMatch[1]) || (idMatch && idMatch[1]);
      if (targetSlug && states[`scene.${targetSlug.trim().toLowerCase()}`]) return true;

      const nameMatch = cleanCode.match(/(?:^|\n)\s*name:\s*['"]?([^'"\n]+)['"]?/i);
      const targetName = nameMatch ? nameMatch[1].trim() : null;
      for (const eid in states) {
        if (eid.startsWith("scene.")) {
          const fn = states[eid]?.attributes?.friendly_name;
          const sSlug = eid.substring(6);
          if (targetSlug && (sSlug === targetSlug || this._isFuzzyMatch(targetSlug, sSlug))) return true;
          if (targetName && fn && this._isFuzzyMatch(targetName, fn)) return true;
        }
      }
      return false;
    }

    if (resType === "card") {
      if (this._cachedLovelaceConfig && Array.isArray(this._cachedLovelaceConfig.views)) {
        const entMatches = cleanCode.matchAll(/[a-z0-9_]+\.[a-z0-9_]+/gi);
        const cardEnts = new Set();
        for (const m of entMatches) {
          cardEnts.add(m[0].toLowerCase());
          cardEnts.add(m[0].toLowerCase().replace(/_local$/, ""));
        }
        const nameMatch = cleanCode.match(/(?:^|\n)\s*(?:title|name):\s*['"]?([^'"\n]+)['"]?/i);
        const cardTitle = nameMatch ? nameMatch[1].trim().toLowerCase() : "";

        for (const v of this._cachedLovelaceConfig.views) {
          let vCards = Array.isArray(v.cards) ? [...v.cards] : [];
          if (Array.isArray(v.sections)) {
            for (const s of v.sections) {
              if (Array.isArray(s.cards)) vCards.push(...s.cards);
            }
          }
          for (const c of vCards) {
            if (!c || typeof c !== "object") continue;
            const cDump = JSON.stringify(c).toLowerCase();
            for (const ent of cardEnts) {
              if (cDump.includes(ent)) return true;
            }
            if (cardTitle && cardTitle.length >= 4) {
              const cTitle = (c.title || c.name || "").trim().toLowerCase();
              if (cTitle && (cTitle === cardTitle || cTitle.includes(cardTitle) || cardTitle.includes(cTitle))) {
                return true;
              }
            }
          }
        }
      }
      return false;
    }

    return false;
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
    if (this._config && this._config.language) {
      return this._config.language === "es";
    }
    const haObj = this._hass || document.querySelector("home-assistant")?.hass;
    const lang = String(
      haObj?.locale?.language ||
      haObj?.language ||
      haObj?.selectedLanguage ||
      navigator.language ||
      "en"
    ).toLowerCase();
    return lang.startsWith("es");
  }

  _updateSendButtonState() {
    if (!this.shadowRoot) return;
    const sendBtn = this.shadowRoot.getElementById("btn-send");
    if (!sendBtn) return;
    const isEs = this._isSpanish();

    if (this._isSending) {
      sendBtn.disabled = false;
      sendBtn.classList.add("btn-stop");
      sendBtn.title = isEs ? "Detener consulta (Esc)" : "Stop query (Esc)";
      sendBtn.innerHTML = `<ha-icon icon="mdi:stop"></ha-icon>`;
    } else {
      sendBtn.disabled = false;
      sendBtn.classList.remove("btn-stop");
      sendBtn.title = isEs ? "Enviar" : "Send";
      sendBtn.innerHTML = `<ha-icon icon="mdi:send"></ha-icon>`;
    }
  }

  _stopGeneration() {
    if (!this._isSending) return;
    this._aborted = true;
    this._isSending = false;

    // Remove any waiting bubble in DOM
    const container = this.shadowRoot?.getElementById("messages-container");
    if (container) {
      const waiting = container.querySelector(".waiting-bubble");
      if (waiting) waiting.remove();
    }

    const isEs = this._isSpanish();
    const agents = this._getAvailableAgents();
    const currentAgent = agents.find((a) => a.id === this._selectedAgent);
    const agentName = currentAgent ? currentAgent.name : "Nexus MCP";

    this._messages.push({
      role: "assistant",
      agent_name: agentName,
      content: isEs ? "⏹️ *Consulta detenida por el usuario.*" : "⏹️ *Query stopped by user.*",
      timestamp: Date.now(),
    });
    this._saveHistoryForAgent(this._selectedAgent);

    this._updateSendButtonState();
    this._updateMessagesView(true);
  }

  _updateTranslations() {
    if (!this.shadowRoot) return;
    const isEs = this._isSpanish();

    const input = this.shadowRoot.getElementById("chat-input");
    if (input) {
      input.placeholder = isEs
        ? "Escribe un mensaje o pega una imagen (Ctrl+V)..."
        : "Type a message or paste an image (Ctrl+V)...";
    }

    const sendBtn = this.shadowRoot.getElementById("btn-send");
    if (sendBtn) {
      if (this._isSending) {
        sendBtn.title = isEs ? "Detener consulta (Esc)" : "Stop query (Esc)";
      } else {
        sendBtn.title = isEs ? "Enviar" : "Send";
      }
    }

    const resetBtn = this.shadowRoot.getElementById("btn-reset");
    if (resetBtn) {
      resetBtn.title = isEs ? "Reiniciar Conversación" : "Reset Conversation";
    }

    const assistBtn = this.shadowRoot.getElementById("btn-assist");
    if (assistBtn) {
      assistBtn.title = isEs ? "Abrir Assist / Voz" : "Open Assist / Voice";
    }

    const attachBtn = this.shadowRoot.getElementById("btn-attach");
    if (attachBtn) {
      attachBtn.title = isEs
        ? "Adjuntar imagen (o pega con Ctrl+V)"
        : "Attach image (or paste with Ctrl+V)";
    }

    const removeImgBtn = this.shadowRoot.getElementById("btn-remove-image");
    if (removeImgBtn) {
      removeImgBtn.title = isEs ? "Eliminar imagen" : "Remove image";
    }

    const agentSelect = this.shadowRoot.getElementById("agent-select");
    if (agentSelect) {
      agentSelect.title = isEs ? "Seleccionar IA / Modelo" : "Select AI / Model";
    }

    const previewCaption = this.shadowRoot.querySelector(".preview-caption");
    if (previewCaption) {
      previewCaption.textContent = isEs
        ? "Imagen adjunta (lista para enviar)"
        : "Attached image (ready to send)";
    }
  }

  _render() {
    if (!this.shadowRoot) return;

    const isEs = this._isSpanish();
    const txtConfig = isEs ? "Configurar Nexus MCP" : "Configure Nexus MCP";
    const txtSelectModel = isEs ? "Seleccionar IA / Modelo" : "Select AI / Model";
    const txtAssist = isEs ? "Abrir Assist / Voz" : "Open Assist / Voice";
    const txtQuickReload = isEs ? "Recarga rápida de Home Assistant" : "Quick reload Home Assistant";
    const txtUndo = isEs ? "Deshacer último cambio" : "Undo last change";
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
        .icon-btn#btn-header-undo {
          transition: all 0.25s ease;
        }
        .icon-btn#btn-header-undo.has-backup {
          color: #ffb74d !important;
          background: rgba(255, 152, 0, 0.18) !important;
          border: 1px solid rgba(255, 152, 0, 0.55);
          box-shadow: 0 0 10px rgba(255, 152, 0, 0.35);
          animation: pulse-undo 2.2s infinite ease-in-out;
        }
        @keyframes pulse-undo {
          0%, 100% { transform: scale(1); box-shadow: 0 0 4px rgba(255, 152, 0, 0.2); }
          50% { transform: scale(1.08); box-shadow: 0 0 12px rgba(255, 152, 0, 0.6); }
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
        .code-actions {
          display: inline-flex;
          align-items: center;
          gap: 6px;
        }
        .bubble-automation-footer {
          margin-top: 14px;
          padding-top: 10px;
          border-top: 1px dashed var(--divider-color, rgba(255, 255, 255, 0.15));
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .code-save-auto-btn,
        .code-save-helper-btn,
        .code-save-script-btn,
        .code-save-scene-btn,
        .code-save-card-btn {
          background: linear-gradient(135deg, #1976d2 0%, #0288d1 100%);
          border: none;
          color: #ffffff;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          font-size: 0.88rem;
          font-weight: 600;
          padding: 10px 16px;
          border-radius: 8px;
          transition: all 0.2s ease;
          box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
          width: 100%;
          box-sizing: border-box;
        }
        .code-save-helper-btn {
          background: linear-gradient(135deg, #7b1fa2 0%, #9c27b0 100%);
        }
        .code-save-script-btn {
          background: linear-gradient(135deg, #00796b 0%, #009688 100%);
        }
        .code-save-scene-btn {
          background: linear-gradient(135deg, #e65100 0%, #f57c00 100%);
        }
        .code-save-card-btn {
          background: linear-gradient(135deg, #00838f 0%, #00acc1 100%);
        }
        .code-save-auto-btn:hover:not(:disabled),
        .code-save-helper-btn:hover:not(:disabled),
        .code-save-script-btn:hover:not(:disabled),
        .code-save-scene-btn:hover:not(:disabled),
        .code-save-card-btn:hover:not(:disabled) {
          filter: brightness(1.15);
          transform: translateY(-1px);
          box-shadow: 0 4px 10px rgba(0, 0, 0, 0.35);
        }
        .code-save-auto-btn:active:not(:disabled),
        .code-save-helper-btn:active:not(:disabled),
        .code-save-script-btn:active:not(:disabled),
        .code-save-scene-btn:active:not(:disabled),
        .code-save-card-btn:active:not(:disabled) {
          transform: translateY(0);
        }
        .code-save-auto-btn ha-icon,
        .code-save-helper-btn ha-icon,
        .code-save-script-btn ha-icon,
        .code-save-scene-btn ha-icon,
        .code-save-card-btn ha-icon {
          --mdc-icon-size: 20px;
          color: #ffca28;
          display: inline-flex;
          align-items: center;
          justify-content: center;
        }
        .code-save-helper-btn ha-icon {
          color: #e1bee7;
        }
        .code-save-script-btn ha-icon {
          color: #b2dfdb;
        }
        .code-save-scene-btn ha-icon {
          color: #ffe0b2;
        }
        .code-save-card-btn ha-icon {
          color: #b2ebf2;
        }
        .code-save-auto-btn.saved ha-icon,
        .code-save-auto-btn.error ha-icon,
        .code-save-helper-btn.saved ha-icon,
        .code-save-helper-btn.error ha-icon,
        .code-save-script-btn.saved ha-icon,
        .code-save-script-btn.error ha-icon,
        .code-save-scene-btn.saved ha-icon,
        .code-save-scene-btn.error ha-icon,
        .code-save-card-btn.saved ha-icon,
        .code-save-card-btn.error ha-icon {
          color: #ffffff;
        }
        .code-save-auto-btn.saved,
        .code-save-helper-btn.saved,
        .code-save-script-btn.saved,
        .code-save-scene-btn.saved,
        .code-save-card-btn.saved {
          background: #2e7d32 !important;
          color: #ffffff !important;
          cursor: default;
        }
        .code-action-btn.error {
          background: #c62828 !important;
          color: #ffffff !important;
        }
        .code-action-btn .btn-text {
          white-space: normal;
          line-height: 1.25;
          max-height: 2.8em;
          overflow: hidden;
          text-overflow: ellipsis;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
        }
        .code-revert-btn {
          background: linear-gradient(135deg, #b71c1c 0%, #7f0000 100%);
          border: 1px solid rgba(239, 83, 80, 0.4);
          color: #ffffff;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          font-size: 0.86rem;
          font-weight: 600;
          padding: 9px 14px;
          border-radius: 8px;
          transition: all 0.2s ease;
          box-shadow: 0 2px 6px rgba(183, 28, 28, 0.35);
          width: 100%;
          box-sizing: border-box;
          margin-top: 4px;
        }
        .code-revert-btn:hover:not(:disabled) {
          background: linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%);
          border-color: #ef5350;
          transform: translateY(-1px);
          box-shadow: 0 4px 10px rgba(183, 28, 28, 0.5);
        }
        .code-revert-btn:active:not(:disabled) {
          transform: translateY(0);
        }
        .code-revert-btn ha-icon {
          --mdc-icon-size: 18px;
          color: #ffcdd2;
          display: inline-flex;
          align-items: center;
          justify-content: center;
        }
        .code-actions-group {
          display: flex;
          flex-direction: column;
          gap: 6px;
          width: 100%;
        }
        .code-action-btn {
          border: none;
          color: #ffffff;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          font-size: 0.88rem;
          font-weight: 600;
          padding: 10px 16px;
          border-radius: 8px;
          transition: all 0.2s ease;
          box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
          width: 100%;
          box-sizing: border-box;
        }
        .code-save-update-btn {
          background: linear-gradient(135deg, #00838f 0%, #00acc1 100%);
        }
        .code-save-new-btn {
          background: linear-gradient(135deg, #1976d2 0%, #0288d1 100%);
        }
        .code-action-btn:hover:not(:disabled) {
          filter: brightness(1.15);
          transform: translateY(-1px);
          box-shadow: 0 4px 10px rgba(0, 0, 0, 0.35);
        }
        .code-action-btn:active:not(:disabled) {
          transform: translateY(0);
        }
        .code-action-btn ha-icon {
          --mdc-icon-size: 20px;
          color: #ffffff;
          display: inline-flex;
          align-items: center;
          justify-content: center;
        }
        .code-success-banner {
          background: rgba(46, 125, 50, 0.2);
          border: 1px solid #4caf50;
          color: #81c784;
          padding: 10px 14px;
          border-radius: 8px;
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.88rem;
          font-weight: 600;
          width: 100%;
          box-sizing: border-box;
        }
        .code-success-banner ha-icon {
          --mdc-icon-size: 20px;
          color: #81c784;
        }
        .code-copy-btn {
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
        .action-btn.btn-stop {
          background: var(--error-color, #e53935) !important;
          color: #ffffff !important;
          animation: pulse-stop 1.2s infinite ease-in-out;
        }
        @keyframes pulse-stop {
          0% { transform: scale(1); }
          50% { transform: scale(1.08); }
          100% { transform: scale(1); }
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
            <button class="icon-btn" id="btn-header-undo" title="${txtUndo}">
              <ha-icon icon="mdi:undo-variant"></ha-icon>
            </button>
            <div class="vision-badge" id="vision-badge"></div>
            <button class="icon-btn" id="btn-quick-reload" title="${txtQuickReload}">
              <ha-icon icon="mdi:lightning-bolt-outline"></ha-icon>
            </button>
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

      const handleSendOrStop = () => {
        if (this._isSending) {
          this._stopGeneration();
          return;
        }
        const text = input.value.trim();
        if (text || this._attachedImage) {
          this._sendMessage(text);
          input.value = "";
          input.style.height = "52px";
          input.style.overflowY = "hidden";
        }
      };

      sendBtn.onclick = handleSendOrStop;
      input.onkeydown = (e) => {
        if (e.key === "Escape" && this._isSending) {
          e.preventDefault();
          this._stopGeneration();
          return;
        }
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
            // Standard Enter sends message or stops
            e.preventDefault();
            handleSendOrStop();
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

    const quickReloadBtn = this.shadowRoot.getElementById("btn-quick-reload");
    if (quickReloadBtn) {
      quickReloadBtn.onclick = () => {
        this._handleQuickReload();
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

    const headerUndoBtn = this.shadowRoot.getElementById("btn-header-undo");
    if (headerUndoBtn) {
      headerUndoBtn.onclick = () => {
        this._revertLastBackup();
      };
    }
    this._updateHeaderUndoState();
  }

  _updateHeaderUndoState() {
    if (!this.shadowRoot) return;
    const undoBtn = this.shadowRoot.getElementById("btn-header-undo");
    if (!undoBtn) return;
    const isEs = this._isSpanish();
    const rawBackup = localStorage.getItem("nexus_last_backup");
    if (rawBackup) {
      undoBtn.disabled = false;
      undoBtn.classList.add("has-backup");
      undoBtn.title = isEs ? "↩️ Deshacer / Revertir último cambio realizado" : "↩️ Undo / Revert last change";
      undoBtn.style.opacity = "1";
      undoBtn.style.cursor = "pointer";
      undoBtn.style.pointerEvents = "auto";
    } else {
      undoBtn.disabled = true;
      undoBtn.classList.remove("has-backup");
      undoBtn.title = isEs ? "Deshacer (inactivo: no hay cambios pendientes)" : "Undo (inactive: no pending changes)";
      undoBtn.style.opacity = "0.35";
      undoBtn.style.cursor = "not-allowed";
      undoBtn.style.pointerEvents = "none";
    }
  }

  async _revertLastBackup(sourceBtn = null) {
    const isEs = this._isSpanish();
    const rawBackup = localStorage.getItem("nexus_last_backup");
    if (!rawBackup) {
      alert(isEs ? "No hay ningún cambio previo guardado para revertir en esta sesión." : "No previous changes saved to revert in this session.");
      return;
    }

    let textSpan = null;
    let allGroupBtns = [];
    if (sourceBtn) {
      const btnGroup = sourceBtn.closest(".code-actions-group") || sourceBtn.parentNode;
      allGroupBtns = btnGroup ? btnGroup.querySelectorAll(".code-action-btn") : [sourceBtn];
      allGroupBtns.forEach((b) => (b.disabled = true));
      textSpan = sourceBtn.querySelector(".btn-text");
      if (textSpan) textSpan.textContent = isEs ? "Revirtiendo..." : "Reverting...";
    }

    try {
      const backupObj = JSON.parse(rawBackup);
      if (backupObj.type === "card" && backupObj.config) {
        await this._hass.callWS({
          type: "lovelace/config/save",
          url_path: backupObj.urlPath || null,
          config: backupObj.config,
        });
      } else if (backupObj.type === "helper" && backupObj.helperId) {
        if (backupObj.prevAttributes) {
          await this._hass.callWS({
            type: `${backupObj.helperDomain}/update`,
            [`${backupObj.helperDomain}_id`]: backupObj.helperId,
            ...backupObj.prevAttributes,
          });
        } else {
          await this._hass.callWS({
            type: `${backupObj.helperDomain}/delete`,
            [`${backupObj.helperDomain}_id`]: backupObj.helperId,
          });
        }
      } else if (backupObj.type === "automation" && backupObj.autoId) {
        if (backupObj.prevConfig) {
          await this._hass.callApi("POST", `config/automation/config/${backupObj.autoId}`, backupObj.prevConfig);
        } else {
          await this._hass.callApi("DELETE", `config/automation/config/${backupObj.autoId}`);
        }
      } else if (backupObj.type === "script" && backupObj.scriptId) {
        if (backupObj.prevConfig) {
          await this._hass.callApi("POST", `config/script/config/${backupObj.scriptId}`, backupObj.prevConfig);
        } else {
          await this._hass.callApi("DELETE", `config/script/config/${backupObj.scriptId}`);
        }
      } else if (backupObj.type === "scene" && backupObj.sceneId) {
        if (backupObj.prevConfig) {
          await this._hass.callApi("POST", `config/scene/config/${backupObj.sceneId}`, backupObj.prevConfig);
        } else {
          await this._hass.callApi("DELETE", `config/scene/config/${backupObj.sceneId}`);
        }
      }

      localStorage.removeItem("nexus_last_backup");
      this._updateHeaderUndoState();

      if (sourceBtn) {
        const btnGroup = sourceBtn.closest(".code-actions-group") || sourceBtn.parentNode;
        if (btnGroup) {
          btnGroup.innerHTML = `
            <div class="code-success-banner" style="background: rgba(33, 150, 243, 0.2); border-color: #2196f3; color: #64b5f6;">
              <ha-icon icon="mdi:undo-variant"></ha-icon>
              <span>${isEs ? "↩️ ¡Último cambio revertido y estado anterior restaurado con éxito!" : "↩️ Last change reverted and restored successfully!"}</span>
            </div>
          `;
        }
      } else {
        alert(isEs ? "↩️ ¡Último cambio revertido y estado anterior restaurado con éxito!" : "↩️ Last change reverted and restored successfully!");
      }
    } catch (rErr) {
      console.error("Nexus MCP Card: Revert failed:", rErr);
      if (sourceBtn) {
        allGroupBtns.forEach((b) => (b.disabled = false));
        const errMsg = (rErr && (rErr.message || rErr.error)) || (isEs ? "Error al revertir" : "Error reverting");
        if (textSpan) textSpan.textContent = errMsg;
      }
      alert((isEs ? "Error al revertir: " : "Error reverting: ") + ((rErr && (rErr.message || rErr.error)) || rErr));
    }
  }

  async _handleQuickReload() {
    const btn = this.shadowRoot?.getElementById("btn-quick-reload");
    if (!btn || !this._hass || this._isReloading) return;

    this._isReloading = true;
    btn.disabled = true;
    btn.style.opacity = "0.5";
    const icon = btn.querySelector("ha-icon");
    if (icon) icon.icon = "mdi:loading";

    try {
      await this._hass.callService("homeassistant", "reload_all");
      if (icon) icon.icon = "mdi:check";
      btn.style.color = "var(--success-color, #4caf50)";
      setTimeout(() => {
        if (icon) icon.icon = "mdi:lightning-bolt-outline";
        btn.style.color = "";
        btn.style.opacity = "";
        btn.disabled = false;
        this._isReloading = false;
      }, 2000);
    } catch (err) {
      console.error("Nexus MCP: Quick Reload failed:", err);
      if (icon) icon.icon = "mdi:alert-circle-outline";
      btn.style.color = "var(--error-color, #f44336)";
      setTimeout(() => {
        if (icon) icon.icon = "mdi:lightning-bolt-outline";
        btn.style.color = "";
        btn.style.opacity = "";
        btn.disabled = false;
        this._isReloading = false;
      }, 2500);
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
      html += `<option value="${escapeHtml(ag.id)}" ${isSelected}>${prefix}${escapeHtml(ag.name)}</option>`;
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

    // 6. Reinsert formatted code boxes and generate explicit dual-action buttons (Update vs Add)
    const detectedResources = [];
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

      const normLang = (langLabel || "").toLowerCase();
      const isYaml = !normLang || normLang === "yaml" || normLang === "yml" || normLang === "ha" || normLang === "homeassistant";

      const HELPER_DOMAINS = [
        "input_boolean", "input_number", "input_select", "input_text",
        "input_datetime", "input_button", "counter", "timer", "schedule"
      ];
      const isHelper = isYaml && HELPER_DOMAINS.some((hd) =>
        cleanCode.includes(`${hd}:`) || cleanCode.includes(`type: ${hd}`) || cleanCode.includes(`domain: ${hd}`)
      );

      const CARD_TYPES = [
        "tile", "entities", "entity", "glance", "button", "gauge", "markdown",
        "thermostat", "weather-forecast", "light", "alarm-panel", "picture",
        "picture-elements", "picture-entity", "picture-glance", "history-graph",
        "statistics-graph", "logbook", "media-control", "map", "iframe",
        "grid", "vertical-stack", "horizontal-stack", "area", "sensor"
      ];
      const isCard = isYaml && !isHelper && (
        CARD_TYPES.some((ct) => cleanCode.includes(`type: ${ct}`) || cleanCode.includes(`type: '${ct}'`) || cleanCode.includes(`type: "${ct}"`)) ||
        cleanCode.includes("type: custom:") ||
        cleanCode.includes("-card") ||
        cleanCode.includes("chips:") ||
        (cleanCode.includes("type:") && !cleanCode.includes("sequence:") && (cleanCode.includes("entity:") || cleanCode.includes("entities:") || cleanCode.includes("cards:") || cleanCode.includes("card:")))
      );

      const hasTrigger = cleanCode.includes("trigger:") || cleanCode.includes("triggers:") || cleanCode.includes("platform:");
      const hasAction = cleanCode.includes("action:") || cleanCode.includes("actions:") || cleanCode.includes("service:");
      const isAutomation = isYaml && !isHelper && !isCard && hasTrigger && hasAction;

      const isScript = isYaml && !isHelper && !isCard && !isAutomation && (
        cleanCode.includes("sequence:") || cleanCode.includes("script:") || (hasAction && !hasTrigger)
      );

      const isScene = isYaml && !isHelper && !isCard && !isAutomation && !isScript && (
        cleanCode.includes("scene:") || (cleanCode.includes("entities:") && !hasTrigger && !cleanCode.includes("sequence:"))
      );

      let resType = null;
      if (isCard) resType = "card";
      else if (isHelper) resType = "helper";
      else if (isAutomation) resType = "automation";
      else if (isScript) resType = "script";
      else if (isScene) resType = "scene";

      if (resType) {
        detectedResources.push({ type: resType, code: cleanCode });
      }

      const boxHtml = `
        <div class="code-block-container">
          <div class="code-header">
            <span class="code-lang">${langLabel}</span>
            <div class="code-actions">
              <button class="code-copy-btn" data-code="${dataCode}" title="${copyLabel}">
                <ha-icon icon="mdi:content-copy"></ha-icon>
                <span class="copy-text">${copyLabel}</span>
              </button>
            </div>
          </div>
          <pre class="code-content"><code>${escapedCode}</code></pre>
        </div>
      `;
      text = text.split(placeholder).join(boxHtml);
    });

    if (detectedResources.length > 0) {
      const isEs = this._isSpanish();
      let footerHtml = `<div class="bubble-automation-footer">`;
      detectedResources.forEach((resItem, idx) => {
        const itemDataCode = encodeURIComponent(resItem.code);
        const rType = resItem.type;
        const prefix = detectedResources.length > 1 ? ` #${idx + 1}` : "";

        let updateLabel = "";
        let newLabel = "";
        let iconName = "mdi:view-dashboard-outline";

        if (rType === "card") {
          iconName = "mdi:view-dashboard-outline";
          updateLabel = isEs ? `🔄 Actualizar Tarjeta Existente${prefix} en Dashboard` : `🔄 Update Existing Card${prefix} in Dashboard`;
          newLabel = isEs ? `➕ Añadir como Nueva Tarjeta${prefix} al Dashboard` : `➕ Add as New Card${prefix} to Dashboard`;
        } else if (rType === "helper") {
          iconName = "mdi:puzzle-plus-outline";
          updateLabel = isEs ? `🔄 Actualizar Ayudante Existente${prefix} en Home Assistant` : `🔄 Update Existing Helper${prefix} in Home Assistant`;
          newLabel = isEs ? `➕ Crear como Nuevo Ayudante${prefix} en Home Assistant` : `➕ Create as New Helper${prefix} in Home Assistant`;
        } else if (rType === "automation") {
          iconName = "mdi:lightning-bolt";
          updateLabel = isEs ? `🔄 Actualizar Automatización Existente${prefix} en Home Assistant` : `🔄 Update Existing Automation${prefix} in Home Assistant`;
          newLabel = isEs ? `➕ Crear como Nueva Automatización${prefix} en Home Assistant` : `➕ Create as New Automation${prefix} in Home Assistant`;
        } else if (rType === "script") {
          iconName = "mdi:script-text-play-outline";
          updateLabel = isEs ? `🔄 Actualizar Script Existente${prefix} en Home Assistant` : `🔄 Update Existing Script${prefix} in Home Assistant`;
          newLabel = isEs ? `➕ Crear como Nuevo Script${prefix} en Home Assistant` : `➕ Create as New Script${prefix} in Home Assistant`;
        } else if (rType === "scene") {
          iconName = "mdi:palette-outline";
          updateLabel = isEs ? `🔄 Actualizar Escena Existente${prefix} en Home Assistant` : `🔄 Update Existing Scene${prefix} in Home Assistant`;
          newLabel = isEs ? `➕ Crear como Nueva Escena${prefix} en Home Assistant` : `➕ Create as New Scene${prefix} in Home Assistant`;
        }

        const exists = this._checkResourceExists(rType, resItem.code);

        footerHtml += `
          <div class="code-actions-group" data-code="${itemDataCode}" data-resource="${rType}">
            ${exists ? `
              <button class="code-action-btn code-save-update-btn" data-code="${itemDataCode}" data-resource="${rType}" data-mode="update" title="${updateLabel}">
                <ha-icon icon="${iconName}"></ha-icon>
                <span class="btn-text">${updateLabel}</span>
              </button>
              <button class="code-action-btn code-save-new-btn secondary-btn" data-code="${itemDataCode}" data-resource="${rType}" data-mode="add" title="${newLabel}">
                <ha-icon icon="mdi:content-copy"></ha-icon>
                <span class="btn-text">${isEs ? "➕ Crear como Duplicado" : "➕ Create Duplicate"}</span>
              </button>
            ` : `
              <button class="code-action-btn code-save-new-btn" data-code="${itemDataCode}" data-resource="${rType}" data-mode="add" title="${newLabel}">
                <ha-icon icon="mdi:plus-circle-outline"></ha-icon>
                <span class="btn-text">${newLabel}</span>
              </button>
            `}
          </div>
        `;
      });
      footerHtml += `</div>`;
      text += footerHtml;
    }

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
      const label = isUser ? (isEs ? "🧑 Tú" : "🧑 You") : "🤖 " + escapeHtml(msg.agent_name || (isEs ? "IA" : "AI"));
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

    // Helper to merge Lovelace card properties non-destructively
    function mergeCardProps(existing, incoming) {
      if (!existing || typeof existing !== "object") return incoming;
      if (existing.type !== incoming.type) {
        const result = { ...incoming };
        if (existing.layout_options && !incoming.layout_options) result.layout_options = existing.layout_options;
        if (existing.grid_options && !incoming.grid_options) result.grid_options = existing.grid_options;
        if (existing.visibility && !incoming.visibility) result.visibility = existing.visibility;
        if (existing.view_layout && !incoming.view_layout) result.view_layout = existing.view_layout;
        return result;
      }
      const merged = { ...existing, ...incoming };
      if (existing.card_mod && !incoming.card_mod) merged.card_mod = existing.card_mod;
      if (existing.layout_options && !incoming.layout_options) merged.layout_options = existing.layout_options;
      if (existing.grid_options && !incoming.grid_options) merged.grid_options = existing.grid_options;
      if (existing.visibility && !incoming.visibility) merged.visibility = existing.visibility;
      if (existing.hold_action && !incoming.hold_action) merged.hold_action = existing.hold_action;
      if (existing.double_tap_action && !incoming.double_tap_action) merged.double_tap_action = existing.double_tap_action;
      return merged;
    }

    // Unified click handler for all code action buttons (Update vs Add vs Revert)
    const actionButtons = container.querySelectorAll(".code-action-btn");
    actionButtons.forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const rawCode = decodeURIComponent(btn.getAttribute("data-code") || "");
        const mode = btn.getAttribute("data-mode") || "add"; // "update", "add", or "revert"
        const isEs = this._isSpanish();

        const btnGroup = btn.closest(".code-actions-group") || btn.parentNode;
        const allGroupBtns = btnGroup.querySelectorAll(".code-action-btn");

        if (mode === "revert") {
          await this._revertLastBackup(btn);
          return;
        }

        if (!rawCode) return;
        allGroupBtns.forEach((b) => (b.disabled = true));

        const textSpan = btn.querySelector(".btn-text");
        if (textSpan) {
          textSpan.textContent = isEs
            ? (mode === "update" ? "Actualizando..." : "Creando...")
            : (mode === "update" ? "Updating..." : "Creating...");
        }

        try {
          const res = await this._hass.callWS({
            type: "nexus_mcp/yaml_to_json",
            yaml: rawCode,
            mode: mode,
            allow_update: mode === "update",
          });

          if (!res || !res.data) {
            throw new Error(isEs ? "Formato YAML no reconocido" : "Unrecognized YAML format");
          }

          const resType = res.resource_type || (
            res.is_card ? "card" :
            res.is_helper ? "helper" :
            res.is_script ? "script" :
            res.is_scene ? "scene" : "automation"
          );

          let okMsg = "";
          let undoLabel = "";
          let undoCallback = null;

          if (resType === "card") {
            const newCard = res.data;
            const pathname = window.location.pathname || "";
            const pathParts = pathname.split("/").filter(Boolean);
            let urlPath = null;
            if (pathParts.length > 0 && pathParts[0] !== "lovelace") {
              urlPath = pathParts[0];
            }

            let configRes = null;
            try {
              configRes = await this._hass.callWS({
                type: "lovelace/config",
                url_path: urlPath,
              });
            } catch (_) {}

            // Auto-fallback: if views empty, query 'mi-casa'
            if (!configRes || !Array.isArray(configRes.views) || configRes.views.length === 0) {
              try {
                const miCasaRes = await this._hass.callWS({
                  type: "lovelace/config",
                  url_path: "mi-casa",
                });
                if (miCasaRes && Array.isArray(miCasaRes.views) && miCasaRes.views.length > 0) {
                  configRes = miCasaRes;
                  urlPath = "mi-casa";
                }
              } catch (_) {}
            }

            if (!configRes || !Array.isArray(configRes.views) || configRes.views.length === 0) {
              throw new Error(isEs ? "No se pudo leer la configuración del dashboard" : "Could not load dashboard config");
            }

            const backupDashboardConfig = JSON.parse(JSON.stringify(configRes));
            localStorage.setItem("nexus_last_backup", JSON.stringify({
              type: "card",
              urlPath: urlPath,
              config: backupDashboardConfig,
              timestamp: Date.now()
            }));
            this._updateHeaderUndoState();

            const views = configRes.views;
            let targetView = views[0];
            const currentViewPath = pathParts.length > 1 ? pathParts[1] : "";
            if (currentViewPath) {
              const matched = views.find(
                (v, idx) => v.path === currentViewPath || String(idx) === currentViewPath
              );
              if (matched) targetView = matched;
            }

            let cardUpdated = false;
            const isExplicitUpdate = mode === "update";

            // Recursive entity extractor
            function extractEntities(obj) {
              const ents = new Set();
              function scan(val) {
                if (!val) return;
                if (typeof val === "string") {
                  const trimmed = val.trim();
                  if (/^[a-z0-9_]+\.[a-z0-9_]+$/i.test(trimmed)) {
                    ents.add(trimmed.toLowerCase());
                    ents.add(trimmed.toLowerCase().replace(/_local$/, ""));
                  }
                } else if (Array.isArray(val)) {
                  val.forEach(scan);
                } else if (typeof val === "object") {
                  for (const k in val) {
                    scan(val[k]);
                  }
                }
              }
              scan(obj);
              return ents;
            }

            const newCardEntities = extractEntities(newCard);
            const newCardId = newCard.id || newCard.card_id;
            const newCardName = (newCard.title || newCard.name || "").trim().toLowerCase();

            // Extract keywords from newCard names or entities
            const newKeywords = [];
            if (newCardName) {
              newCardName.split(/\s+/).forEach((w) => {
                if (w.length >= 4) newKeywords.push(w);
              });
            }
            newCardEntities.forEach((e) => {
              const part = e.split(".")[1] || "";
              part.split("_").forEach((w) => {
                if (w.length >= 4) newKeywords.push(w);
              });
            });

            function matches(c) {
              if (!c || typeof c !== "object") return false;
              if (newCardId && (c.id === newCardId || c.card_id === newCardId)) return true;

              // Check entities
              const cEntities = extractEntities(c);
              for (const e of newCardEntities) {
                if (cEntities.has(e)) return true;
              }

              // Check entity in JSON string dump
              const cDump = JSON.stringify(c).toLowerCase();
              for (const e of newCardEntities) {
                if (cDump.includes(e)) return true;
              }

              // Check name / title match
              const cName = (c.title || c.name || "").trim().toLowerCase();
              if (newCardName && cName) {
                if (newCardName === cName) return true;
                if (newCardName.includes(cName) || cName.includes(newCardName)) return true;
              }

              // Check keyword overlap (e.g. "oukitel")
              for (const kw of newKeywords) {
                if (kw && cDump.includes(kw)) return true;
              }

              // Same type fallback if card content mentions the entity
              if (newCard.type && c.type === newCard.type && newCardEntities.size > 0) {
                for (const e of newCardEntities) {
                  if (cDump.includes(e)) return true;
                }
              }

              return false;
            }

            const insertAtBeginning = /principio|inicio|arriba|primera|top|start/i.test(rawCode) ||
              (this._messages && this._messages.length > 0 && /principio|inicio|arriba|primera|top|start/i.test(this._messages[this._messages.length - 2]?.content || ""));

            if (isExplicitUpdate) {
              // 1. Search in targetView
              if (Array.isArray(targetView.sections)) {
                for (const sec of targetView.sections) {
                  if (Array.isArray(sec.cards)) {
                    const matchIdx = sec.cards.findIndex(matches);
                    if (matchIdx !== -1) {
                      sec.cards[matchIdx] = mergeCardProps(sec.cards[matchIdx], newCard);
                      cardUpdated = true;
                      sec.cards = sec.cards.filter((sc, idx) => idx === matchIdx || !matches(sc));
                      break;
                    }
                  }
                }
              }
              if (!cardUpdated && Array.isArray(targetView.cards)) {
                const matchIdx = targetView.cards.findIndex(matches);
                if (matchIdx !== -1) {
                  targetView.cards[matchIdx] = mergeCardProps(targetView.cards[matchIdx], newCard);
                  cardUpdated = true;
                  targetView.cards = targetView.cards.filter((tc, idx) => idx === matchIdx || !matches(tc));
                }
              }

              // 2. If not found in targetView, search across ALL views in dashboard
              if (!cardUpdated) {
                for (const v of views) {
                  if (Array.isArray(v.sections)) {
                    for (const sec of v.sections) {
                      if (Array.isArray(sec.cards)) {
                        const matchIdx = sec.cards.findIndex(matches);
                        if (matchIdx !== -1) {
                          sec.cards[matchIdx] = mergeCardProps(sec.cards[matchIdx], newCard);
                          cardUpdated = true;
                          sec.cards = sec.cards.filter((sc, idx) => idx === matchIdx || !matches(sc));
                          break;
                        }
                      }
                    }
                  }
                  if (cardUpdated) break;
                  if (Array.isArray(v.cards)) {
                    const matchIdx = v.cards.findIndex(matches);
                    if (matchIdx !== -1) {
                      v.cards[matchIdx] = mergeCardProps(v.cards[matchIdx], newCard);
                      cardUpdated = true;
                      v.cards = v.cards.filter((tc, idx) => idx === matchIdx || !matches(tc));
                      break;
                    }
                  }
                }
              }
            }

            // If not found as update, or mode is add
            if (!cardUpdated) {
              if (Array.isArray(targetView.sections) && targetView.sections.length > 0) {
                const targetSec = targetView.sections.find((s) => Array.isArray(s.cards)) || targetView.sections[0];
                targetSec.cards = targetSec.cards || [];
                if (insertAtBeginning) {
                  targetSec.cards.unshift(newCard);
                } else {
                  targetSec.cards.push(newCard);
                }
              } else {
                targetView.cards = targetView.cards || [];
                if (insertAtBeginning) {
                  targetView.cards.unshift(newCard);
                } else {
                  targetView.cards.push(newCard);
                }
              }
            }

            await this._hass.callWS({
              type: "lovelace/config/save",
              url_path: urlPath,
              config: configRes,
            });

            okMsg = cardUpdated
              ? (isEs ? "¡Tarjeta modificada y actualizada con éxito en el Dashboard!" : "Card safely modified and updated in Dashboard!")
              : (insertAtBeginning
                  ? (isEs ? "¡Tarjeta insertada al principio del Dashboard!" : "Card added at top of Dashboard!")
                  : (isEs ? "¡Nueva tarjeta añadida al Dashboard!" : "New card added to Dashboard!"));

            undoLabel = isEs ? "↩️ Deshacer cambios en el Dashboard" : "↩️ Undo Dashboard changes";
            undoCallback = async () => {
              await this._hass.callWS({
                type: "lovelace/config/save",
                url_path: urlPath,
                config: backupDashboardConfig,
              });
              localStorage.removeItem("nexus_last_backup");
              this._updateHeaderUndoState();
            };

          } else if (resType === "helper") {
            const helperId = res.helper_id;
            const entityId = helperId ? `${res.helper_domain}.${helperId}` : null;
            const existingState = entityId && this._hass?.states?.[entityId];
            const prevAttributes = existingState ? { ...existingState.attributes } : null;

            localStorage.setItem("nexus_last_backup", JSON.stringify({
              type: "helper",
              helperDomain: res.helper_domain,
              helperId: helperId,
              prevAttributes: prevAttributes,
              timestamp: Date.now()
            }));
            this._updateHeaderUndoState();

            if (mode === "add") {
              const createPayload = { ...res.data };
              delete createPayload[`${res.helper_domain}_id`];
              delete createPayload.id;
              delete createPayload.helper_id;

              const createRes = await this._hass.callWS({
                type: `${res.helper_domain}/create`,
                ...createPayload,
              });
              const createdId = createRes?.id || createRes?.[`${res.helper_domain}_id`] || helperId;

              this._lastCreatedEntities = this._lastCreatedEntities || [];
              this._lastCreatedEntities.push({
                domain: res.helper_domain,
                id: createdId,
                name: res.data?.name || "",
                entityId: `${res.helper_domain}.${createdId}`
              });

              okMsg = isEs ? "¡Ayudante creado en Home Assistant!" : "Helper active in Home Assistant!";
              undoLabel = isEs ? "↩️ Deshacer y eliminar Ayudante creado" : "↩️ Undo and delete created Helper";
              undoCallback = async () => {
                if (createdId) {
                  await this._hass.callWS({
                    type: `${res.helper_domain}/delete`,
                    [`${res.helper_domain}_id`]: createdId,
                  });
                }
                localStorage.removeItem("nexus_last_backup");
                this._updateHeaderUndoState();
              };
            } else {
              // mode === "update"
              let targetId = helperId;
              try {
                const listItems = await this._hass.callWS({ type: `${res.helper_domain}/list` });
                if (Array.isArray(listItems) && listItems.length > 0) {
                  const match = listItems.find(
                    (it) => it.id === helperId ||
                            this._isFuzzyMatch(res.data?.name, it.name) ||
                            this._isFuzzyMatch(helperId, it.id) ||
                            this._isFuzzyMatch(res.data?.name, it.id)
                  );
                  if (match) targetId = match.id;
                }
              } catch (_) {}

              if (!targetId && !existingState) {
                // If it doesn't exist to update, create it!
                const createPayload = { ...res.data };
                delete createPayload[`${res.helper_domain}_id`];
                delete createPayload.id;
                delete createPayload.helper_id;

                const createRes = await this._hass.callWS({
                  type: `${res.helper_domain}/create`,
                  ...createPayload,
                });
                const createdId = createRes?.id || helperId;

                okMsg = isEs ? "¡Ayudante creado en Home Assistant!" : "Helper active in Home Assistant!";
                undoLabel = isEs ? "↩️ Deshacer y eliminar Ayudante creado" : "↩️ Undo and delete created Helper";
                undoCallback = async () => {
                  if (createdId) {
                    await this._hass.callWS({
                      type: `${res.helper_domain}/delete`,
                      [`${res.helper_domain}_id`]: createdId,
                    });
                  }
                  localStorage.removeItem("nexus_last_backup");
                  this._updateHeaderUndoState();
                };
              } else {
                const mergedPayload = {
                  ...(prevAttributes ? {
                    name: prevAttributes.friendly_name,
                    icon: prevAttributes.icon,
                    min: prevAttributes.min,
                    max: prevAttributes.max,
                    step: prevAttributes.step,
                    options: prevAttributes.options,
                    unit_of_measurement: prevAttributes.unit_of_measurement,
                    mode: prevAttributes.mode,
                  } : {}),
                  ...res.data,
                };
                delete mergedPayload[`${res.helper_domain}_id`];
                delete mergedPayload.id;
                delete mergedPayload.helper_id;

                await this._hass.callWS({
                  type: `${res.helper_domain}/update`,
                  [`${res.helper_domain}_id`]: targetId,
                  ...mergedPayload,
                });

                okMsg = isEs ? "¡Ayudante actualizado con respaldo!" : "Helper safely updated!";
                undoLabel = isEs ? "↩️ Deshacer cambios en el Ayudante" : "↩️ Undo Helper changes";
                undoCallback = async () => {
                  if (prevAttributes) {
                    await this._hass.callWS({
                      type: `${res.helper_domain}/update`,
                      [`${res.helper_domain}_id`]: targetId,
                      name: prevAttributes.friendly_name,
                      icon: prevAttributes.icon,
                      min: prevAttributes.min,
                      max: prevAttributes.max,
                      step: prevAttributes.step,
                      options: prevAttributes.options,
                      unit_of_measurement: prevAttributes.unit_of_measurement,
                      mode: prevAttributes.mode,
                    });
                  }
                  localStorage.removeItem("nexus_last_backup");
                  this._updateHeaderUndoState();
                };
              }
            }

          } else if (resType === "automation") {
            const payload = res.data;
            const autoId = res.automation_id || payload.id || `nexus_${Date.now()}`;
            payload.id = autoId;

            let prevAutoConfig = null;
            let isExisting = false;
            try {
              prevAutoConfig = await this._hass.callApi("GET", `config/automation/config/${autoId}`);
              isExisting = !!prevAutoConfig;
            } catch (_) {
              isExisting = false;
            }

            localStorage.setItem("nexus_last_backup", JSON.stringify({
              type: "automation",
              autoId: autoId,
              prevConfig: prevAutoConfig,
              timestamp: Date.now()
            }));
            this._updateHeaderUndoState();

            if ((mode === "update" || isExisting) && prevAutoConfig && typeof prevAutoConfig === "object") {
              Object.keys(prevAutoConfig).forEach((k) => {
                if (payload[k] === undefined) {
                  payload[k] = prevAutoConfig[k];
                }
              });
            }

            await this._hass.callApi("POST", `config/automation/config/${autoId}`, payload);

            okMsg = (mode === "update" || isExisting)
              ? (isEs ? "¡Automatización actualizada con respaldo!" : "Automation safely updated!")
              : (isEs ? "¡Automatización creada y activa!" : "Automation active!");

            undoLabel = isEs ? "↩️ Deshacer cambios en la Automatización" : "↩️ Undo Automation changes";
            undoCallback = async () => {
              if (isExisting && prevAutoConfig) {
                await this._hass.callApi("POST", `config/automation/config/${autoId}`, prevAutoConfig);
              } else {
                await this._hass.callApi("DELETE", `config/automation/config/${autoId}`);
              }
              localStorage.removeItem("nexus_last_backup");
              this._updateHeaderUndoState();
            };

          } else if (resType === "script") {
            const scriptId = res.script_id || `nexus_script_${Date.now()}`;
            let prevScriptConfig = null;
            let isExistingScript = false;
            try {
              prevScriptConfig = await this._hass.callApi("GET", `config/script/config/${scriptId}`);
              isExistingScript = !!prevScriptConfig;
            } catch (_) {}

            localStorage.setItem("nexus_last_backup", JSON.stringify({
              type: "script",
              scriptId: scriptId,
              prevConfig: prevScriptConfig,
              timestamp: Date.now()
            }));
            this._updateHeaderUndoState();

            if ((mode === "update" || isExistingScript) && prevScriptConfig && typeof prevScriptConfig === "object") {
              Object.keys(prevScriptConfig).forEach((k) => {
                if (res.data[k] === undefined) {
                  res.data[k] = prevScriptConfig[k];
                }
              });
            }

            await this._hass.callApi("POST", `config/script/config/${scriptId}`, res.data);

            okMsg = (mode === "update" || isExistingScript)
              ? (isEs ? "¡Script actualizado con respaldo!" : "Script safely updated!")
              : (isEs ? "¡Script creado y activo!" : "Script active!");

            undoLabel = isEs ? "↩️ Deshacer cambios en el Script" : "↩️ Undo Script changes";
            undoCallback = async () => {
              if (isExistingScript && prevScriptConfig) {
                await this._hass.callApi("POST", `config/script/config/${scriptId}`, prevScriptConfig);
              } else {
                await this._hass.callApi("DELETE", `config/script/config/${scriptId}`);
              }
              localStorage.removeItem("nexus_last_backup");
              this._updateHeaderUndoState();
            };

          } else if (resType === "scene") {
            const sceneId = res.scene_id || `nexus_scene_${Date.now()}`;
            let prevSceneConfig = null;
            let isExistingScene = false;
            try {
              prevSceneConfig = await this._hass.callApi("GET", `config/scene/config/${sceneId}`);
              isExistingScene = !!prevSceneConfig;
            } catch (_) {}

            localStorage.setItem("nexus_last_backup", JSON.stringify({
              type: "scene",
              sceneId: sceneId,
              prevConfig: prevSceneConfig,
              timestamp: Date.now()
            }));
            this._updateHeaderUndoState();

            if ((mode === "update" || isExistingScene) && prevSceneConfig && typeof prevSceneConfig === "object") {
              Object.keys(prevSceneConfig).forEach((k) => {
                if (res.data[k] === undefined) {
                  res.data[k] = prevSceneConfig[k];
                }
              });
            }

            await this._hass.callApi("POST", `config/scene/config/${sceneId}`, res.data);

            okMsg = (mode === "update" || isExistingScene)
              ? (isEs ? "¡Escena actualizada con respaldo!" : "Scene safely updated!")
              : (isEs ? "¡Escena creada en Home Assistant!" : "Scene active in Home Assistant!");

            undoLabel = isEs ? "↩️ Deshacer cambios en la Escena" : "↩️ Undo Scene changes";
            undoCallback = async () => {
              if (isExistingScene && prevSceneConfig) {
                await this._hass.callApi("POST", `config/scene/config/${sceneId}`, prevSceneConfig);
              } else {
                await this._hass.callApi("DELETE", `config/scene/config/${sceneId}`);
              }
              localStorage.removeItem("nexus_last_backup");
              this._updateHeaderUndoState();
            };
          }

          // Replace the button group with the confirmation banner and Undo button
          btnGroup.innerHTML = `
            <div class="code-success-banner">
              <ha-icon icon="mdi:check-circle"></ha-icon>
              <span>${escapeHtml(okMsg)}</span>
            </div>
            <button class="code-revert-btn" title="${escapeHtml(undoLabel)}">
              <ha-icon icon="mdi:undo-variant"></ha-icon>
              <span class="btn-text">${escapeHtml(undoLabel)}</span>
            </button>
          `;

          const undoBtn = btnGroup.querySelector(".code-revert-btn");
          if (undoBtn && undoCallback) {
            undoBtn.onclick = async (ue) => {
              ue.stopPropagation();
              undoBtn.disabled = true;
              const uText = undoBtn.querySelector(".btn-text");
              if (uText) uText.textContent = isEs ? "Restaurando..." : "Restoring...";
              try {
                await undoCallback();
                btnGroup.innerHTML = `
                  <div class="code-success-banner" style="background: rgba(33, 150, 243, 0.2); border-color: #2196f3; color: #64b5f6;">
                    <ha-icon icon="mdi:undo-variant"></ha-icon>
                    <span>${isEs ? "↩️ Estado anterior restaurado con éxito" : "↩️ Restored to previous state"}</span>
                  </div>
                `;
              } catch (uErr) {
                console.error("Nexus MCP Card: Undo failed:", uErr);
                undoBtn.disabled = false;
                const errMsg = (uErr && (uErr.message || uErr.error)) || (isEs ? "Error al revertir" : "Error reverting");
                if (uText) uText.textContent = errMsg;
              }
            };
          }
        } catch (err) {
          console.error("Nexus MCP Card: Action failed:", err);
          allGroupBtns.forEach((b) => (b.disabled = false));
          btn.classList.add("error");
          const rawErrMsg = (err && (err.message || err.error)) || (isEs ? "Error al procesar" : "Error processing");
          const cleanErrMsg = String(rawErrMsg).split("\n")[0].substring(0, 90);
          btn.innerHTML = `<ha-icon icon="mdi:alert-circle"></ha-icon><span class="btn-text">${escapeHtml(cleanErrMsg)}</span>`;
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
    this._aborted = false;
    const currentQueryId = ++this._queryCounter;
    this._updateSendButtonState();

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
          <div class="bubble-label">🤖 ${escapeHtml(agentName)}</div>
        </div>
        <div class="bubble-content" style="font-style: italic; opacity: 0.7;">${imageToSend ? "Analizando imagen y pensando..." : "Pensando..."}</div>
      `;
      container.appendChild(waitingBubble);
      this._scrollToBottom(true);
    }

    const userLang = this._hass?.locale?.language || this._hass?.language || (this._isSpanish() ? "es" : "en");

    let reply = "";
    try {
      const callWithTimeout = (promise, ms = 180000) =>
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

      if (imageToSend) {
        // Direct call via custom multimodal WebSocket nexus_mcp/chat
        const payload = {
          type: "nexus_mcp/chat",
          text: messageText,
          image: imageToSend,
          agent_id: agentId,
          conversation_id: this._conversationId || undefined,
          language: userLang,
        };
        const res = await callWithTimeout(this._hass.callWS(payload), 180000);
        if (currentQueryId !== this._queryCounter || this._aborted) return;
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
          language: userLang,
        };
        if (agentId) {
          payload.agent_id = agentId;
        }
        if (this._conversationId) {
          payload.conversation_id = this._conversationId;
        }

        const res = await callWithTimeout(this._hass.callWS(payload), 180000);
        if (currentQueryId !== this._queryCounter || this._aborted) return;
        reply =
          res?.response?.speech?.plain?.speech ||
          res?.response?.card?.text ||
          "Comando procesado correctamente.";

        if (res?.conversation_id) {
          this._conversationId = res.conversation_id;
        }
      }

      if (currentQueryId !== this._queryCounter || this._aborted) return;

      // Add assistant response to history
      this._messages.push({
        role: "assistant",
        agent_name: agentName,
        content: reply,
        timestamp: Date.now(),
      });
      this._saveHistoryForAgent(agentId);
    } catch (err) {
      if (currentQueryId !== this._queryCounter || this._aborted) return;
      console.error("Nexus MCP Card execution error:", err);
      this._messages.push({
        role: "assistant",
        agent_name: "Error",
        content: `Error al procesar: ${err.message || JSON.stringify(err)}`,
        timestamp: Date.now(),
      });
      this._saveHistoryForAgent(agentId);
    } finally {
      if (currentQueryId === this._queryCounter && !this._aborted) {
        this._isSending = false;
        this._updateSendButtonState();
        this._updateMessagesView(true);
      }
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
        const resetLang = this._hass?.locale?.language || this._hass?.language || (this._isSpanish() ? "es" : "en");
        await this._hass.callWS({
          type: "conversation/process",
          text: "nueva conversación",
          agent_id: agentId,
          language: resetLang,
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
    this._rendered = false;
    this._lastAgentIds = "";
  }

  setConfig(config) {
    this._config = config || {};
    if (!this._rendered) {
      this._render();
    } else {
      this._updateValues();
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._rendered) {
      this._render();
    } else {
      this._updateOptionsIfNeeded();
    }
  }

  _isSpanish() {
    if (this._config && this._config.language) {
      return this._config.language === "es";
    }
    const haObj = this._hass || document.querySelector("home-assistant")?.hass;
    const lang = haObj?.locale?.language || haObj?.language || haObj?.selectedLanguage || navigator.language || "en";
    return String(lang).toLowerCase().startsWith("es");
  }

  _getAgents() {
    if (!this._hass) return [];
    return Object.keys(this._hass.states)
      .filter((e) => e.startsWith("conversation."))
      .map((id) => ({
        id,
        name: this._hass.states[id].attributes?.friendly_name || id,
      }));
  }

  _render() {
    if (!this._hass || !this._config) return;
    this._rendered = true;

    const isEs = this._isSpanish();
    const agents = this._getAgents();
    this._lastAgentIds = agents.map((a) => a.id).sort().join(",");

    const autoLabel = isEs ? "(Automático / Selector en vivo)" : "(Automatic / Live Selector)";
    let optionsHtml = `<option value="">${autoLabel}</option>`;
    for (const ag of agents) {
      const isSel = this._config?.agent_id === ag.id ? "selected" : "";
      optionsHtml += `<option value="${escapeHtml(ag.id)}" ${isSel}>${escapeHtml(ag.name)}</option>`;
    }

    const titleLabel = isEs ? "Título de la tarjeta" : "Card Title";
    const agentLabel = isEs ? "IA / Agente predeterminado (Opcional)" : "Default AI / Agent (Optional)";
    const langLabel = isEs ? "Idioma de la interfaz" : "Interface Language";
    const autoLang = isEs ? "(Automático según Home Assistant)" : "(Automatic based on Home Assistant)";
    const currentLang = this._config?.language || "";
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
            value="${escapeHtml((this._config && this._config.title) || "Nexus MCP Intercom")}"
            style="padding: 8px 12px; border-radius: 6px; border: 1px solid var(--divider-color, #ccc); background: var(--card-background-color, inherit); color: var(--primary-text-color, inherit);"
          />
        </label>
        <label style="display: flex; flex-direction: column; gap: 4px; font-weight: 500;">
          ${agentLabel}
          <select id="cfg-agent" style="padding: 8px 12px; border-radius: 6px; border: 1px solid var(--divider-color, #ccc); background: var(--card-background-color, inherit); color: var(--primary-text-color, inherit); cursor: pointer;">
            ${optionsHtml}
          </select>
        </label>
        <label style="display: flex; flex-direction: column; gap: 4px; font-weight: 500;">
          ${langLabel}
          <select id="cfg-lang" style="padding: 8px 12px; border-radius: 6px; border: 1px solid var(--divider-color, #ccc); background: var(--card-background-color, inherit); color: var(--primary-text-color, inherit); cursor: pointer;">
            <option value="" ${currentLang === "" ? "selected" : ""}>${autoLang}</option>
            <option value="es" ${currentLang === "es" ? "selected" : ""}>Español</option>
            <option value="en" ${currentLang === "en" ? "selected" : ""}>English</option>
          </select>
        </label>
        <small style="color: var(--secondary-text-color, #666);">
          ${tipLabel}
        </small>
      </div>
    `;

    const titleInput = this.querySelector("#cfg-title");
    const agentSelect = this.querySelector("#cfg-agent");
    const langSelect = this.querySelector("#cfg-lang");

    const handleChange = () => {
      const newConfig = {
        ...this._config,
        title: titleInput ? titleInput.value : (this._config.title || "Nexus MCP Intercom"),
        agent_id: agentSelect && agentSelect.value ? agentSelect.value : undefined,
        language: langSelect && langSelect.value ? langSelect.value : undefined,
      };
      this._config = newConfig;
      const event = new CustomEvent("config-changed", {
        detail: { config: newConfig },
        bubbles: true,
        composed: true,
      });
      this.dispatchEvent(event);
    };

    if (titleInput) titleInput.oninput = handleChange;
    if (agentSelect) agentSelect.onchange = handleChange;
    if (langSelect) langSelect.onchange = handleChange;
  }

  _updateValues() {
    const titleInput = this.querySelector("#cfg-title");
    const agentSelect = this.querySelector("#cfg-agent");
    const langSelect = this.querySelector("#cfg-lang");
    if (titleInput && document.activeElement !== titleInput) {
      titleInput.value = this._config?.title || "Nexus MCP Intercom";
    }
    if (agentSelect && document.activeElement !== agentSelect) {
      agentSelect.value = this._config?.agent_id || "";
    }
    if (langSelect && document.activeElement !== langSelect) {
      langSelect.value = this._config?.language || "";
    }
  }

  _updateOptionsIfNeeded() {
    const agentSelect = this.querySelector("#cfg-agent");
    if (!agentSelect || document.activeElement === agentSelect) return;

    const agents = this._getAgents();
    const currentAgentIds = agents.map((a) => a.id).sort().join(",");
    if (currentAgentIds === this._lastAgentIds) return;

    this._lastAgentIds = currentAgentIds;
    const isEs = this._isSpanish();
    const autoLabel = isEs ? "(Automático / Selector en vivo)" : "(Automatic / Live Selector)";
    const currentVal = this._config?.agent_id || agentSelect.value || "";

    let optionsHtml = `<option value="">${autoLabel}</option>`;
    for (const ag of agents) {
      const isSel = currentVal === ag.id ? "selected" : "";
      optionsHtml += `<option value="${escapeHtml(ag.id)}" ${isSel}>${escapeHtml(ag.name)}</option>`;
    }
    agentSelect.innerHTML = optionsHtml;
    agentSelect.value = currentVal;
  }
}

customElements.define("nexus-mcp-card", NexusMcpCard);
customElements.define("nexus-mcp-card-editor", NexusMcpCardEditor);
console.info(
  "%c NEXUS MCP CARD %c v1.6.8 Ready ",
  "color: white; background: #03a9f4; font-weight: bold; padding: 2px 6px; border-radius: 4px 0 0 4px;",
  "color: #03a9f4; background: #e1f5fe; font-weight: bold; padding: 2px 6px; border-radius: 0 4px 4px 0;"
);
