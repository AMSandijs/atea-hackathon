# Agent instructions

Rules for GitHub Copilot, Claude Code, or any other AI agent working in this repo.

## Before writing any code

1. Read `docs/SPEC.md` — what this is and why.
2. Read `docs/ARCHITECTURE.md` — the contracts you must implement against.
3. Open `docs/BUILD-PLAN.md` and find the **lowest-numbered unfinished task**.

## How to work

- **One task at a time.** Implement it, make its acceptance criteria pass, run
  `pytest`, then stop and report what you did. Do not chain tasks unprompted.
- **Do not invent structure.** Module names, function signatures and data classes are
  specified in `docs/ARCHITECTURE.md`. If something is genuinely missing, add it there
  first and say so, rather than improvising in code.
- **Every module gets tests.** A task is not done until its tests pass.
- If a task cannot be completed as written, stop and explain why. Do not silently
  substitute a different approach.

## Hard rules

- **Deterministic before model.** If a value can be found with a regex, a format check,
  a checksum or an entropy test, it is found that way. The local model is only invoked
  on free prose that rules cannot cover. Violating this makes the tool too slow to use.
- **No cloud call may bypass `gateway.py`.** There is exactly one place in this codebase
  where bytes leave the machine. Do not add another, do not add a convenience HTTP call
  in a detector or a test helper.
- **Blocked findings are never sent, not even encrypted or hashed.** A `block`-tier
  finding aborts the request and tells the user to rotate the credential.
- **Never commit real customer data.** All fixtures, samples and tests use invented
  organisations and people with realistic *shapes*. See `docs/EVAL.md`.
- **Fail loudly.** If a stand-in cannot be mapped back during re-hydration, surface it.
  Never silently return an answer containing unresolved placeholders.

## Non-goals — do not build these

- A chat UI or conversational assistant. Input is text or a file; output is a checkpoint
  and an answer.
- Interception, proxying or rewriting of GitHub Copilot's network traffic. Fragile,
  undocumented, and against its terms. The CLI and the MCP server are the front doors.
- Inline-completion (ghost text) integration. The latency budget makes it impossible.
- A web service, a container deployment, or any multi-user server. This is a local tool.
- Authentication, user accounts, telemetry.

## Conventions

- Python 3.11+. Standard library plus: `presidio-analyzer`, `presidio-anonymizer`,
  `pydantic`, `pyyaml`, `typer`, `rich`, `httpx`, `pytest`, `ruff`.
- `ruff` for lint and format. Type hints on every public function.
- Config lives in `policy.yaml`, not in Python. A security officer must be able to read
  and amend it without touching code.
- Secrets for the cloud endpoint come from environment variables, never from files in
  the repo.
- Keep functions small enough to unit test without mocking the world.
