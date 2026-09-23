# Local AI Airlock

A chamber between the laptop and the cloud model. Customer-identifying material is
detected and swapped locally, secrets are stopped outright, the sanitized text goes
out for cloud-grade reasoning, and the answer is rebuilt with the real names on the
way back in. **The identifying data never leaves the machine.**

Built for a local-AI hackathon: kickoff Fri 25 Sep 14:00 CEST, delivery Mon 28 Sep
08:00 CEST (09:00 Riga), short presentation immediately after.

## Constraints that shape every decision

- Runs on a **CPU-only corporate laptop**. No GPU. Assume a 4B-8B quantized model.
- **Deterministic first.** The LLM only handles what regex and format checks cannot.
- Team of 3, ~2.5 working days. Scope is protected by `docs/BUILD-PLAN.md`.
- The eval (`docs/EVAL.md`) is **not optional** — it is the differentiator.

## Start here

| File | What it is |
|---|---|
| `AGENTS.md` | Rules for any AI agent working in this repo. Read first. |
| `docs/SPEC.md` | What the product is and why. Product decisions, not code. |
| `docs/ARCHITECTURE.md` | Module contracts, data shapes, algorithms. |
| `docs/BUILD-PLAN.md` | Ordered tasks with acceptance criteria. Work through in order. |
| `docs/EVAL.md` | Corpus, metrics, reporting format. |

## Quickstart (once T1 is done)

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
airlock scan samples/incident-bundle.txt
airlock ask "why is this app service throttling?" --file samples/incident-bundle.txt
pytest
```

## Non-goals

Listed in `AGENTS.md` and enforced there. The short version: no chat UI, no browser
extension, no MITM of Copilot traffic, no inline-completion interception.
