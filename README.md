# Nexus MCP for Home Assistant

[![HACS Default](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/default)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-blue.svg)](https://www.home-assistant.io/)
[![MCP Ready](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

**Nexus MCP** is the first fully functional, open-source, and free **Click & Install Agentic Integration** for Home Assistant. 

It embeds a powerful **MCP Client and ReAct reasoning agent** directly into your Home Assistant instance, allowing you to converse with advanced language models (such as **Qwen 2.5 Coder** and **Google Gemini**) to create, inspect, debug, and manage your automations, scripts, and smart home entities with zero friction.

---

## 🌟 Key Features

* **⚡ 100% Free & Unlimited Options**:
  * **Google Gemini Free Tier**: Ready to use with a free API key from Google AI Studio (15 RPM / 1M TPM, no credit card required).
  * **Ollama Local (Qwen 2.5 Coder)**: Zero-cost, fully private, offline inference running on your local network.
  * **Custom BYOK**: Connect to Alibaba DashScope, OpenAI, DeepSeek, or any OpenAI-compatible provider.
* **🔌 Native MCP Bridge**:
  * Acts as a client to [`ha-mcp`](https://github.com/homeassistant-ai/ha-mcp), unlocking dozens of deep smart home tools (automation creation, entity fuzzy search, service calls, trace analysis).
* **🧠 ReAct Agentic Reasoning**:
  * The agent doesn't just chat; it plans, explores your entity registry, checks states, writes clean YAML, and validates against Home Assistant schemas before applying changes.
* **🛡️ Human-in-the-Loop Safeguards**:
  * Preview YAML diffs before automations are installed, or switch to Autonomous Mode if you want full autopilot.
* **🖱️ Pure Click & Install**:
  * Packaged as a standard HACS custom component with a guided visual Config Flow. No Docker commands or external desktop apps required.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 HOME ASSISTANT CORE                         │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ Nexus MCP (HACS Custom Component)                   │   │
│   │                                                     │   │
│   │   [ Chat / UI ] ◄──► [ ReAct Agent Orchestrator ]   │   │
│   │                                │                    │   │
│   │                                ▼                    │   │
│   │                         [ MCP Client ]              │   │
│   └────────────────────────────────┬────────────────────┘   │
│                                    │                        │
│                                    ▼ (MCP Protocol)         │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ ha-mcp Server (Home Assistant MCP Server)           │   │
│   │  • create_automation   • search_entities            │   │
│   │  • debug_trace         • call_service               │   │
│   └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Installation

### Via HACS (Recommended)
1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Open HACS > **Integrations** > Three dots menu > **Custom repositories**.
3. Add `https://github.com/victor/ha-nexus-mcp` with category `Integration`.
4. Click **Download**, then restart Home Assistant.

### Manual Installation
Copy the `custom_components/nexus_mcp` folder into your Home Assistant `config/custom_components/` directory and restart.

---

## ⚙️ Configuration

1. In Home Assistant, go to **Settings** > **Devices & Services** > **Add Integration**.
2. Search for **Nexus MCP**.
3. Choose your AI brain:
   * **Google Gemini (Free Tier)**: Paste your free key from [aistudio.google.com](https://aistudio.google.com).
   * **Ollama Local**: Enter your Ollama host (default: `http://localhost:11434/v1`) and model (`qwen2.5-coder:7b`).
   * **Custom OpenAI**: Enter your endpoint, key, and model.
4. Set your MCP server URL (connects to your `ha-mcp` instance).
5. Enjoy an intelligent agent inside your smart home!

---

## 📄 License

This project is licensed under the **MIT License** - free and open for the community. See [LICENSE](LICENSE) for details.
