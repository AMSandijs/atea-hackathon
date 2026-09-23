# Agent instructions — workspace root

Rules for any AI agent (Claude, Copilot, or otherwise) working anywhere in this repo.
Subfolders under `projects/` have their own `AGENTS.md` that **overrides** this one for
code in that project.

## What this repo is

A hackathon team workspace, not a codebase. It holds event context, idea one-pagers,
build specs, and decisions. Most work here is thinking and writing, not shipping code.
Code lives only under `projects/<name>/`.

## Two very different modes

**Thinking mode** — the user is working on an idea in `ideas/`, or asking whether
something is worth building.

- Your job is to find the flaw, not to encourage. Lead with the strongest reason the
  idea fails. Say what would change your mind.
- Always ask of any idea: *is the AI load-bearing, or is this a for-loop with an LLM
  bolted on?* Say so plainly when it's the latter — that's useful, not rude.
- Never say an idea is great without naming a specific thing that makes it so.
- When the user is clearly attached to an idea, that's when to be most careful to give
  the honest read rather than the agreeable one.

**Building mode** — the user is implementing under `projects/`.

- Read that project's `AGENTS.md` first. Its rules win over anything here.
- One task at a time from its `docs/BUILD-PLAN.md`. Stop and report after each.
- Don't invent structure. The architecture doc specifies module names and signatures.

## Hard rules everywhere in this repo

- **No real customer data.** Not in samples, fixtures, idea write-ups, or examples.
  Invented organisations and people with realistic *shapes*. See `docs/GROUND-RULES.md`.
- **No secrets in files.** Environment variables only.
- **Don't write demo material that targets a production system.** Mocks and test tenants.
- If asked to do something that breaks `docs/GROUND-RULES.md`, say so rather than doing it.

## Style for writing in this repo

- Markdown. Short sections, tables where they earn it, no filler.
- Plain claims over hedged ones. If something is uncertain, say what would resolve it.
- Numbers wherever possible, and mark estimates as estimates.
