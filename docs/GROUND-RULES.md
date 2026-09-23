# Ground rules

Short, and not negotiable. These are the things that turn a good demo into an awkward
conversation with someone's manager.

## Data

- **No real customer data in this repo. Ever.** Not in samples, fixtures, screenshots,
  idea write-ups or slides. Use invented organisations and people with *realistic shapes*
  — `nordbro`, `meridian-logistics`, invented person names, GUIDs you generated.
- **No real credentials anywhere.** Environment variables only. If a key ever lands in a
  file or a chat, treat it as compromised and rotate it.
- If you need real data to test something, ask the owner first and say what you'll do
  with it. "I'll delete it after" is not a plan; "it stays on my machine and never gets
  committed" is.
- Assume anything pasted into a cloud AI has left the building. That's the whole premise
  of one of our projects — we should not be the people who forget it.

## Demos

- **Never demo against a production system.** Build the mock. We have one specified in
  `projects/attachment-clerk/`.
- If you want the real system on screen, do a sanctioned run against a test tenant with
  the owner watching, and play the recording.
- Check vendor terms before automating anyone's SaaS UI. Find out *before* Friday so the
  answer is ready when someone asks.

## Claims

- Don't claim a number we didn't measure. "We estimate" is a fine phrase; a made-up
  percentage on a slide is not, and this panel will ask how we got it.
- Show the misses. A team that reports what its tool failed to catch reads as competent.
  A team that claims perfection reads as untested.

## Each other

- Feature freeze means feature freeze. The person who keeps building on Sunday is the
  reason the demo breaks on Monday.
- Disagree early and in writing. `DECISIONS.md` exists so we argue once.
