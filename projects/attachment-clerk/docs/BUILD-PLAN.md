# Build plan — Local Attachment Clerk

Work in order. A task is done when its acceptance criteria pass and `pytest` is green.
**Stop and report after each task.**

Saturday evening is a hard feature freeze. Anything not working by then is a roadmap
slide.

---

## T1 — Skeleton, models, CLI stub

`pyproject.toml` with console script `clerk = clerk.cli:app`, the package layout from
`ARCHITECTURE.md`, `config.yaml`, pydantic-validated `config.py`, all dataclasses in
`models.py` with JSON round-trip, and a Typer app with `pull`, `plan`, `file`, `review`
printing parsed arguments.

**Done when:** `clerk --help` lists four commands, a `Plan` round-trips through JSON
without loss, `ruff check` is clean, `pytest` runs.

---

## T2 — Mock Basware page

A static page in `mock/` reproducing the Add attachment modal: a trigger link, a file
input, a description field, Save and Cancel, a visible attachment list that grows, and a
stated size ceiling. This exists **before** the driver so the driver is testable and the
demo is safe.

**Done when:** the page runs from `file://` or a local static server, adding a file
appends it to the visible list with its description, and oversized files are rejected
with a message.

---

## T3 — Mailbox: folder mode first

`mailbox/folder.py` reading `.msg`/`.eml` from disk, plus `mailbox/attachments.py` with
the full filtering rules. Build folder mode before COM so everyone can work regardless of
platform.

**Done when:** a sample mail with 5 attachments and 2 signature logos yields exactly the
3 real documents, every rejection logged with its reason, and a `MailItem` with body text
preserved.

---

## T4 — Document reading

`read/document.py` and `read/llm.py`. Text layer, OCR fallback, `DocFacts` extraction with
the retry ladder, hash cache.

**Done when:** a digital PDF extracts without OCR, a scanned PDF triggers OCR on that page
only, invalid model JSON retries once then degrades to `needs_human` without crashing,
seconds-per-document is recorded, and re-running is served from cache.

---

## T5 — Mail body parsing and shape detection

`read/mail_body.py`. Regex patterns plus the model pass for prose.

**Done when:** a single-invoice mail yields shape A, a multi-invoice mail yields shape B
with all numbers in order of appearance, and invoice numbers embedded in prose are found.

---

## T6 — Matching ladder (deterministic rungs)

`match.py` rungs 1-3 only. No model, no Basware lookup yet.

**Done when:** shape A maps every attachment to the single invoice; shape B maps every
attachment whose own invoice number appears in the mail; everything else lands in
`unmatched`; `source` is recorded per mapping; confidence is 1.0 for exact matches.

---

## T7 — Describe, cross-check, and the review screen

`describe.py` and `review.py`.

**Done when:** descriptions follow the specified format and length limit, an amount
mismatch produces the flag, the batch review renders every mail with items grouped and
flags visible, and rejecting an item removes it from the approved set.

---

## T8 — Filer against the mock, end to end

`basware/session.py`, `selectors.py`, `filer.py`, wired to `--target mock`.

**Done when:** `clerk file --plan plan.json --target mock` files every approved item,
verifies each upload by waiting for the filename to appear, rejects oversized files before
starting, and writes one JSONL line per item. Flagged items are not filed. `--target
basware` refuses without `CLERK_ALLOW_LIVE=1`.

---

## T9 — Outlook COM mode

`mailbox/outlook.py`. Queue folder read, attachment save, move to done.

**Done when:** a hello-world listing of folder subjects works, attachments save to a
working directory, mail moves to the done folder on success, `.Delete()` appears nowhere,
and folder mode still works unchanged for teammates without Outlook desktop.

---

## T10 — Shape B: lookup and model rungs

`basware/lookup.py` (read-only) and `match.py` rungs 4-5. **This is the presentation.**
Give it the time the schedule allocates on Saturday afternoon.

**Done when:** an attachment with no invoice number on it resolves by vendor plus amount
via read-only lookup; genuinely ambiguous cases get the ranked-candidates model prompt and
a confidence score; nothing is written during lookup; below-threshold matches are flagged
rather than filed.

---

## T11 — Real selectors

Replace every placeholder in `selectors.py` with values observed on the real Add
attachment modal, each with a note recording where it was seen. Record the real size
ceiling in `config.yaml`.

**Done when:** selectors carry observation notes and the driver passes a dry run against
a sanctioned test tenant, if one is available.

---

## T12 — Stretch

Only after T1-T11. A timer that drains the queue hourly and batches the morning's plans;
richer HTML review; per-supplier description templates.

---

## Demo checklist (Sunday)

- Open on the Teams message that asked for this.
- Shape B mail on screen: 3 invoice numbers, 5 attachments, meaningless filenames. Ask
  the room which goes where.
- The cost today: opening each invoice by hand, 8 times a day.
- The plan screen: mapped, described, one flagged for amount mismatch.
- The run, against the mock. Recorded, not live.
- Close: nothing left the laptop.
