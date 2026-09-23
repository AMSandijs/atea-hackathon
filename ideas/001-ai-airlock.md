# 001 — AI Airlock

**One sentence:** a local redaction gateway that lets people use cloud AI on data that
currently isn't allowed anywhere near it.

**Status: BUILDING.** Full spec in `projects/airlock/`.

---

## The problem

Regulated customers won't put their data into a cloud AI assistant, so they do without.
Every existing control answers *no* (block the file, block the transfer) or *trust us*
(contractual assurance). None produce a payload the work can continue with.

## What it does

Text in — a file, a payload, a prompt. Customer-identifying material is detected locally
and swapped for structure-preserving stand-ins; secrets are blocked outright rather than
swapped; the sanitized text goes to a cloud model; the answer comes back and is rebuilt
locally with the real values.

## The four questions

**1. Is the AI load-bearing?** Partly, and be honest about it. Most detection is regex,
format checks and entropy — deliberately, because that's what makes it fast on a CPU
laptop. The model handles the fuzzy remainder: is this token an organisation, is this a
person, and a second-opinion pass over the sanitized output. Remove it and recall on
prose falls over.

**2. Why must it run locally?** This one is as strong as it gets: *the thing that decides
what is safe to send cannot itself be a cloud service.* Not a preference — a definition.

**3. What's the 90-second demo?** Three panes: what you typed, what actually left the
laptop, what came back rebuilt. Plus the blocked-key moment, plus four measured numbers.

**4. Who has this problem, and what's the number?** Weakest answer of the four, and the
gap we need to close: we have no named customer and no number. **One attributed sentence
from an account manager about a specific engagement where cloud AI was ruled out is the
highest-value thing anyone can fetch before Friday.**

## Known weaknesses

- **Recall is never 100%**, and someone will ask. Answered by design rather than denial:
  it's a visible checkpoint, not a silent filter, because a filter that misses one secret
  manufactures confidence. Backed by a measured recall number with the misses shown.
- **Over-redaction degrades the cloud answer** and people switch it off. Tracked as a
  metric; if an entity type keeps causing degradation it moves to the `pass` tier.
- **Crowded lane** — see below.
- Demo value is partly invisible: it's measured in what didn't happen.

## Who else builds this?

Probably several teams. Privacy is *the* headline benefit of local AI, so a redaction
gateway is the single most obvious thing to build at this event. Our differentiation is
depth, not novelty: three-tier classification rather than binary, structure-preserving
swaps rather than `TENANT_01`, working re-hydration, and — above all — an eval with
recall, precision, quality delta and latency. With a Director Cloud & DevOps judging,
"we measured it, here are the misses" beats a polished demo that claims perfection.

## Verdict

**Build** — decided 19 Sep. See `DECISIONS.md` for the reasoning, including why this beat
002 on this particular panel.
