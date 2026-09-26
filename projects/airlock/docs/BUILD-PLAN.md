# Build plan — Local AI Airlock

## Implementation snapshot (26 Sep 2026)

The repository contains the T1-T9 modules and team-selected Copilot pilot
(approved local cases, an MCP `read_case` tool, read-only single-resource Azure
capture, and local restoration), plus T13's local typed planner, T14's private
case scope/broker authorization gate, T15's fixed read adapters, and T16's separate
local result sanitizer/checkpoint with approved sanitized evidence available through
MCP. The operator-side iterative query/release interaction and GUI are not yet built.
The test suite and invented-data evaluation should be rerun on each laptop; this snapshot
is not a claim that every original task acceptance criterion has been independently
verified. T10's second-opinion pass, T11's paired Copilot answer-quality
measurement, and T12's clipboard/UI extras are **not implemented**. The MCP
server remains a pilot-specific, case-ID-only front door, not the originally
proposed general `scan_text`/`ask_safely` interface. An actual Copilot session and
live Azure collection safety remain unverified; see the README for boundaries.

Work in order. Each task is sized for one agent session. A task is done when its
acceptance criteria pass and `pytest` is green. **Stop and report after each task.**

The Saturday-lunch decision point is real: if T2-T6 are not solid by then, cut T9 and
T10 entirely and ship a measured rule-based gateway. That still wins.

---

## T1 — Repo skeleton and CLI stub

Create `pyproject.toml` (project name `airlock`, console script `airlock = airlock.cli:app`),
the package layout from `ARCHITECTURE.md`, `policy.yaml` with the example content,
`config.py` loading and validating it with pydantic, and a Typer app with `scan`, `ask`
and `eval` commands that currently print their parsed arguments.

**Done when:** `pip install -e ".[dev]"` succeeds, `airlock --help` lists three commands,
`airlock scan README.md` prints the resolved path and the loaded policy version, `ruff
check` is clean, `pytest` runs (even with one trivial test).

---

## T2 — Deterministic detectors

Implement `detect/rules.py` and `detect/entropy.py`. Presidio analyzer plus every custom
recognizer in the architecture table. Each recognizer gets a test with at least two
positives and two near-miss negatives.

**Done when:** `detect(text, policy)` returns correct `Finding` objects with accurate
offsets for a fixture containing a resource ID, a subscription GUID, an FQDN, a public
IP, a connection string, a SAS token, an IBAN and a Latvian personal code. Checksums are
validated, not just shapes — an IBAN with a bad check digit is not a finding.

---

## T3 — Policy and classification

Implement `classify.py`. Unknown entity types default to `swap` and emit a warning.

**Done when:** every entity type in `policy.yaml` maps to its tier, an unlisted type
defaults to `swap` with a warning, and a malformed `policy.yaml` fails at load with a
readable message rather than at first use.

---

## T4 — Vault and structure-preserving generators

Implement `vault.py` with a generator per entity type as specified.

**Done when:**
- The same input always produces the same stand-in, across process restarts, given the
  same key.
- Generated GUIDs parse as valid UUIDs; generated IPs fall in RFC 5737 ranges; generated
  IBANs pass mod-97; generated hostnames keep their real suffix and segment count;
  generated resource names keep separators, segment count and environment suffix.
- `original(stand_in(f)) == f.text` for every entity type.
- Two different originals never collide on one stand-in (test with 10k generated values).
- The vault file is written mode 0600 and contains no key material.

---

## T5 — Sanitize pipeline

Implement `sanitize.py` with the seven-step order from the architecture (model sweep
stubbed out for now — T9 fills it in).

**Done when:** overlapping findings deduplicate longest-match-first; a `block` finding
short-circuits with `text` unchanged and an empty mapping; replacement happens
right-to-left so offsets stay valid; the worked example in `SPEC.md` produces the
sanitized output shown there.

---

## T6 — Gateway, re-hydration, end to end

Implement `gateway.py` and `rehydrate.py`. Wire `airlock ask` end to end.

**Done when:**
- `gateway.send` raises if `blocked` is non-empty.
- Re-hydration passes tests for: exact match, uppercased, title-cased, split across a
  newline inside a code fence, referenced by identifying segment only, and an invented
  neighbour that must be left alone and reported in `unmapped`.
- `airlock ask` produces an `AirlockResult` with `sent`, `received`, the rebuilt answer,
  and per-stage latency.
- A run appends one JSONL line containing no original values.

---

## T7 — Checkpoint

Implement `checkpoint.py` with the `rich` rendering described in the architecture, wired
into `ask` (approve before send) and `scan` (render and exit).

**Done when:** findings are grouped by tier with stand-ins shown, uncertain findings are
visibly marked, the diff of transmitted text renders, blocked findings show the rotation
warning and abort, and rejecting at the prompt sends nothing.

---

## T8 — Eval harness

Implement `eval/score.py` and build the corpus per `docs/EVAL.md`. **Do this before
tuning any detector** — you cannot improve what you have not measured, and building the
corpus first stops you fitting to vibes.

**Done when:** `airlock eval` prints recall, precision, per-entity-type recall, and a
list of misses with file and offset. Results are written to `eval/results-<date>.json`.

---

## T9 — Local model prose sweep

Implement `detect/model.py` against a loopback OpenAI-compatible endpoint (LM Studio
or Foundry Local), with an Ollama fallback selected by `policy.model.provider`.
Structured JSON output, retry ladder, hard span cap.

**Done when:** the model runs only over rule-free prose spans; invalid JSON retries once
then aborts protected case release; evaluation records model sweep latency; recall on
the corpus improves measurably over T8's rules-only baseline, and you can state by how
much.

---

## T10 — Second-opinion pass

Implement `detect/review.py` over sanitized text, surfacing warnings at the checkpoint
only. Never auto-redacts.

**Done when:** it runs post-sanitize, its findings appear as checkpoint warnings, and
the eval reports how many true misses it caught that the primary detectors did not.

---

## T11 — Answer-quality and latency measurement

Extend the eval to run each corpus question twice — through the airlock and directly —
and record both answers for side-by-side judgement, plus added latency per stage.

**Done when:** `airlock eval --quality` produces a table of paired answers and a latency
breakdown, ready to put on a slide.

---

## T12 — Stretch, in this order

Only if T1-T11 are complete and the eval numbers are good.

1. `mcpserver.py` — local MCP server exposing `scan_text` and `ask_safely`.
2. `clipboard.py` — clipboard guard with a focus-change trigger.
3. An HTML checkpoint view instead of terminal rendering.

## Team-selected Copilot pilot (25 Sep)

The team selected the Azure/Copilot workflow. Implement the local approved-case front
door before further cloud-model features: close the raw-prompt gateway leak, prepare a
sanitized case from an exported Azure bundle, expose only approved cases over local MCP,
and restore a saved answer locally. Prove that blocked or rejected bundles never become
MCP-readable. Live Azure collection and resource mutations require separate validation.

## T13 — Local typed query planner (first build slice)

Implement `airlock/planner.py` as a loopback-only LM Studio client that maps a
sanitized alias-only investigation goal and approved case capabilities into one
strictly parsed proposal: operation, target alias and bounded time range. The planner
does not execute Azure commands, mutate case scope, approve a query, or release output.

**Done when:**
- The request uses the configured local model and JSON Schema response format.
- Invalid JSON, extra fields, missing local model, timeout, unknown aliases,
  unsupported operation/target pairs and out-of-range time windows fail closed.
- Unit tests prove only approved aliases and operations can be returned as proposals;
  no Azure CLI call is made by this module.
- Existing `pytest` and `ruff check .` pass.

T13 added a proposal-only local planner. T14 adds private scope and a query authorization
gate; later tasks will add mocked Azure adapters, separate result approval and sanitized
MCP iteration, the local GUI, and finally a supervised disposable-subscription test.

## T14 — Private scope and deterministic broker authorization

Implement a private per-case scope binding validated aliases to supported Azure ARM
resource IDs. Infer the allowed operation from the resource provider/type rather than
accepting an operation list from the model or caller. Require an approved case and
trusted-local operator approval to create scope. Add broker APIs that expose only alias
capabilities to the planner and independently reload/revalidate case approval, scope,
expiry, target, operation, and time range before requiring a separate per-query operator
approval. Successful authorization returns an internal typed capability for a future
fixed adapter; this task does not execute Azure commands or release results over MCP.

**Done when:**
- Only supported, structurally valid ARM resource IDs can be bound; provider/type and
  operation are checked together and aliases are unique.
- Scope creation fails for unapproved cases, absent/rejected approval, invalid duration,
  invalid IDs, or an existing scope. Private resource IDs never appear in `read_case()`
  or planner capabilities.
- Broker authorization fails closed for expired/corrupt scope, rejected proposals,
  unapproved cases, out-of-scope aliases, operation mismatches, and rejected/failed
  operator approval. No Azure subprocess/API adapter is called in this task.
- Tests and `ruff check .` pass. Stop after T14 and report; adapter and result-release
  work remain separate tasks.

## T15 — Fixed Azure read adapters (mocked validation only)

Add the broker's only execution entry point. It must obtain a fresh T14 authorization
and local per-query approval, then dispatch to fixed Azure CLI read operations for VM
CPU, Application Insights failures, Logic App run history, and Azure SQL metrics. Use
only fixed metric names, fixed GET route/API version, bounded time range, and a fixed
record limit; no model-supplied KQL, URL, arguments, or shell text. Keep raw responses
local and out of MCP pending the separate result-sanitization/release task. Do not run
against a live Azure tenant in this task.

**Done when:**
- The broker refuses execution before resolving/invoking Azure if case approval,
  scope, proposal validation, or per-query operator approval fails.
- Each operation maps only to its documented, fixed read command; resource ID and time
  range come from an independently validated authorization capability.
- Output is bounded, Logic run input/output payloads are excluded, and raw results are
  not persisted or exposed to MCP. CLI errors do not echo potentially sensitive output.
- Tests mock the runner for every operation and prove rejection makes no process call;
  no live Azure request is made. `pytest`, `ruff check .`, and formatting for changed
  Python files pass. Stop after T15 and report.

## T16 — Sanitize and separately approve Azure result release

Implement the result-release boundary in `cases.py` and expose only its approved,
sanitized output through a new read-only MCP `read_evidence(case_id, evidence_id)`
tool. Require an approved parent case, cap input at 1 MiB, preserve existing case
aliases, run the local sanitization pipeline, and require a distinct operator checkpoint
after query approval. Rules-only release must be an explicit choice. Persist only
approved sanitized evidence and its separate private reverse-map sidecar; never persist
raw Azure results. Local restoration must use mappings from the case and its approved
evidence. T16 remains offline/mocked and must not query a live tenant.

**Done when:**
- Missing/unapproved parent, oversized input, missing local model without explicit
  rules-only mode, a block-tier finding, rejected approval, and checkpoint errors all
  fail closed without an MCP-readable evidence record.
- Approved evidence is returned by the MCP reader as sanitized text only. Invalid IDs,
  corrupt/unapproved evidence, orphan mapping files, and unapproved parent cases are
  rejected. The raw result and private mapping are absent from public evidence and MCP
  output; restoration can resolve aliases introduced by released evidence.
- Tests demonstrate query approval and result approval are separate; tests and `ruff
  check .` pass, with changed Python files formatted. Do not run Azure against a tenant.
  Stop after T16 and report.

---

## Demo checklist (Sunday)

- Recorded run, not live.
- Wire view showing the exact transmitted bytes.
- The blocked-key moment called out explicitly.
- Four numbers on one slide: recall, precision, quality delta, added latency.
- The honest sentence about recall never being 100%, and why a human approves.
