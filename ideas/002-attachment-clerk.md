# 002 — Attachment Clerk

**One sentence:** reads supplier emails locally, works out which attachment belongs to
which invoice, and files them into Basware.

**Status: FALLBACK / AFTER THE HACKATHON.** Full spec in `projects/attachment-clerk/`.

---

## The problem

Raised unprompted by Deivids in Teams on 14 Sep: Basware only lets you add invoice
attachments one at a time. Attachments arrive by email with the invoice number. **Up to
8 such emails a day**, ~40 a week, ~1,700 a year for one clerk.

Two shapes. Shape A: one invoice, up to 5 attachments — the email names the invoice, no
decision to make. Shape B: several invoices, 1-2 attachments each — *"then I gotta see
individual invoice to know which attachment to add."*

## The four questions

**1. Is the AI load-bearing?** Only if you build shape B. Shape A is a for-loop and we
said so early. Shape B is reading documents and deciding where each belongs — genuinely
fuzzy, genuinely AI.

**2. Why must it run locally?** The automation runs in the clerk's own authenticated
browser session by definition, and the input is a mailbox full of supplier invoices —
vendor names, bank details, amounts. Strong, though not as airtight as 001.

**3. What's the 90-second demo?** The strongest of any idea we had. Meaningless filenames
on screen, ask the room which goes where, show the plan, watch files land. Visible things
happening.

**4. Who has this problem, and what's the number?** The best answer of any idea: a named
colleague, a Teams thread, 8/day. Still missing minutes-per-email — someone should time
five real ones.

## Known weaknesses

- Per-event saving is small; the case rests on volume and on the shape B decision cost,
  not on clicking.
- Outlook COM is Windows-and-Outlook-desktop only.
- Needs real mailbox access and a vendor-terms answer before anything is pointed at it.

## Who else builds this?

Nobody. That was its biggest advantage, and it still is.

## Verdict

**Park for the hackathon, build afterwards** — decided 19 Sep. Not because it's weaker
work, but because neither judge lives in accounts payable. The spec is complete and
Deivids still gets his tool. See `DECISIONS.md`.
