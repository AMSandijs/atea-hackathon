# 005 — RPA perception layer

**One sentence:** a local agent watches a folder, classifies and routes what lands there,
and hands structured output to Power Automate or a UiPath queue.

**Status: FOLDED INTO 002.**

---

## The idea

Local AI as the perception layer for RPA. Robots are good at deterministic steps and bad
at "what is this document" — that's exactly the gap a small local model fills, and on a
locked-down VM with no cloud egress it's the only option.

## Why it's folded in

The Attachment Clerk (002) is this pattern with a named person and a real number attached.
Building the generic version as well would have been two projects wearing one hat.

Worth keeping as a framing device, though: *inbox or folder → read → decide → hand off*,
running locally, pointed at any system with a web UI and no bulk import. That's the
generalisation slide if anyone asks how far 002 goes.

## Verdict

**Folded into 002.** Revisit if the Automation Developer work makes it concrete.
