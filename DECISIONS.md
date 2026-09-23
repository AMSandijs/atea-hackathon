# Decisions

Written down so we argue once. Newest first. If you want to reopen one, that's fine —
bring the thing that changed.

---

## 2026-09-19 — Build the AI Airlock, not the Attachment Clerk

**Decision:** AI Airlock (001) is the hackathon entry. Attachment Clerk (002) is fully
specced and gets built afterwards.

**Why:** the panel. At least one organiser is a Director Cloud & DevOps, alongside a
strategic advisor. Neither works in accounts payable. The Director is plausibly the
person who already has the Copilot-rollout problem on his desk, which makes the airlock
something he might adopt rather than just assess. The Clerk's ceiling with this panel is
"nicely built, not my world."

**The argument against, which we accepted anyway:** a redaction gateway is the most
obvious idea at a local-AI hackathon and we will probably not be the only team with one.
We're betting that with a technical judge, depth beats novelty — specifically that a
measured recall number with the misses shown beats a polished demo claiming perfection.
That bet is why the eval is not cuttable.

**What would change this:** if the panel turned out to be commercial rather than
technical, the calculus flips and the Clerk's named-stakeholder story wins.

---

## 2026-09-17 — Three tiers, not two, and structure-preserving swaps

**Decision:** findings sort into block / swap / pass, and swapped values keep the shape of
what they replace.

**Why:** a leaked key and a leaked hostname need different responses — a key that's
already been pasted is an incident, so it's stopped rather than pseudonymized. And
replacing a GUID with `TENANT_01` makes the cloud model reason about a malformed payload
and produce confident false findings; replacing it with another valid GUID doesn't.

---

## 2026-09-17 — Encryption is not the mechanism

**Decision:** pseudonymization with a vault, not encryption of the prompt.

**Why:** the cloud model has to *understand* the text to reason about it. Encryption
preserves the information and destroys the meaning; pseudonymization destroys the link
and preserves the meaning. Ciphertext in place of a hostname also tells the model nothing
about it having been a hostname, which degrades the answer.

**Worth revisiting:** format-preserving encryption per finding would give reversibility
without a persisted vault — the ciphertext *is* the mapping, and only the key needs
protecting. If the vault becomes annoying, look there.

---

## 2026-09-16 — No interception of Copilot traffic

**Decision:** CLI, MCP server and clipboard guard are the front doors. No MITM proxy.

**Why:** rewriting Copilot's TLS traffic is fragile, undocumented, breaks on any
extension update, and is almost certainly against GitHub's terms. Inline completions also
have a latency budget a local model cannot meet. Scope is deliberate, bulk context —
chat, file review, pasted payloads — not autocomplete.
