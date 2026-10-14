<p align="center">
  <img src="images/banner.png" alt="Nexus MCP Banner" width="100%">
</p>

<div align="center">
  <img src="images/icon.png" width="130" height="130" alt="Nexus MCP Icon" />
  <h1>Nexus MCP for Home Assistant</h1>

  [![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/default)
  [![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1.0%20%E2%80%94%202026.9.4%2B-41BDF5.svg?logo=home-assistant)](https://www.home-assistant.io/)
  [![MCP Ready](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
  
  [![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Donate-orange?logo=buy-me-a-coffee)](https://buymeacoffee.com/VictorCV)
  [![PayPal](https://img.shields.io/badge/PayPal-Donate-blue?logo=paypal)](https://paypal.me/victorcava)
  [![Ko-fi](https://img.shields.io/badge/Ko--fi-Donate-red?logo=ko-fi)](https://ko-fi.com/victorcv)
</div>

<p align="center">
  <strong>The Ultra-Lightweight Click & Install Agentic Intercom for Home Assistant</strong><br>
  Connect Home Assistant with advanced AI models (Qwen 2.5 Coder & Google Gemini) and the Model Context Protocol (ha-mcp) at zero cost.
</p>

---

## 📦 Quick Installation via HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=VictorCV-DAM&repository=ha-nexus-mcp&category=integration)

### ⚡ 1-Click Fast Install
Click the badge above or use the direct link to open this repository directly inside your Home Assistant HACS store, then click **Download**.

### 🛠️ Manual HACS Installation
1. Open **HACS** in Home Assistant.
2. Click the three dots (top right corner) and select **Custom repositories**.
3. Add repository URL: `https://github.com/VictorCV-DAM/ha-nexus-mcp` with category **Integration**.
4. Click **Download** and then **Restart Home Assistant**.
5. Go to **Settings ➔ Devices & Services ➔ Add Integration ➔ Search for Nexus MCP**.
6. Select your preferred inference engine (Google Gemini Free Tier, Ollama local Qwen Coder, or custom OpenAI) and start interacting.

---

## 🌟 Why Nexus MCP?

Home Assistant should remain **fast, stable, and unburdened**. Heavy multi-step agentic reasoning and background workers belong on dedicated inference servers, not inside your Home Assistant event loop.

**Nexus MCP** acts as an **ultra-lightweight intercom and client** embedded directly into Home Assistant:
* **⚡ Native Conversation Integration**: Registers seamlessly as an official `ConversationEntity` (*Assist*). Speak or chat from the Home Assistant app, web dashboard, or voice satellites.
* **💸 100% Free & Unlimited Options**:
  * **Google Gemini Free Tier**: Instant setup with a free key from Google AI Studio (15 RPM / 1M TPM, no credit card required).
  * **Ollama Local (Qwen 2.5 Coder)**: Zero-cost, 100% private, offline inference on your local network.
  * **Custom BYOK**: Connect to Alibaba DashScope, OpenAI, DeepSeek, or any OpenAI-compatible provider.
* **🔌 Native MCP Bridge**:
  * Talks seamlessly with [`ha-mcp`](https://github.com/homeassistant-ai/ha-mcp) to read states, execute services, and inspect devices.
* **🛡️ Zero CPU & RAM Bloat**:
  * Built entirely on non-blocking `aiohttp` calls. No background threads, no memory leaks, no sluggishness.

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        FUERA DE HOME ASSISTANT                         │
│  (Servidor Cloud / Ollama Local / Proceso Externo / Servidor Agente)   │
│                                                                        │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ MOTOR DE INFERENCIA / MODELO DE LENGUAJE                     │     │
│   │                                                              │     │
│   │  • Google Gemini Free Tier (Cloud 0€)                        │     │
│   │  • Ollama + Qwen 2.5 Coder (Local 0€)                        │     │
│   │  • Servidor OpenAI / DashScope BYOK                          │     │
│   └──────────────────────────────▲───────────────────────────────┘     │
└──────────────────────────────────┼─────────────────────────────────────┘
                                   │
                                   │ (Llamadas asíncronas ligeras REST / HTTP)
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│                    DENTRO DE HOME ASSISTANT (HACS)                     │
│                                                                        │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ NEXUS MCP INTERCOM (Este componente)                         │     │
│   │                                                              │     │
│   │  • Entidad oficial de conversación (Assist / Voice / Chat).  │     │
│   │  • Pesa apenas unos pocos KBs.                               │     │
│   │  • Delega la inferencia de forma asíncrona sin bloquear HA.  │     │
│   │  • Muestra respuestas de texto y control de dispositivos.    │     │
│   └──────────────────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## ⚙️ Configuration Options

1. In Home Assistant, navigate to **Settings** > **Devices & Services** > **Add Integration**.
2. Search for **Nexus MCP**.
3. Select your AI engine:
   * **Google Gemini (Free Tier)**: Paste your free key from [aistudio.google.com](https://aistudio.google.com).
   * **Ollama Local**: Enter your Ollama URL (`http://localhost:11434/v1`) and model (`qwen2.5-coder:7b`).
   * **Custom OpenAI**: Enter your endpoint URL, API Key, and model name.
4. Set your MCP Server URL (connects to your `ha-mcp` server).
5. Done! Set **Nexus MCP** as your default agent in **Settings** > **Voice Assistants** > **Assist** to talk to your home intelligently.

---

## 🧪 Testing & Quality

Nexus MCP includes a full unit test suite with 100% test coverage for client parsing, JSON-RPC handling, and conversation processing:

```bash
python -m unittest discover -s tests
```

---

## ☕ Support & Donations

If you appreciate this free, open-source integration and want to support its ongoing development, feel free to buy me a coffee:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Donate-orange?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/VictorCV)
[![PayPal](https://img.shields.io/badge/PayPal-Donate-blue?style=for-the-badge&logo=paypal)](https://paypal.me/victorcava)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Donate-red?style=for-the-badge&logo=ko-fi)](https://ko-fi.com/victorcv)

---

## 📄 License

This project is licensed under the **MIT License** - 100% open-source and free for the community. See [LICENSE](LICENSE) for details.
