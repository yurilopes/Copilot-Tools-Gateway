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

Consumer browser-assisted chat is intentionally not part of the main provider
path right now. The consumer provider keeps using the non-browser WebSocket
path, with `refresh consumer` as a guided browser warm-up when Copilot requires
a browser challenge. A browser-assisted provider fallback can be reconsidered if
the warm-up flow stops restoring WebSocket access reliably.

Consumer image attachments use the consumer `/c/api/attachments` endpoint and
are supported for PNG and JPEG files. This powers `copilot_vision` with
`model: copilot` and image-only `copilot_chat_with_files` calls. Consumer
document attachments such as DOCX are not enabled yet because the observed
consumer attachment endpoint did not return a usable document URL for the chat
frame.

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

Refresh an existing consumer Copilot browser-backed session:

```bash
python -m copilot_tools_gateway refresh consumer
```

Consumer Copilot may require a browser challenge before chat traffic is accepted.
When that happens, run `refresh consumer`, complete the challenge in the opened
browser, send a normal message, wait for Copilot to answer, and then retry the
MCP or HTTP request. The gateway does not synthesize Cloudflare challenge tokens
in the non-browser WebSocket path.

This warm-up step was validated with a consumer account: after the browser
challenge was completed and Copilot answered normal browser messages, consumer
chat over the non-browser WebSocket path worked again without keeping the
browser open.

The `refresh consumer` command is interactive and guided. It opens the
persistent browser profile, prints the browser warm-up steps, waits for Enter,
saves the refreshed local session, and tells the user or agent to retry the
original MCP or HTTP request.

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

Typical consumer first login:

```bash
python -m copilot_tools_gateway login consumer
```

Typical consumer stale session recovery:

```bash
python -m copilot_tools_gateway refresh consumer
```

An agent with local terminal access can run the recommended command, wait for
the user to complete any browser sign-in step, call `copilot_status` again, and
then retry the original MCP tool call. MCP tool errors also include the
recommended command text when provider resolution can identify one.

If an MCP call against `copilot` fails with a browser challenge or
`chat-service-unavailable`, the LLM should tell the user that Consumer Copilot
needs a browser warm-up. The LLM should run:

```bash
python -m copilot_tools_gateway refresh consumer
```

Then it should ask the user to complete any challenge in the opened browser,
send one normal message to Copilot, wait for Copilot to answer, and return to
the agent. After that, the LLM should retry the original MCP tool call. The LLM
should not ask the user for cookies, tokens, browser storage, or session files.

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
- `copilot` requires a valid consumer session. It supports image attachments
  for PNG and JPEG files, but not document attachments.

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

## Diagnostics

Optional diagnostic tools live under `tools/diagnostics/`. They are not part of
normal MCP or HTTP operation.

Consumer WebSocket shape capture:

```bash
python tools/diagnostics/capture_consumer_websocket_shape.py --seconds 300
```

This tool requires a local Pydoll checkout and opens the persistent consumer
browser profile. Use the opened browser normally, including completing browser
challenges if needed. The output stores only sanitized protocol shape data:
event names, key names, lengths, booleans, and short hashes. It does not store
raw payloads, cookies, tokens, browser storage, session files, or raw requests.

Consumer WebSocket health check:

```bash
python tools/diagnostics/check_consumer_websocket_health.py
```

This tool sends a fixed consumer Copilot chat prompt through the normal gateway
provider path and appends a sanitized result to
`captures/consumer-websocket-health.jsonl`. It records success or failure,
response length, whether the expected fixed response was returned, and the
session file age from filesystem metadata. It does not read or print session
file contents.
