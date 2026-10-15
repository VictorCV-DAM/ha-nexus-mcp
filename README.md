<p align="center">
  <img src="images/banner.png" alt="Nexus MCP Banner" width="100%">
</p>

<div align="center">
  <img src="images/icon.png" width="130" height="130" alt="Nexus MCP Icon" />
  <h1>Nexus MCP for Home Assistant</h1>

  [![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/default)
  [![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1.0%20%E2%80%94%202026.9.4%2B-41BDF5.svg?logo=home-assistant)](https://www.home-assistant.io/)
  [![MCP Ready](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)
  [![Tests](https://img.shields.io/badge/Tests-20%2F20%20Passing-brightgreen.svg)](tests/)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
  
  [![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Donate-orange?logo=buy-me-a-coffee)](https://buymeacoffee.com/VictorCV)
  [![PayPal](https://img.shields.io/badge/PayPal-Donate-blue?logo=paypal)](https://paypal.me/victorcava)
  [![Ko-fi](https://img.shields.io/badge/Ko--fi-Donate-red?logo=ko-fi)](https://ko-fi.com/victorcv)
</div>

<p align="center">
  <strong>The Ultra-Lightweight Click & Install Agentic Intercom for Home Assistant</strong><br>
  Connect Home Assistant with cutting-edge AI models (Groq Cloud, Google Gemini, Qwen Cloud, Ollama Local) and the Model Context Protocol (ha-mcp) with native Tool Calling and 100% free tiers.
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
4. Click **Download** and then **Restart Home Assistant** (*Settings > System > Restart*).
5. Go to **Settings ➔ Devices & Services ➔ Add Integration ➔ Search for Nexus MCP**.
6. Select your preferred inference engine and start chatting with your smart home.

---

## 🚀 Key Features

* **⚡ Native Home Assistant Voice & Chat (`ConversationEntity`)**:
  Registers seamlessly as an official Home Assistant Assist agent. Talk to your home via web dashboard, mobile app, or ESPHome / Assist voice satellites.
* **🛠️ Native Tool Calling & Automation Creator**:
  Equipped with built-in Home Assistant tools:
  * `ha_search_entities`: Semantic discovery of entities and device IDs.
  * `ha_get_entity_state`: State and attribute inspection.
  * `ha_call_service`: Real-time execution of any Home Assistant service (`light.turn_on`, `switch.toggle`, `climate.set_temperature`, etc.).
  * `ha_create_automation`: Dynamic generation and hot-reload of Home Assistant automations (`automations.yaml`), with automatic schema sanitization for time patterns and service actions.
* **🌐 100% Free & Fast Cloud Providers**:
  * **Groq Cloud (Recommended in Europe & Worldwide)**:
    * 1-click Google/GitHub login, zero credit card, zero phone verification required.
    * Up to **14,400 free requests per day** at ultra-high inference speeds (~0.08s latency).
    * Supported models: `openai/gpt-oss-120b` (default - 120B reasoning model!), `qwen/qwen3.8-27b` (ultra-fast ~0.08s latency), and `openai/gpt-oss-20b`.
    * Direct in-app link to official catalog: [Groq Model Catalog](https://console.groq.com/docs/models).
  * **Google Gemini (Free Tier)**:
    * Free API key from [Google AI Studio](https://aistudio.google.com/app/apikey) (no billing required).
    * `gemini-3.1-flash-lite`: **250,000 Tokens/Min (TPM)** and 500 requests/day for conversational velocity with zero rate limits.
    * `gemini-flash-latest`: Always points to the newest Flash release.
  * **Qwen Cloud (Alibaba Model Studio / DashScope)**:
    * Access to flagship Qwen models (`qwen-plus-latest`, `qwen-turbo-latest`, `qwen2.5-coder-32b-instruct`) with millions of free tokens.
  * **Ollama Local**:
    * 100% offline, private, and free inference on your local network (`qwen2.5-coder:7b`).
  * **Custom OpenAI / BYOK**:
    * Connect to [OpenRouter](https://openrouter.ai/keys) (including `:free` models), OpenAI Platform, DeepSeek, or any OpenAI-compatible API.
* **🛡️ Resilient & Self-Healing Architecture**:
  * **Automatic Exponential Backoff**: Gracefully retries HTTP 429 (rate limits) and HTTP 503 (server load) honoring `Retry-After` headers.
  * **In-Flight Model Fallback**: Automatically switches to capable backup models (`openai/gpt-oss-120b`) if a specific model trips rate limits.
  * **Model Name Auto-Normalization**: Automatically fixes common user inputs (e.g. `qwen3.8-27b` is auto-prefixed to `qwen/qwen3.8-27b`).
  * **Model Clarity in Hub & Entity Titles**: Config entries and entities clearly display the active model name in parentheses (e.g., `Nexus MCP (qwen/qwen3.8-27b)`).
* **⚙️ Full In-App Options Flow**:
  * Update API keys, switch models, adjust endpoints, or toggle autonomous mode anytime via **Settings > Devices & Services > Nexus MCP > Configure (⚙️)** without reinstalling.
  * All configuration screens feature clickable direct links to API key dashboards and model documentation.
* **🔌 Native MCP Bridge**:
  * Auto-discovers and connects to [`ha-mcp`](https://github.com/homeassistant-ai/ha-mcp) via Server-Sent Events (SSE) or HTTP.
* **🪶 Zero CPU & RAM Overhead**:
  * Built entirely on non-blocking `aiohttp` calls on Home Assistant's event loop. No background threads, no memory leaks.

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        FUERA DE HOME ASSISTANT                         │
│  (Groq Cloud / Google AI Studio / Alibaba Cloud / Ollama Local)        │
│                                                                        │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ MOTOR DE INFERENCIA / MODELO DE LENGUAJE                     │     │
│   │                                                              │     │
│   │  • Groq Cloud (14.400 req/día, Qwen 3.8 27B / GPT-OSS 120B)  │     │
│   │  • Google Gemini Free Tier (250k TPM, Gemini 3.1 Flash Lite) │     │
│   │  • Alibaba Model Studio (Qwen Plus / Coder)                  │     │
│   │  • Ollama + Qwen 2.5 Coder (Local Offline 0€)                │     │
│   │  • Servidor OpenAI / OpenRouter / DeepSeek BYOK              │     │
│   └──────────────────────────────▲───────────────────────────────┘     │
└──────────────────────────────────┼─────────────────────────────────────┘
                                   │
                                   │ (Llamadas asíncronas REST / HTTP con Tool Calling)
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│                    DENTRO DE HOME ASSISTANT (HACS)                     │
│                                                                        │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ NEXUS MCP INTERCOM (Custom Component)                        │     │
│   │                                                              │     │
│   │  • Entidad oficial de conversación (Assist / Voice / Web).   │     │
│   │  • Herramientas nativas: Búsqueda, Estados, Servicios, Auto. │     │
│   │  • Sanitizador automático de YAML de automatizaciones.       │     │
│   │  • Auto-reintentos con backoff exponencial en HTTP 429/503.  │     │
│   │  • Conexión auto-descubierta con servidor HA-MCP.            │     │
│   └──────────────────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Free Tier Models Comparison

| Provider | Model Identifier | Tokens/Min (**TPM**) | Requests/Day (**RPD**) | Availability (EU / Global) | Best Used For |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Google Gemini** | **`gemini-3.1-flash-lite`** *(Recommended)* | **250,000 TPM** | 500 RPD | Global / Europe | **Best daily driver**: Zero minute-rate-limit friction in fast voice/chat conversations. |
| **Groq Cloud** | **`openai/gpt-oss-120b`** *(Default Groq)* | 6,000 TPM | **14,400 RPD** | Global / Europe | **Maximum AI intelligence**: 120B open reasoning model for complex automations. |
| **Groq Cloud** | **`qwen/qwen3.8-27b`** | 6,000 TPM | **14,400 RPD** | Global / Europe | **Ultra-fast inference**: ~0.08s latency, excellent tool calling and multilingual support. |
| **Groq Cloud** | **`openai/gpt-oss-20b`** | 6,000 TPM | **14,400 RPD** | Global / Europe | Fast and lightweight 20B model for simple queries. |
| **Alibaba Cloud**| **`qwen-plus-latest`** | Generous | Generous | Global / Europe | Qwen flagship intelligence via DashScope. |
| **Ollama Local** | **`qwen2.5-coder:7b`** | Unlimited | Unlimited | Local Network | 100% private, offline home control. |

*Note on Meta Llama models: Groq Cloud restricts Meta models (`llama-3.3-70b`) in European Union regions due to EU licensing. Nexus MCP automatically falls back to `qwen/qwen3.8-27b` or `openai/gpt-oss-120b` to prevent HTTP 404 errors.*

---

## ⚙️ Configuration & Direct Links

When setting up or reconfiguring Nexus MCP, clickable links are provided right inside the dialog:

* **Google Gemini**: Get your free key at [Google AI Studio](https://aistudio.google.com/app/apikey).
* **Groq Cloud**: Get your free key at [Groq Console](https://console.groq.com/keys) and check the [Official Model Catalog](https://console.groq.com/docs/models).
* **Qwen Cloud**: Get your key at [Alibaba Cloud Model Studio](https://modelstudio.console.alibabacloud.com/).
* **OpenRouter**: Get your key at [OpenRouter](https://openrouter.ai/keys) (explore [Free Models](https://openrouter.ai/models?max_price=0)).
* **HA-MCP**: Discover or install the server from [homeassistant-ai/ha-mcp](https://github.com/homeassistant-ai/ha-mcp).

---

## 🧪 Testing & Quality Assurance

Nexus MCP maintains a rigorous test suite covering config flows, options flows, entity discovery, builtin tools, schema sanitization, and LLM engines:

```bash
python -m unittest discover -s tests
```

*Result:* **20/20 unit tests passing (100% success rate)**.

---

## ☕ Support & Donations

If you appreciate this free, open-source integration and want to support its ongoing development, feel free to buy me a coffee:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Donate-orange?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/VictorCV)
[![PayPal](https://img.shields.io/badge/PayPal-Donate-blue?style=for-the-badge&logo=paypal)](https://paypal.me/victorcava)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Donate-red?style=for-the-badge&logo=ko-fi)](https://ko-fi.com/victorcv)

---

## 📄 License

This project is licensed under the **MIT License** - 100% open-source and free for the community. See [LICENSE](LICENSE) for details.
