# Copilot instructions

Full brief in `AGENTS.md` at the root; read it with `docs/SPEC.md` and
`docs/ARCHITECTURE.md` before generating code.

The rules that matter most:

- Nothing is filed without a human approving the plan. No auto-file mode.
- Never delete mail — move it to a done folder. `.Delete()` must not appear in this repo.
- The default filing target is the local mock. `--target basware` requires an explicit
  flag plus `CLERK_ALLOW_LIVE=1`.
- Never automate the OS file-open dialog; use Playwright `set_input_files`. Never script
  the login; attach to an authenticated browser over CDP.
- Deterministic matching (invoice number, PO) before any model call.
- All sample data uses invented suppliers and people.

Work through `docs/BUILD-PLAN.md` in order, one task at a time.
