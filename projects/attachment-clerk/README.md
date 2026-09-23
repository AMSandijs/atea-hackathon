# Local Attachment Clerk

Supplier emails arrive with invoice numbers and loose attachments. This agent runs
entirely on the AP clerk's own machine: it reads the mail, works out which attachment
belongs to which invoice, writes a real description for each, and files them into
Basware — including the case where the answer is not in the email.

Built for a local-AI hackathon: kickoff Fri 25 Sep 14:00 CEST, delivery Mon 28 Sep
08:00 CEST (09:00 Riga).

## The workflow, from the person who has it

Up to **8 such emails a day**, roughly 40 a week, around 1,700 a year for one clerk.
Two shapes:

- **Shape A** — one invoice, up to 5 attachments. The email names the invoice. Every
  attachment goes there. No decision to make; this is a loop.
- **Shape B** — several invoices, 1-2 attachments each. *"Then I gotta see individual
  invoice to know which attachment to add."* This is the real work and the reason the
  project needs a model at all.

**Build shape B.** Shape A falls out as the trivial case.

## Constraints

- **CPU-only corporate laptop.** No GPU. 4B-8B quantized model.
- Email is read **locally via Outlook COM**, not Microsoft Graph — see `docs/SPEC.md`.
- Nothing is filed without a human approving the plan.
- Team of 3, ~2.5 working days.

## Start here

| File | What it is |
|---|---|
| `AGENTS.md` | Rules for any AI agent in this repo. Read first. |
| `docs/SPEC.md` | What it does and why, including the decisions that are not negotiable. |
| `docs/ARCHITECTURE.md` | Module contracts, data shapes, algorithms. |
| `docs/BUILD-PLAN.md` | Ordered tasks with acceptance criteria. |

## Quickstart (once T1 is done)

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
clerk pull --from-folder samples/mails       # no Outlook needed
clerk plan  --out plan.json
clerk file  --plan plan.json --target mock   # never --target basware in a demo
pytest
```
