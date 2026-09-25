# Copilot instructions

This repo has a full agent brief in `AGENTS.md` at the root. Read it before generating
code, along with `docs/SPEC.md` and `docs/ARCHITECTURE.md`.

The rules that matter most:

- Deterministic detection (regex, format, checksum, entropy) runs before any LLM call.
  The local model only handles free prose.
- `gateway.py` is the sole outbound cloud-model request. The read-only Azure collector
  contacts the customer's Azure tenant locally before sanitization. The prose detector
  contacts a loopback-only local model.
- In an Airlock investigation, only approved sanitized cases may be exposed through
  the local MCP tool. Do not pass original customer values in Copilot prompts or other
  Copilot tools.
- `block`-tier findings (API keys, connection strings, tokens, passwords) are never
  transmitted in any form. They abort the request.
- No chat UI. No interception of Copilot's own traffic. No inline-completion hooks.
- All test and sample data uses invented organisations and people. Never real customers.

The team-selected Copilot pilot in `docs/BUILD-PLAN.md` is the current priority.
Run `pytest` before reporting a task complete.
