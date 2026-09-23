# Agent instructions

Rules for GitHub Copilot, Claude Code, or any other AI agent working in this repo.

## Before writing any code

1. Read `docs/SPEC.md`.
2. Read `docs/ARCHITECTURE.md`.
3. Open `docs/BUILD-PLAN.md`, find the lowest-numbered unfinished task, do that one.

## How to work

- **One task at a time.** Implement, make acceptance criteria pass, run `pytest`, stop
  and report. Do not chain tasks unprompted.
- Module names and data shapes are specified in `docs/ARCHITECTURE.md`. If something is
  missing, add it there first and say so rather than improvising.
- Every module gets tests. Filing and mailbox code is tested against fakes, never
  against a live system.

## Hard rules

- **Nothing is filed without human approval.** `clerk file` requires an approved plan.
  There is no auto-file mode and no `--yes` default.
- **Never delete a user's mail.** Processed mail is *moved* to a done folder. `.Delete()`
  must not appear anywhere in this codebase.
- **Default target is the mock.** `--target basware` must be explicit, and must refuse to
  run unless `CLERK_ALLOW_LIVE=1` is set. A demo must never touch a production AP system.
- **Never automate the OS file dialog.** Playwright's `set_input_files` sets the file on
  the input element directly. If you find yourself scripting a Windows Explorer window,
  stop — the approach is wrong.
- **Never script the login.** Attach to an already-authenticated browser over CDP.
- **Deterministic before model.** Invoice-number matches, PO matches and format checks
  run first. The model handles only what is genuinely ambiguous.
- **Verify, do not assume.** After each upload, confirm the attachment appears before
  reporting success.

## Non-goals — do not build these

- A chat UI.
- Microsoft Graph integration or any cloud mailbox API.
- Unattended filing with no human in the loop.
- Anything that writes to an invoice other than adding an attachment.
- A web service or multi-user deployment.

## Conventions

- Python 3.11+. `pywin32`, `playwright`, `pypdf`, `pdfplumber`, `pytesseract`, `pydantic`,
  `typer`, `rich`, `pytest`, `ruff`.
- Every Playwright selector lives in one module (`basware/selectors.py`) with a comment
  recording where it was observed. They are guesses until verified against the real page.
- Sample mails and documents in `samples/` use invented suppliers and people.
