# MCP Reference

Copilot Tools Gateway exposes Microsoft Copilot capabilities through MCP tools.
The MCP client remains responsible for its primary LLM. The gateway only adds
tool calls that can use a signed-in Copilot account.

## Server Command

Run the MCP server over stdio:

```bash
python -m copilot_tools_gateway mcp
```

Equivalent installed script:

```bash
copilot-tools-gateway mcp
```

Generic MCP client configuration:

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

Use the same server definition in OpenCode, Codex, Claude Desktop, or another
stdio MCP client. If the client does not inherit the repository virtual
environment, use the absolute interpreter path in `command`.

## Models

Supported model values:

- `copilot-auto`: choose a valid configured provider automatically.
- `m365-copilot`: use Microsoft 365 Copilot.
- `copilot`: use consumer Microsoft Copilot.

`copilot-auto` prefers `m365-copilot` when both providers are available.

## Capability Matrix

| Capability | `m365-copilot` | `copilot` |
| --- | --- | --- |
| Text chat | Yes | Yes |
| Streaming | Yes | Yes |
| Conversation resume | Yes | Yes |
| Image generation | Yes | Yes |
| Image analysis | Yes | Yes |
| PNG and JPEG attachments | Yes | Yes |
| Document attachments | Yes | No |
| PDF, DOCX, PPTX, XLSX, TXT validation | Diagnostic coverage exists | No |

M365 document attachments require valid Copilot, Graph, and search access. If
document access fails after a session has aged, run `refresh m365`.

Consumer document attachments are not supported. Use `m365-copilot` for
documents, or limit `copilot` file requests to PNG and JPEG images.

## Response Envelope

All MCP tools return `mcp-response/v2`:

```json
{
  "schema_version": "mcp-response/v2",
  "ok": true,
  "tool": "copilot_chat",
  "model_requested": "copilot-auto",
  "provider": "m365-copilot",
  "result": {},
  "error": null,
  "agent": {
    "summary": "Copilot chat completed.",
    "user_message": "Copilot returned a response.",
    "recommended_action": "none",
    "recommended_command": null,
    "retryable": false,
    "retry_after_action": false,
    "next_steps": []
  },
  "diagnostics": {}
}
```

Envelope fields:

- `schema_version`: always `mcp-response/v2`.
- `ok`: true for success, false for failure.
- `tool`: MCP tool name.
- `model_requested`: model argument sent by the client, or null for status.
- `provider`: resolved provider when known.
- `result`: tool-specific success payload.
- `error`: structured failure payload, or null on success.
- `agent`: concise guidance for the calling LLM.
- `diagnostics`: safe operational metadata.

Diagnostics must not contain tokens, cookies, browser storage, raw requests,
raw responses, session file contents, or unnecessary user content.

## Agent Guidance

Every response includes `agent`:

```json
{
  "summary": "Microsoft 365 Copilot is not ready.",
  "user_message": "Microsoft 365 Copilot needs refresh_session before this request can run.",
  "recommended_action": "refresh_session",
  "recommended_command": ["python", "-m", "copilot_tools_gateway", "refresh", "m365"],
  "retryable": true,
  "retry_after_action": true,
  "next_steps": [
    "Run the recommended local command.",
    "Complete any browser sign-in or challenge steps if requested.",
    "Retry the original MCP tool call after the command succeeds."
  ]
}
```

Agent rules:

- Show `agent.user_message` when the user needs a concise explanation.
- Run `agent.recommended_command` only when local terminal access is available
  and the user has allowed local commands.
- If `retry_after_action` is true, run or ask for the action, call
  `copilot_status`, then retry the original tool.
- If `retryable` is false, do not retry the same request unchanged.
- Never ask the user to paste cookies, tokens, browser storage, session files,
  or raw upstream traffic.

Recommended actions:

- `none`: no action is needed.
- `login_session`: run the provider login command.
- `refresh_session`: run the provider refresh command.
- `browser_warmup`: refresh consumer and complete the browser challenge flow.
- `retry`: retry may be useful without a separate setup action.
- `use_different_provider`: switch provider model.
- `unsupported_capability`: choose a different tool or provider.

## Error Object

Failure responses include:

```json
{
  "code": "refresh_required",
  "message": "Provider refresh is required.",
  "safe_detail": "M365 document access needs refresh.",
  "provider": "m365-copilot"
}
```

Common error codes:

- `provider_unavailable`: provider exists but is not currently usable.
- `session_expired`: stored session is expired.
- `unsupported_capability`: provider cannot perform the requested capability.
- `upstream_protocol_error`: upstream response did not match the expected
  protocol.
- `login_required`: provider needs first login.
- `refresh_required`: provider needs refresh.
- `unknown_model`: model must be `copilot-auto`, `m365-copilot`, or `copilot`.

## Tools

### `copilot_status`

Use this before relying on a provider, and after any login or refresh command.

Arguments: none.

Success `result`:

```json
{
  "providers": [
    {
      "provider": "m365-copilot",
      "configured": true,
      "available": true,
      "label": "Microsoft 365 Copilot",
      "detail": null,
      "recommended_action": null,
      "recommended_command": null,
      "capabilities": {
        "chat": true,
        "streaming": true,
        "image_generation": true,
        "vision": true,
        "file_chat": true,
        "conversation_resume": true
      }
    }
  ],
  "recommendation": {
    "summary": "Microsoft 365 Copilot is available.",
    "recommended_provider": "m365-copilot",
    "recommended_action": "none",
    "recommended_command": null
  }
}
```

Agent behavior:

- If no provider is available, follow the top-level recommendation.
- Prefer M365 when both providers are available and the user did not specify a
  provider.

### `copilot_chat`

Ask Copilot for text.

Arguments:

- `prompt`: user prompt text.
- `model`: optional, defaults to `copilot-auto`.
- `conversation_id`: optional upstream conversation id.

Example:

```json
{
  "prompt": "Summarize the role of MCP in one sentence.",
  "model": "copilot-auto"
}
```

Success `result`:

```json
{
  "text": "MCP lets an assistant call external tools through a standard protocol.",
  "conversation_id": "example-conversation-id",
  "conversation_resume_supported": true,
  "streaming_supported": true
}
```

Conversation behavior:

- If `conversation_resume_supported` is true and `conversation_id` is present,
  pass that id back to continue the same conversation.
- If no `conversation_id` is present, treat the response as a completed one-off
  call.

### `copilot_generate_image`

Generate images with a provider that supports image generation.

Arguments:

- `prompt`: image prompt.
- `model`: optional, defaults to `copilot-auto`.
- `count`: optional number of images, defaults to 1.

Example:

```json
{
  "prompt": "A simple blue notebook on a desk, product photo style.",
  "model": "copilot",
  "count": 1
}
```

Success `result`:

```json
{
  "images": [
    {
      "url": "https://example.invalid/image.png",
      "preview_url": "https://example.invalid/preview.png"
    }
  ],
  "count": 1
}
```

Agent behavior:

- Present returned URLs to the user when appropriate.
- If the provider returns unsupported capability, call `copilot_status` and
  choose a provider with `image_generation: true`.

### `copilot_vision`

Ask Copilot to analyze one image.

Arguments:

- `image_path`: local PNG or JPEG path.
- `prompt`: question about the image.
- `model`: optional, defaults to `copilot-auto`.

Example:

```json
{
  "image_path": "C:\\path\\to\\cat.png",
  "prompt": "Describe the image and mention the main subject.",
  "model": "copilot"
}
```

Success `result`:

```json
{
  "text": "The image shows a cat sitting near a window.",
  "conversation_id": "example-conversation-id",
  "input_image_supported": true
}
```

Provider notes:

- Consumer Copilot supports PNG and JPEG image attachments.
- M365 Copilot supports image analysis through its file flow.

### `copilot_chat_with_files`

Ask Copilot to answer using local file attachments.

Arguments:

- `file_paths`: list of local file paths.
- `prompt`: question about the files.
- `model`: optional, defaults to `copilot-auto`.

M365 document example:

```json
{
  "file_paths": ["C:\\path\\to\\report.docx"],
  "prompt": "Summarize the document and list the validation marker.",
  "model": "m365-copilot"
}
```

Consumer image example:

```json
{
  "file_paths": ["C:\\path\\to\\photo.jpg"],
  "prompt": "What is visible in this image?",
  "model": "copilot"
}
```

Success `result`:

```json
{
  "text": "The document describes a validation process.",
  "conversation_id": "example-conversation-id",
  "file_count": 1,
  "file_extensions": [".docx"],
  "attachment_mode": "document"
}
```

Attachment modes:

- `image`: all files are PNG or JPEG.
- `document`: all files are non-image document types.
- `mixed`: image and non-image attachments were sent together.

Provider notes:

- Use `m365-copilot` for DOCX, PDF, PPTX, XLSX, TXT, and larger document tests.
- Use `copilot` only for PNG and JPEG image attachments.
- If M365 document access fails with refresh guidance, run `refresh m365`. The
  browser may ask the user to attach a small document to refresh document
  access.

## Login And Refresh Flow For Agents

Login and refresh are intentionally CLI operations. MCP tools do not open a
browser automatically.

First login:

```bash
python -m copilot_tools_gateway login m365
python -m copilot_tools_gateway login consumer
```

Refresh:

```bash
python -m copilot_tools_gateway refresh m365
python -m copilot_tools_gateway refresh consumer
```

Agent flow:

1. Call `copilot_status`.
2. If a provider is unavailable, inspect `agent.recommended_command`.
3. Run the command when local terminal access is available.
4. Ask the user to complete browser sign-in, account selection, challenge, or
   warm-up steps if the command opens a browser.
5. Call `copilot_status` again.
6. Retry the original MCP tool only after status or the prior response says the
   action is complete.

Consumer browser warm-up:

1. Run `python -m copilot_tools_gateway refresh consumer`.
2. Complete any browser challenge in the opened browser.
3. Send one normal message to Copilot in the browser.
4. Wait for Copilot to answer.
5. Return to the MCP client and retry the original tool call.

M365 document refresh:

1. Run `python -m copilot_tools_gateway refresh m365`.
2. Complete sign-in or account selection if requested.
3. If instructed, send a normal browser message or attach a small document.
4. Wait for Copilot to answer or for the CLI to report refreshed access.
5. Retry the document tool call.

## Safety Rules For Agents

- Do not request cookies, tokens, browser storage, session files, or raw
  upstream requests from the user.
- Do not print or store session file contents.
- Do not treat diagnostics as user document content.
- Do not run login or refresh unless the user has allowed local commands.
- Prefer `copilot_status` after any recovery step.
- Use `m365-copilot` for documents and `copilot` for consumer image workflows.
