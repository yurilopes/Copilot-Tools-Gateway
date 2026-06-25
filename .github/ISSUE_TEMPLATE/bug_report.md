---
name: Bug report
about: Report a Copilot Tools Gateway issue with sanitized diagnostics
title: ""
labels: bug
assignees: ""
---

## Summary

Describe what failed and which provider was used.

## Environment

- OS:
- Python version:
- Copilot Tools Gateway version:
- MCP client:
- Provider: `copilot`, `m365-copilot`, or `copilot-auto`

## Safe Diagnostics

Run:

```bash
python -m copilot_tools_gateway doctor
python tools/diagnostics/check_mcp_smoke.py
```

Paste only sanitized output. Do not paste session files, cookies, tokens,
browser storage, raw requests, raw responses, prompts, answers, or document
contents.

## Expected Behavior

What did you expect to happen?

## Actual Behavior

What happened instead?
