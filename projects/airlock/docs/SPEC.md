# Spec — Local AI Airlock

## The problem

Regulated customers will not put their data into a cloud AI assistant. The current
answer is that they do without. Existing controls all answer *no* (block the file,
block the transfer, block the push) or answer *trust us* (contractual assurance that
the vendor will not train on it). None of them produce a version of the payload that
the work can continue with.

## The premise

**The thing that decides what is safe to send cannot itself be a cloud service.**
Detection has to run on the machine. That is not a preference, it is the definition.

This is why the project is local-AI rather than local-AI-flavoured, and it is the line
the presentation opens with.

## What it does

Text goes in — a pasted payload, a file, a prompt. Every piece of customer-identifying
material is found and replaced with a stand-in. Secrets are stopped rather than replaced.
The sanitized text goes to whichever cloud model. The answer comes back full of
stand-ins and is rebuilt locally with the real values.

### Worked example

On the laptop:

```
/subscriptions/8f4c2b91-3d07-4a1e-b8c2-77e3a9d61f04
  /resourceGroups/nordbro-prd-rg
  /providers/Microsoft.Web/sites/qconv-inhouse-prd

STORAGE_KEY=Xo9vK2mA7pQ1sR4tU6wY8zB0cD3eF5gH
host: nordbro-rmq-prd.westeurope.cloudapp.azure.com
owner: lars.olesen@nordbro.dk
```

On the wire:

```
/subscriptions/3a7e1f04-9b21-4c68-a0d5-12ef7b34c9a8
  /resourceGroups/alpha-prd-rg
  /providers/Microsoft.Web/sites/bconv-inhouse-prd

STORAGE_KEY=[BLOCKED - rotate this key]
host: alpha-rmq-prd.westeurope.cloudapp.azure.com
owner: person01@example.invalid
```

Three decisions are visible in that diff, and they are the design:

1. The GUID became **another valid GUID**, not `TENANT_01`. A malformed payload makes the
   cloud model reason about the wrong thing and produce confident false findings.
2. The resource name kept its **Azure naming shape** — segment count, separators, the
   `-prd` suffix — so the model can still reason about conventions.
3. The storage key was **not pseudonymized**. It was stopped, with a rotation warning.
   A key that has already been pasted somewhere is an incident, not a confidentiality
   question.

## Three tiers, not two

Most naive versions of this are binary. The useful version sorts every finding into one
of three buckets, because the right response to a leaked key and a leaked hostname are
not the same response.

| Tier | Behaviour | Examples |
|---|---|---|
| `block` | Never sent, not even as a placeholder. Request is refused; user is told to rotate. | API keys, connection strings, SAS tokens, private keys, passwords, bearer tokens |
| `swap` | Replaced with a structure-preserving deterministic stand-in, mapped in the local vault. | subscription and tenant GUIDs, resource names, hostnames and FQDNs, public IPs, organisation names, person names, emails, IBANs, national ID numbers |
| `pass` | Goes out untouched. | Azure service names, SKUs, regions, API versions, error codes, generic code, anything in the public docs |

**Over-redaction is a real failure mode.** If the sanitized prompt is so scrubbed that
the cloud answer gets worse, nobody uses this twice. The `pass` tier exists to be
generous, and answer-quality delta is a tracked metric (`docs/EVAL.md`).

## Checkpoint, not silent filter

The question that will be asked is *how do you know it caught everything?* There is no
honest answer in which recall is 100%, so the product must not depend on it being 100%.

**A silent filter that misses one secret is worse than nothing, because it manufactures
confidence.** The airlock shows what it found, what class each finding landed in, what
is about to leave, and what it is unsure about. A human approves. That makes it a
control a security officer can sign off, rather than a promise.

This is a product requirement, not a UX preference. Do not add a `--yes` flag that
skips the checkpoint by default; if one exists at all it is opt-in per invocation and
logged.

## Front doors

Three ways in, one core:

1. **CLI** — `airlock scan <file>` and `airlock ask <prompt> [--file ...]`. Build first;
   it is the only one you cannot demo without.
2. **Local MCP server** — tools the assistant calls on purpose. Legitimate integration
   point, no interception.
3. **Clipboard guard** — warns when sensitive text is copied and a browser AI tab takes
   focus. Best demo moment, lowest priority to build.

## Why not what already exists

Have an answer ready for each; verify current capabilities before presenting, because
these products move.

| Control | What it does | Why it isn't this |
|---|---|---|
| Copilot content exclusions | Admin marks paths Copilot won't read | Whole files, by path, all or nothing. No help for a file that is 95% fine, or anything pasted. |
| Purview / DLP | Policy at a service boundary; blocks or audits | Its answer is stop. It does not produce a payload the work can continue with. |
| Secret scanning / push protection | Catches credentials at the git boundary | Different boundary, and too late — the model saw it long before the push. |
| Self-hosted model | Keeps everything in-tenant | Legitimate, different trade: gives up frontier capability for privacy. This keeps both. |
| "No training on your data" terms | Contractual assurance | A paper control. The data still crossed the boundary, which is the objection. |

The sentence to rehearse: *every existing control answers no, or answers trust us. This
is the only one that transforms the payload so the answer can be yes — and here is
exactly what left the machine.*

## Success criteria for the weekend

- End-to-end path works: text in, checkpoint, cloud call, rebuilt answer out.
- `block` tier genuinely aborts.
- Eval produces four numbers: recall, precision, answer-quality delta, added latency.
- Policy lives in readable YAML and can be shown on screen.
- Demo runs from a recording, not live.
