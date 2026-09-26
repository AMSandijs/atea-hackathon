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

## Product workflows

Airlock shares one local detection, classification, sanitization, approval, and restore
core across two distinct cloud-assisted workflows. They are not interchangeable:

1. **Standalone sanitized request:** the CLI accepts a prompt and optional file, shows a
   checkpoint, sends only approved sanitized text through Airlock's configured gateway,
   then restores known stand-ins in the response locally. `gateway.py` owns this outbound
   request. If the gateway is not configured, the local echo is for offline testing only.
2. **Azure investigation with Copilot:** the operator prepares an approved sanitized
   case and private alias scope. Copilot reads approved context through the local MCP
   server, requests bounded Azure reads, and reasons over released sanitized evidence.
   The local planner proposes a typed read; the deterministic broker runs the fixed
   adapter after local query approval. The result is sanitized and needs a second local
   approval before MCP can return it. Copilot itself calls its cloud service; that
   traffic is not sent through `gateway.py` and is not intercepted by Airlock.

Secrets are blocked rather than replaced in either workflow. The answer or approved
evidence can be restored locally using the private map. The sanitization boundary covers
only data routed through Airlock; it cannot protect content sent through another enabled
Copilot tool or pasted directly into a cloud prompt.

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

1. **CLI** — standalone `scan`/`ask` plus case, scope, capture, and one-turn investigation
   commands. The exact command set is in `airlock --help`.
2. **Local MCP server** — exposes approved sanitized case/evidence reads and the narrow
   Copilot-to-GUI request/status handoff. It uses stdio and does not open a listener.
3. **Local GUI** — supervises private scope creation, per-query approval, result review,
   and Copilot-requested reads. This is a trusted local control surface, not a chat UI.
4. **Clipboard guard** — an original stretch idea; not implemented.

## Copilot Azure investigation pilot

For GitHub Copilot in VS Code, Airlock is a local, intentionally invoked MCP tool.
The operator approves a case scope and sanitized evidence. Copilot reasons over stable
aliases, then asks Airlock for the next bounded read. A local AI planner turns that
request into a typed proposal; the local broker checks the case scope, resolves aliases,
and executes only a fixed read operation. Airlock sanitizes the result and asks the
operator before releasing it to Copilot. This loop can repeat across related VMs,
Application Insights, Logic Apps, and database telemetry. The operator restores the
final answer locally.

The Copilot prompt and every enabled tool output are part of the cloud model context.
Therefore the prompt must contain no customer identifiers, and direct Azure MCP,
portal/browser, terminal, file-reading and other tools that can expose the customer
environment must be disabled for the protected investigation. An Airlock MCP tool
cannot sanitize data another enabled tool or the user already sent to Copilot.

The local planner never receives a shell, a generic Azure command tool, or permission
to approve its own request. It can propose only an enumerated operation, an alias in
the approved case, and bounded parameters. The broker owns the local Azure identity,
original names, command construction, scope enforcement, and output release. Model
proposals are untrusted even when they conform to a JSON schema. Raw Azure output stays
local; secrets block release, and uncertain findings remain visible for operator review.

The T13–T20 milestones implement the typed planner, fixed read broker, separate result
release, CLI/GUI supervision, and one-at-a-time Copilot-to-GUI handoff. The T21
investigation evaluation is in progress. Automated Azure calls are mocked; live Copilot,
live local-model planning, and live-tenant behavior remain unverified. See
[`BUILD-PLAN.md`](BUILD-PLAN.md) and [`EVAL.md`](EVAL.md) for status and test boundaries.

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

Treat this as a positioning hypothesis, not a verified claim that no competing product
does similar work. Before presenting comparisons, verify the current capabilities of the
named products. A supportable project claim is narrower: *Airlock's goal is to show the
approved sanitized evidence crossing its MCP boundary, while keeping the original map
and raw Azure response local.*

## Original standalone-gateway success criteria

- End-to-end path works: text in, checkpoint, cloud call, rebuilt answer out.
- `block` tier genuinely aborts.
- Eval produces four numbers: recall, precision, answer-quality delta, added latency.
- Policy lives in readable YAML and can be shown on screen.
- Demo runs from a recording, not live.

The current Azure/Copilot pilot has additional milestone criteria in `BUILD-PLAN.md`;
the original standalone-gateway criteria above do not demonstrate the Copilot
investigation loop by themselves.
