# Spec — Local Attachment Clerk

## The problem

Attachments for supplier invoices arrive by email. The AP clerk downloads them, opens
Basware, finds each invoice, and adds attachments one at a time through a modal dialog
that takes one file per cycle. Up to 8 such emails a day.

The tedious part is the clicking. **The expensive part is shape B**: when one email
carries several invoice numbers and a pile of files, the clerk has to open each invoice
in Basware to work out which attachment belongs where.

## Why it must be local

- The automation runs inside the clerk's own authenticated browser session, by definition.
- The input is a corporate mailbox carrying supplier invoices: vendor names, bank details,
  amounts, occasionally personal data. Routing that through a cloud model is a legal
  conversation, not a hackathon demo.

## Decisions that are not negotiable

### Email comes from local Outlook, not Graph

Microsoft Graph needs an app registration, admin consent and a mailbox permission review
that will not be approved in time, and it moves mail content through a cloud API, which
undercuts the premise. Read Outlook on the desktop through COM instead: local, needs
nobody's permission, and it matches the mental model the clerk already proposed — a
designated folder the agent empties.

Flow: clerk drags mail into `Basware queue` (or a rule does it) -> agent reads that
folder -> on success the mail **moves** to `Basware done`. Reversible. Never deleted.

A `--from-folder` mode reads saved `.msg`/`.eml` files instead, so team members without
Outlook desktop can still develop and test.

### Signature images are attachments too

Every corporate email carries inline logos as attachments. Filter by size, by extension,
and by whether the part is referenced as an inline image in the HTML body. Without this,
the first demo attaches someone's email signature to an invoice.

### Never automate the OS file dialog

Playwright sets the file directly on the `<input type=file>` element. The Windows Open
dialog never appears. This is the single most important technical decision in the build:
it is the difference between a demo that works and one that does not.

### Attach to an authenticated browser

Do not script SSO. The clerk launches Edge once with `--remote-debugging-port=9222` and
signs in by hand; the agent connects over CDP.

### A human approves the plan

The agent produces a plan — *these 14 files go to these 6 invoices, with these
descriptions, and this one is flagged* — and a human hits go. At 8 emails a day this is
a **batch** screen: the queue is drained on a timer and the clerk approves a morning's
worth in one pass, rather than being interrupted eight times.

## Pipeline

1. **Pick up the mail** — Outlook COM, save attachments, keep the body, move on success.
2. **Read the email body** — extract every invoice number mentioned, in order, with
   context. Regex for the clean cases, model for the twenty ways suppliers write the
   same thing. List length decides shape A or shape B.
3. **Read each attachment** — text layer via pypdf, OCR fallback for scans, one model
   call per file into a fixed schema.
4. **Map attachments to invoices** — deterministic first: an attachment carrying an
   invoice number from step 2 is matched and done. Only leftovers reach the model.
5. **Look up what is missing** — read-only pass in Basware: open each candidate invoice,
   read vendor and total, resolve. Nothing is written in this pass.
6. **Describe and check** — write the Description field, flag any document whose total
   contradicts the invoice it was matched to.
7. **Approve, then file** — plan on screen, human approves, driver files each one and
   verifies the attachment count moved. Flagged items are never filed silently.

## The business case

| If an email takes | Per week | Per year, one clerk |
|---|---|---|
| 3 min | 2 h | ~11 working days |
| 5 min | 3 h 20 | ~18 working days |
| 8 min | 5 h 20 | ~29 working days |

Volume is settled at up to 8/day. Minutes-per-email is the multiplier still to be
measured — have the clerk time five real ones. Also worth knowing how many people in
the AP function do this; the per-person figure is the unit, the team figure is the slide.

8/day also settles the hardware question: roughly 30 document reads a day, a few minutes
of CPU spread over working hours. **This does not need a GPU.**

## Open questions to resolve before the build

- Exact selectors for the Add attachment modal, and the file-size ceiling it states.
- Whether automating Basware's UI is permitted under the vendor agreement.
- Explicit agreement from the mailbox owner before pointing anything at real mail.
