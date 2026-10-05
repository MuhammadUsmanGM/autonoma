<p align="center">
  <h1 align="center">Autonoma</h1>
  <p align="center"><strong>Your personal AI assistant, running on your computer.</strong></p>
  <p align="center">
    <img src="https://img.shields.io/npm/v/autonoma-ai?style=flat-square&color=cb3837&logo=npm" alt="npm version">
    <img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="MIT license">
  </p>
</p>

Autonoma can chat with you through Telegram, Discord, WhatsApp, Gmail, or its
web dashboard. It can remember useful details, search the web, work with files,
and connect to services such as Google Calendar, OneDrive, and GitHub.

**Autonoma runs on your computer, but AI requests are sent to the provider you
choose.** You need that provider's API key, and its usage may cost money.

## Get started

You need **Node.js 18 or newer** and **Python 3.11 or newer**.

Install Autonoma and start it:

```bash
npm install -g --allow-scripts=autonoma-ai autonoma-ai
autonoma
```

The first launch opens a setup guide. Choose an AI provider, enter its API
key, and select a model. Autonoma saves these settings for you.

Supported providers: OpenRouter, Anthropic, Google Gemini, OpenAI, Groq, and
Mistral.

Already have an OpenRouter key? You can set it before starting:

```bash
export OPENROUTER_API_KEY=your-api-key
autonoma
```

## What you can do

- **Chat:** Send messages from the terminal, dashboard, or a connected app.
- **Get help with tasks:** Search the web and read or write files in Autonoma's
  workspace.
- **Keep useful information:** Autonoma can remember details from past chats.
- **Connect services:** Sign in to Google Calendar, Contacts, or Meet, OneDrive,
  and GitHub to give Autonoma access to those services.
- **Schedule tasks:** Ask Autonoma to run a prompt once or on a schedule.

Connected services only work after you sign in and grant access.

## Dashboard

The web dashboard starts with Autonoma at
<http://127.0.0.1:8766>. Use it to chat, manage connections, review memory, and
check activity and logs.

Autonoma also opens a terminal control panel. Use the arrow keys to move,
**Enter** to select, and **Esc** to go back. From there, you can view status and
logs, manage messaging apps, open the dashboard, or restart Autonoma.

## Connect messaging apps

You can enter credentials in the terminal panel or set them in a `.env` file.

| App | What you need |
|---|---|
| Telegram | A bot token from [@BotFather](https://t.me/BotFather) |
| Discord | A bot token and the Message Content intent enabled |
| WhatsApp | Scan the QR code shown when it connects |
| Gmail | Your address and a [Google App Password](https://support.google.com/accounts/answer/185833) |
| REST API | Optional token set with `AUTONOMA_REST_API_TOKEN`; send messages to `POST /api/chat` |

## Privacy and safety

- Your chats and workspace files are stored on your computer.
- Messages are sent to your chosen AI provider so it can generate replies.
- File tools are limited to Autonoma's `workspace` folder.
- Shell commands are off by default. You must explicitly allow commands before
  Autonoma can run them.
- Autonoma's HTTP and WebSocket services only accept loopback addresses. Do not
  expose their ports to your network; the dashboard does not have login yet.

## Connect accounts

To let Autonoma work with other services, add the service's OAuth credentials
to `.env` or `autonoma.yaml`, then sign in from the dashboard's **Integrations**
page or the terminal panel.

Available connections include:

- **Google Calendar:** View and create events, and find free time.
- **Google Contacts:** Search your contacts.
- **Google Meet:** Work with meeting links and transcripts.
- **OneDrive:** Find and manage files.
- **GitHub:** Search repositories and work with issues and pull requests.

## Settings

Most people can use the setup guide and dashboard. For manual setup, settings
can be placed in environment variables, a `.env` file, or `autonoma.yaml`.
Environment variables take priority.

Example `autonoma.yaml`:

```yaml
name: Autonoma
gateway:
  host: 127.0.0.1
  port: 8765
  http_port: 8766
llm:
  provider: openrouter
  model: your-model-name
```

Common environment variables:

| Variable | Purpose |
|---|---|
| `AUTONOMA_LLM_PROVIDER` | Choose the AI provider |
| `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` | Set your provider API key |
| `AUTONOMA_LLM_MODEL` | Choose a model |
| `AUTONOMA_LOG_LEVEL` | Set logging detail: `debug`, `info`, `warning`, or `error` |

## For developers

Run from source:

```bash
git clone https://github.com/MuhammadUsmanGM/autonoma.git
cd autonoma
cp .env.example .env
pip install -e .
python -m autonoma
```

Run the test suite:

```bash
pip install pytest
pytest tests/
```

The Python application is in `autonoma/`. The React dashboard is in
`dashboard/`, and `whatsapp-bridge/` contains the WhatsApp helper service.

To work on the dashboard:

```bash
cd dashboard
npm install
npm run dev
```

## License

Autonoma is available under the MIT license. See [LICENSE](LICENSE).
