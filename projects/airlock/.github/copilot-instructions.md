# Copilot instructions

This repo has a full agent brief in `AGENTS.md` at the root. Read it before generating
code, along with `docs/SPEC.md` and `docs/ARCHITECTURE.md`.

The rules that matter most:

- Deterministic detection (regex, format, checksum, entropy) runs before any LLM call.
  The local model only handles free prose.
- Exactly one module — `gateway.py` — is allowed to make a network call off this
  machine. Never add another.
- `block`-tier findings (API keys, connection strings, tokens, passwords) are never
  transmitted in any form. They abort the request.
- No chat UI. No interception of Copilot's own traffic. No inline-completion hooks.
- All test and sample data uses invented organisations and people. Never real customers.

Work through `docs/BUILD-PLAN.md` in order, one task at a time, and run `pytest` before
reporting a task complete.
