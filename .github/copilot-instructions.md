# Copilot instructions

Full brief in `AGENTS.md` at the repo root. Projects under `projects/` have their own
`AGENTS.md` which overrides it for code in that folder.

- This repo is mostly documents. Code lives only under `projects/<name>/`.
- When helping with an idea in `ideas/`, argue with it. Lead with the strongest reason it
  fails and say whether the AI is load-bearing or decorative.
- When building, read the project's `AGENTS.md` and `docs/ARCHITECTURE.md`, then take the
  lowest-numbered unfinished task in `docs/BUILD-PLAN.md`. One task, then stop and report.
- Never generate fixtures or examples containing real customer names, subscription IDs,
  hostnames or people. Invented content, realistic shapes.
- Never put secrets in files. Environment variables only.
