# Agent Instructions

This repository is a public, English-language project. Keep all code, comments,
documentation, CLI text, commit messages, and project files in English.

We may discuss the work in Portuguese, but the repository itself stays in
English.

## Core Principles

- Hold the line on code quality from the first change. Do not accept shortcuts,
  postponed cleanup, or "fix it later" work.
- Human readability, correctness, and security outrank concision, implementation
  speed, and clever abstractions.
- Treat this machine with care. This machine is our home.
- Read repository instructions and relevant project data before acting.
- Use focused commands and partial reads before opening large files.
- Never use em dash characters anywhere in code, comments, documentation,
  commit messages, or assistant responses.

## Non-Negotiable Rules

- Never run destructive actions unless they are necessary, explicit, and safe.
- Never revert someone else's changes unless the user explicitly asks for it.
- Preserve UTF-8 in code and text files.
- Never copy secrets, credentials, keys, tokens, sensitive endpoints, unsafe
  patterns, session files, cookies, browser storage, or generated private data
  from other projects.
- Treat AI-generated content as private by default.
- Do not weaken Ruff, mypy, Pyright, LSP, lint, typecheck, tests, or equivalent
  validators to hide a problem.
- Do not use `Any`, `cast`, `type: ignore`, or equivalent shortcuts to silence
  typing. If an external library forces a dynamic boundary, isolate it,
  validate it, and normalize it immediately.
- Do not bend core logic to make mocks easier or to force tests to pass.
- Do not add artificial backward compatibility for incorrect alpha contracts.
- Validate access, payment, credits, permissions, privacy, ownership, and
  authorization in backend code when those domains exist.

## Code Quality

- Enforce strict coding conventions from the first commit.
- Respect LSP diagnostics and fix root causes.
- Prefer direct operational flow, early validation, and domain-oriented names.
- Keep responsibilities separated with explicit boundaries and dependencies.
- Avoid overengineering. Add abstractions only when they remove real complexity
  or define a stable integration contract.
- Internal errors must be specific and domain-oriented.
- Convert internal errors into structured HTTP, MCP, or CLI errors only at the
  appropriate top-level boundary.
- Best-effort fallbacks must be explicit in name, safe, and documented.
- Logs must record relevant operations and transitions without exposing tokens,
  cookies, storage, full JavaScript, user content, secrets, vendor metadata, or
  sensitive data.

## Typing

- Use strong typing whenever possible.
- In Python, prefer precise types, `TypedDict`, dataclasses, Pydantic models, or
  equivalent validated models when appropriate.
- In TypeScript, prefer domain types, validation schemas, and explicit narrowing.
- Keep external dynamic library boundaries small. Validate and normalize values
  before they enter the core domain.

## Tests

- Tests must protect real contracts, not force the core to accept artificial
  shapes.
- Never change core logic only to simplify mocks.
- Never add defensive fallbacks or artificial compatibility only to pass tests.
- If a test reveals an incorrect alpha contract, correct the contract and update
  documentation.
- Include focused tests for business rules, payments, credits, permissions,
  asynchronous generation, uploads, privacy, and authorization when those domains
  exist.

## Execution, Timeouts, And Sliced Runs

- Always set explicit timeouts for commands that can take time, including
  builds, dependency installs, test suites, heavy linting, async processing, and
  browser automation.
- Split long runs by module, suite, file, or group instead of one monolithic
  command.
- Structure tests so subsets can run by path, marker, or focused group.
- Report progress between long pieces before starting the next piece.
- Treat timeouts as explicit signals. Report them, narrow the run, and continue
  without masking the issue or weakening validators.

## Architecture And Boundaries

- Keep clear layers: application, API, domain, infrastructure, integrations,
  workers, and persistence.
- Do not couple business rules to a vendor, payment gateway, AI provider, or
  database implementation.
- Integration categories with multiple implementations must have a common,
  stable contract.
- Distinguish integration type from configured account or instance.
- Integrations and accounts must be activatable or deactivatable through
  persisted state and an administrative surface when those concepts exist.
- Disabled implementations must not be considered for new operations.
- Add implementations through contracts, registration, and resolution, not
  scattered conditionals.
- Keep vendor data internal. Do not expose it through public APIs.
- Private data is private by default.
- Destructive operations require explicit intent, validation, and safe logs.

## File Size

- Target at most 400 physical lines per source file.
- The maximum tolerated size is 450 physical lines.
- Files between 401 and 450 lines require a short justification in progress or
  review notes.
- Files above 450 lines must be refactored while preserving logical cohesion.
- Do not fragment cohesive logic only to reduce line count.
- This rule preserves readability and keeps agent work token-efficient.

## Comments And Logs

Code comments must be in English, short, and explain only:

- a functional or business rule;
- a security or ownership boundary;
- a lock or concurrency decision;
- the risk of a destructive operation;
- the reason for safe best-effort recovery.

Do not narrate obvious code.

Logs must be useful for operations and safe by default. Log events, transitions,
and safe internal identifiers. Do not log full payloads, tokens, cookies, storage,
secrets, documents, sensitive content, full prompts, or full JavaScript.

## Expected Code Style

Use `code-style.md` as the detailed reference. Preserve a direct, modular,
domain-oriented operational style:

- small modules by responsibility;
- explicit and linear flows;
- early validation with fast returns;
- clear domain names;
- small and stable interfaces;
- separated models and handlers;
- transition logs with enough safe context;
- little magic;
- little unnecessary abstraction;
- no versioned secrets;
- rigorous typing;
- specific error handling.
