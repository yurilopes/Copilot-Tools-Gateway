# Copilot Tools Gateway

Copilot Tools Gateway exposes Microsoft Copilot accounts as local tools for
agentic coding assistants. It is designed for OpenCode, Codex, Claude Desktop,
and other MCP-capable clients that already have their own primary LLM.

This project is not intended to replace a selectable coding model. It provides
tool calls for auxiliary Copilot tasks such as chat, image generation, and
vision-style image interpretation when the signed-in account supports them.

> Unofficial project. This repository is not affiliated with Microsoft. It uses
> your own Microsoft account session locally. Use it responsibly and follow the
> service terms that apply to your account.

## What It Provides

- MCP tools for agentic clients:
  - `copilot_status`
  - `copilot_chat`
  - `copilot_generate_image`
  - `copilot_vision`
  - `copilot_chat_with_files`
- An OpenAI-compatible HTTP surface for simple local interoperability:
  - `GET /v1/models`
  - `POST /v1/chat/completions`
  - `POST /v1/images/generations`
- Provider routing for two Copilot account families:
  - `m365-copilot` for Microsoft 365 Copilot accounts.
  - `copilot` for consumer Microsoft Copilot accounts.
  - `copilot-auto` to choose a valid configured provider automatically.

## Current Design

The two account families use different upstream protocols. The gateway hides
that behind a common provider contract.

- Microsoft 365 Copilot uses the M365 chat service over SignalR WebSocket.
- Consumer Copilot uses the public Copilot web protocol with cookies, a Copilot
  chat token when signed in, and challenge responses.

Capabilities are explicit. A provider must report whether it supports chat,
streaming, image generation, vision, and conversation resume. The MCP server uses
those capabilities to fail clearly instead of pretending unsupported features
exist.

## Requirements

- Python 3.11 or newer.
- Windows, macOS, or Linux.
- A Microsoft account with access to the Copilot surface you want to use.

Install dependencies:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,mcp]"
python -m playwright install chromium
```

Unix shells:

```bash
. .venv/bin/activate
python -m pip install -e ".[dev,mcp]"
python -m playwright install chromium
```

## Login

Consumer Copilot:

```bash
python -m copilot_tools_gateway login consumer
```

Microsoft 365 Copilot:

```bash
python -m copilot_tools_gateway login m365
```

Refresh an existing Microsoft 365 Copilot browser-backed session:

```bash
python -m copilot_tools_gateway refresh m365
```

Sessions are stored under `session/`, which is ignored by Git. Do not commit or
share session files.

## MCP Usage

Run the MCP server over stdio:

```bash
python -m copilot_tools_gateway mcp
```

Example MCP client configuration:

```json
{
  "mcpServers": {
    "copilot-tools-gateway": {
      "command": "python",
      "args": ["-m", "copilot_tools_gateway", "mcp"]
    }
  }
}
```

Use the same command in OpenCode, Codex, Claude Desktop, or another MCP client
that accepts stdio MCP servers. If the client runs outside the repository,
replace `python` with the absolute path to the virtual environment interpreter.

### Agent Login And Refresh Flow

Login and refresh are CLI operations, not MCP tools. Agents should use
`copilot_status` before relying on a provider. When a provider is unavailable,
the status response includes `recommended_action` and `recommended_command`
fields when the gateway knows the next safe local command.

Typical M365 first login:

```bash
python -m copilot_tools_gateway login m365
```

Typical M365 refresh after an expired browser-backed session:

```bash
python -m copilot_tools_gateway refresh m365
```

Typical consumer login or stale consumer session recovery:

```bash
python -m copilot_tools_gateway login consumer
```

An agent with local terminal access can run the recommended command, wait for
the user to complete any browser sign-in step, call `copilot_status` again, and
then retry the original MCP tool call. MCP tool errors also include the
recommended command text when provider resolution can identify one.

## HTTP API Usage

Start the local API:

```bash
python -m copilot_tools_gateway api
```

The default URL is `http://127.0.0.1:3991/v1`.

List models:

```bash
curl http://127.0.0.1:3991/v1/models
```

Chat:

```bash
curl http://127.0.0.1:3991/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"copilot-auto\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello in one short sentence.\"}]}"
```

## Model Routing

- `copilot-auto` uses the first available configured provider.
- `m365-copilot` requires a valid M365 session.
- `copilot` requires a valid consumer session.

If both providers are configured, `copilot-auto` prefers M365 by default because
it usually has broader enterprise capabilities. Use an explicit model name when
you need a specific account family.

## Safety And Privacy

- Runtime sessions, cookies, and tokens stay under `session/`.
- AI-generated content is private by default.
- Public APIs return normalized gateway data, not raw vendor payloads.

## Development

Run focused checks with explicit timeouts:

```bash
python -m pytest tests
python -m ruff check .
python -m mypy src
```

The project intentionally uses small modules, explicit provider contracts, and
strict typing. See `AGENTS.md` and `code-style.md` before changing architecture.
