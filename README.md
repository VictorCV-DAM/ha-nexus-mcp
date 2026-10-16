<p align="center">
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/banner.png" alt="Nexus MCP Banner" width="100%">
</p>

<div align="center">
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/icon.png" width="130" height="130" alt="Nexus MCP Icon" />
  <h1>Nexus MCP for Home Assistant</h1>

  [![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/default)
  [![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1.0%20%E2%80%94%202026.9.4%2B-41BDF5.svg?logo=home-assistant)](https://www.home-assistant.io/)
  [![MCP Ready](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)
  [![Tests](https://img.shields.io/badge/Tests-50%2F50%20Passing-brightgreen.svg)](https://github.com/VictorCV-DAM/ha-nexus-mcp/tree/main/tests)
  [![Downloads](https://img.shields.io/github/downloads/VictorCV-DAM/ha-nexus-mcp/total.svg?color=brightgreen)](https://github.com/VictorCV-DAM/ha-nexus-mcp/releases)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/VictorCV-DAM/ha-nexus-mcp/blob/main/LICENSE)
  
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

## 📋 Compatibility & Requirements

Nexus MCP is engineered to be ultra-lightweight, with **zero external Python package dependencies** (`requirements: []`) and native compatibility across all Home Assistant installation types:

| Component / Platform | Minimum Version | Tested & Verified | Status |
| :--- | :--- | :--- | :--- |
| **Home Assistant Core** | `2024.1.0` | `2024.1.0 — 2026.9.4+` | ✅ Fully Supported |
| **Home Assistant OS (HAOS)** | Any supported | Latest Stable | ✅ Fully Supported |
| **Home Assistant Supervised** | Any supported | Debian 12+ | ✅ Fully Supported |
| **Home Assistant Container (Docker)** | `2024.1.0` | Latest Container | ✅ Fully Supported |
| **Home Assistant Core (Python venv)** | `2024.1.0` | Python `3.11` / `3.12+` | ✅ Fully Supported |
| **HACS (Community Store)** | `1.30.0+` | `v2.0+` | ✅ 1-Click Fast Install |
| **Voice Assist Pipeline** | Core Assist | Web, Mobile App & ESPHome Satellites | ✅ Fully Supported |
| **Model Context Protocol (`ha-mcp`)** | Standard SSE / HTTP | `homeassistant-ai/ha-mcp` | ✅ Local Auto-Discovery |

> [!NOTE]
> Nexus MCP runs entirely on Home Assistant's native event loop using the shared `aiohttp` client session. It does not load heavy local libraries into memory, ensuring zero impact on your Home Assistant startup time, memory footprint, or CPU usage.

---

## 📸 Visual Showcase & Real-World Demo

### 💬 Interactive Chat & Automation Creator (with Safety Confirmation)
Ask your smart home in plain natural language (voice or text). Nexus MCP searches entities, designs the automation, explains what it understood, and asks for your confirmation before writing changes:

<p align="center">
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/12_chat_search_explain.png" width="48%" align="middle" style="vertical-align: middle;" alt="Entity Search & Plan Explanation" />
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/13_chat_confirm_create.png" width="48%" align="middle" style="vertical-align: middle;" alt="Confirmation & Automation Creation" />
</p>

### ⚙️ Live Automation & Real-Time Traces
The created automation is immediately visible, editable in the Home Assistant visual editor, and running with live execution traces:

<p align="center">
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/15_automation_visual.png" width="48%" align="middle" style="vertical-align: middle;" alt="Created Automation in Home Assistant UI" />
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/16_automation_traces.png" width="48%" align="middle" style="vertical-align: middle;" alt="Live Automation Traces" />
</p>

### 🎙️ Home Assistant Assist Pipeline Integration
Select Nexus MCP directly as your active Conversation Agent in any Assist pipeline with local Whisper speech-to-text and Edge TTS:

<p align="center">
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/17_assist_pipeline.png" width="60%" align="middle" style="vertical-align: middle;" alt="Assist Pipeline with Nexus MCP" />
</p>

### 🧩 1-Click Click & Install Setup Across 5 AI Brains
Seamlessly connect free cloud providers or local models with automatic discovery *(Groq, Gemini, and Qwen are 100% verified in production; Ollama Local and Custom OpenAI are implemented under standard specs but marked as experimental pending community testing due to local hardware/resource constraints)*:

<p align="center">
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/01_select_brand.png" width="31%" align="middle" style="vertical-align: middle;" alt="Select Nexus MCP" />
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/02_select_provider.png" width="31%" align="middle" style="vertical-align: middle;" alt="Select AI Provider" />
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/04_config_groq.png" width="31%" align="middle" style="vertical-align: middle;" alt="Groq Cloud 120B Setup" />
</p>
<p align="center">
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/03_config_gemini.png" width="31%" align="middle" style="vertical-align: middle;" alt="Google Gemini Setup" />
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/05_config_qwen.png" width="31%" align="middle" style="vertical-align: middle;" alt="Qwen Cloud Setup" />
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/06_config_ollama.png" width="31%" align="middle" style="vertical-align: middle;" alt="Ollama Local Setup" />
</p>

### 🛡️ Autonomous Mode & Hot-Reconfiguration
Toggle between autonomous execution or interactive confirmation anytime via Settings without restarting Home Assistant:

<p align="center">
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/08_config_mcp_uncheck_v2.png" width="31%" align="middle" style="vertical-align: middle;" alt="Autonomous Mode Unchecked" />
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/09_config_mcp_check_v2.png" width="31%" align="middle" style="vertical-align: middle;" alt="Autonomous Mode Checked" />
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/10_options_reconfigure_v4.png" width="31%" align="middle" style="vertical-align: middle;" alt="Options Flow Reconfigure" />
</p>

### 💬 Plug & Play Lovelace Card (Visual Card Picker)
Nexus MCP includes a **100% plug & play custom Lovelace card** that registers automatically in Home Assistant. No manual resource URLs or configuration needed!

1. Open any Dashboard, click **Edit dashboard** ➔ **Add Card**.
2. Look for **«Nexus MCP Chat & Historial»** right in the visual card picker list (with live visual preview and configuration editor).
3. Chat in real-time, view message bubbles, send queries directly from the card input bar, or tap the microphone to open Assist!

```yaml
type: custom:nexus-mcp-card
title: Nexus MCP Intercom
```
*(Tip: If you prefer standard Markdown cards, you can also use `{{ state_attr('sensor.nexus_mcp_openai_gpt_oss_120b_conversation_history', 'formatted_markdown') }}`)*  
*(Note: When updating via HACS, do a hard refresh with `Ctrl + F5` or clear your browser/companion app cache so the new card version loads immediately).*

### 👁️ Multimodal Vision, Image Paste (`Ctrl+V`) & 1-Click Text Selection
Interact visually with your smart home using vision-capable AI models (e.g. `qwen/qwen3.8-27b`, Google Gemini Flash, or local vision models):

<p align="center">
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/18_card_image_paste.png" width="31%" align="middle" style="vertical-align: middle;" alt="Clipboard Image Paste Ctrl+V" />
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/19_card_vision_analysis.png" width="31%" align="middle" style="vertical-align: middle;" alt="Multimodal Real-Time Vision Analysis" />
  <img src="https://raw.githubusercontent.com/VictorCV-DAM/ha-nexus-mcp/main/images/20_card_text_selection.png" width="31%" align="middle" style="vertical-align: middle;" alt="1-Click Copy and Manual Text Selection" />
</p>

* **🖼️ Instant Clipboard Paste (`Ctrl + V`) & File Attach (`📎`)**: Take a screenshot with `Win + Shift + S` or copy an image anywhere on the web, and paste it directly into the chat. You can also click the paperclip icon (`📎`) to upload an image from disk. Includes instant thumbnail preview with a removal button (`✕`).
* **🧠 Real-Time Multimodal Diagnostics**: Upload camera snapshots, device photos, or Home Assistant error screenshots directly to the AI for instant automated diagnosis and actionable recommendations.
* **📋 1-Click Message Copy & Native Text Selection**: Every message bubble features a 1-click copy icon button (`mdi:content-copy`) with instant visual checkmark feedback (`mdi:check`). Full cursor text selection is enabled on all message bubbles for seamless copying of code blocks, YAML configurations, or entity IDs.
* **📦 Syntax-Styled Code Blocks & 1-Click Code Copy**: Any code or YAML automation returned by the model is automatically parsed into a high-contrast code box with language badge and a dedicated **"Copy code"** button.
* **🔄 Cross-Browser & Multi-Device History Sync**: Powered by a dedicated Home Assistant backend WebSocket (`nexus_mcp/get_history`), conversations synchronize seamlessly across all your browsers, laptops, and mobile devices without depending on isolated browser storage.
* **⚡ Guaranteed Auto-Scroll on Reload**: Multi-phase auto-scrolling guarantees that upon page reload or image load, the chat is immediately anchored to the latest sent or received message.

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
  * **🛡️ Autonomous Mode & Interactive Confirmation**: When Autonomous Mode is disabled (default), Nexus MCP will tell you what it understood, describe the exact planned automation (triggers, conditions, actions, entity IDs), and ask for your confirmation before creating it. If Autonomous Mode is enabled, it creates automations immediately without asking.
  * **🔄 Persistent Memory, Continuity & 10 Dedicated Telemetry Sensors**: Conversations are stored on disk via Home Assistant's native storage (`.storage`), ensuring chat history survives restarts and integration reloads. When starting a new session or reopening Assist, Nexus MCP automatically inherits the recent context from your previous conversation so you can seamlessly continue where you left off. Nexus MCP also exposes 10 dedicated sensors (Tokens Used, Requests Remaining, Quota %, TPM/RPM Limits, Window Wait, Rate Limit Cooldown, Conversation History) with ready-to-use formatted Markdown for your Dashboards, plus the `nexus_mcp.clear_history` action. Saying *"Nueva conversación"*, *"Reset"*, or *"Clear history"* instantly resets memory on demand.
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
  * **Ollama Local (Experimental / Untested)**:
    * 100% offline, private, and free inference on your local network (`qwen2.5-coder:7b`).
    * ⚠️ *Note: Implemented following standard Ollama OpenAI-compatible schemas, but currently pending extensive real-world testing due to lack of local hardware/GPU resources. Community feedback and PRs are warmly welcome!*
  * **Custom OpenAI / BYOK (Experimental / Untested)**:
    * Connect to [OpenRouter](https://openrouter.ai/keys) (including `:free` models), OpenAI Platform, DeepSeek, or any OpenAI-compatible API.
    * ⚠️ *Note: Implemented via standard OpenAI chat completion endpoints, but pending full testing due to lack of funded accounts/resources. Community testing is appreciated!*
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
│                      OUTSIDE OF HOME ASSISTANT                         │
│  (Groq Cloud / Google AI Studio / Alibaba Cloud / Ollama Local)        │
│                                                                        │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ INFERENCE ENGINE / LLM PROVIDERS                             │     │
│   │                                                              │     │
│   │  • Groq Cloud (14,400 req/day, Qwen 3.8 27B / GPT-OSS 120B)  │     │
│   │  • Google Gemini Free Tier (250k TPM, Gemini 3.1 Flash Lite) │     │
│   │  • Alibaba Model Studio (Qwen Plus / Coder)                  │     │
│   │  • Ollama + Qwen 2.5 Coder (Local Offline 100% Free)         │     │
│   │  • OpenAI Server / OpenRouter / DeepSeek BYOK                │     │
│   └──────────────────────────────▲───────────────────────────────┘     │
└──────────────────────────────────┼─────────────────────────────────────┘
                                   │
                                   │ (Asynchronous REST / HTTP Calls with Native Tool Calling)
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│                    INSIDE HOME ASSISTANT (HACS)                        │
│                                                                        │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ NEXUS MCP INTERCOM (Custom Component)                        │     │
│   │                                                              │     │
│   │  • Official Conversation Entity (Assist / Voice / Web).      │     │
│   │  • Built-in Tools: Entity Search, States, Services, Auto.    │     │
│   │  • Automatic Schema Sanitizer for Automations YAML.          │     │
│   │  • Exponential Backoff & Auto-Retries on HTTP 429/503.       │     │
│   │  • Auto-Discovered SSE/HTTP Connection to HA-MCP Server.     │     │
│   └──────────────────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Free Tier Models Comparison

| Provider | Model Identifier | Tokens/Min (**TPM**) | Requests/Day (**RPD**) | Availability (EU / Global) | Best Used For |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Google Gemini** | **`gemini-3.1-flash-lite`** *(Recommended)* | **250,000 TPM** | 500 RPD | Global / Europe | **Best daily driver**: Zero minute-rate-limit friction in fast voice/chat conversations. |
| **Groq Cloud** | **`openai/gpt-oss-120b`** *(Default Groq)* | **8,000 TPM** | **14,400 RPD** | Global / Europe | **Maximum AI intelligence**: 120B open reasoning model for complex automations. |
| **Groq Cloud** | **`qwen/qwen3.8-27b`** | **7,000 TPM** | **14,400 RPD** | Global / Europe | **Ultra-fast inference**: ~0.08s latency, excellent tool calling and multilingual support. |
| **Groq Cloud** | **`openai/gpt-oss-20b`** | **8,000 TPM** | **14,400 RPD** | Global / Europe | Fast and lightweight 20B model for simple queries. |
| **Alibaba Cloud**| **`qwen-plus-latest`** | Generous | Generous | Global / Europe | Qwen flagship intelligence via DashScope. |
| **Ollama Local** | **`qwen2.5-coder:7b`** | Unlimited | Unlimited | Local Network | 100% private, offline home control. |

*Note on Meta Llama models: Groq Cloud restricts Meta models (`llama-3.3-70b`) in European Union regions due to EU licensing. Nexus MCP automatically falls back to `qwen/qwen3.8-27b` or `openai/gpt-oss-120b` to prevent HTTP 404 errors.*

---

## 📈 10 Dedicated Telemetry & Quota Sensors

Nexus MCP automatically registers independent first-class Home Assistant sensors for complete visibility into your AI limits and usage:

| Sensor Entity ID | Entity Name | Unit | Hover Tooltip Description |
| :--- | :--- | :---: | :--- |
| `sensor.<id>_daily_tokens` | **Daily Tokens Used** | tokens | Total prompt and completion tokens used today across all requests. |
| `sensor.<id>_daily_requests_used` | **Daily Requests Used** | requests | Total number of queries submitted to the AI model today. |
| `sensor.<id>_daily_quota_remaining` | **Daily Requests Remaining** | requests | Remaining requests available today before hitting the daily quota. |
| `sensor.<id>_daily_quota_percent` | **Daily Quota Remaining** | % | Percentage of daily provider requests quota remaining until midnight UTC reset. |
| `sensor.<id>_daily_requests_limit` | **Daily Requests Limit** | requests | Maximum allowable queries per day (RPD) in the provider's free tier. |
| `sensor.<id>_model_limit` | **Tokens Per Minute Limit** | tokens/min | Maximum input tokens per minute (ITPM/TPM) allowed by the provider. |
| `sensor.<id>_rpm_limit` | **Requests Per Minute Limit** | req/min | Maximum queries allowed within any 60-second window. |
| `sensor.<id>_max_wait_time` | **Max Window Wait Time** | s | Sliding window duration in seconds required for per-minute tokens to replenish. |
| `sensor.<id>_rate_limit_reset` | **Rate Limit Cooldown** | s | Live real-time cooldown seconds remaining if throttled by the provider. |
| `sensor.<id>_conversation_history` | **Conversation History** | - | Most recent conversation message and activity preview with formatted markdown. |

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

*Result:* **50/50 unit tests passing (100% success rate)**.

---

## ☕ Support & Donations

If you appreciate this free, open-source integration and want to support its ongoing development, feel free to buy me a coffee:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Donate-orange?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/VictorCV)
[![PayPal](https://img.shields.io/badge/PayPal-Donate-blue?style=for-the-badge&logo=paypal)](https://paypal.me/victorcava)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Donate-red?style=for-the-badge&logo=ko-fi)](https://ko-fi.com/victorcv)

---

## 📄 License

This project is licensed under the **MIT License** - 100% open-source and free for the community. See [LICENSE](LICENSE) for details.
