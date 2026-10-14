<p align="center">
  <img src="images/banner.png" alt="Nexus MCP Banner" width="100%">
</p>

<p align="center">
  <a href="https://github.com/hacs/default"><img src="https://img.shields.io/badge/HACS-Default-orange.svg" alt="HACS"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://www.home-assistant.io/"><img src="https://img.shields.io/badge/Home%20Assistant-2024.1+-blue.svg" alt="Home Assistant"></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-Compatible-green.svg" alt="MCP Ready"></a>
</p>

<p align="center">
  <strong>The Ultra-Lightweight Click & Install Agentic Intercom for Home Assistant</strong><br>
  Connect Home Assistant with advanced AI models (Qwen 2.5 Coder & Google Gemini) and the Model Context Protocol (ha-mcp) at zero cost.
</p>

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

## 🚀 Installation

### Via HACS (Recommended)
1. Ensure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance.
2. In HACS, go to **Integrations** > Three dots menu (top right) > **Custom repositories**.
3. Add repository URL:
   ```text
   https://github.com/VictorCV-DAM/ha-nexus-mcp
   ```
4. Category: **Integration**.
5. Click **Add**, find **Nexus MCP**, click **Download**, and restart Home Assistant.

### Manual Installation
Copy the `custom_components/nexus_mcp` directory into your Home Assistant `config/custom_components/` folder and restart.

---

## ⚙️ Configuration

1. In Home Assistant, navigate to **Settings** > **Devices & Services** > **Add Integration**.
2. Search for **Nexus MCP**.
3. Select your preferred inference engine:
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

## 📄 License

This project is licensed under the **MIT License** - 100% open-source and free for the community. See [LICENSE](LICENSE) for details.
