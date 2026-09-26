# Copilot-to-GUI investigation handoff — design and implementation record

This document records the T19 transport/safety decision and T20 implementation
criteria for the Airlock Azure investigation loop. T20 is implemented in the repository;
T21 adversarial, multi-resource evaluation is now in progress. Check
[`BUILD-PLAN.md`](BUILD-PLAN.md) for current status and [`EVAL.md`](EVAL.md) for the
evaluation commands and boundaries. Continue from T21; do not repeat the completed
T19/T20 work unless a review or test identifies a specific gap.

## Desired user experience

1. The operator starts Airlock's local GUI and opens an approved case with a private,
   approved alias-to-resource scope.
2. Copilot reads the approved sanitized case and asks Airlock for one more investigation
   read using only the case ID and an alias-only goal.
3. Airlock's local planner proposes one typed operation, target alias, and bounded time
   window. It never proposes shell text, KQL, arbitrary URLs, or mutations.
4. The local GUI shows the actual Azure target and fixed read for explicit operator
   approval. Only then does Airlock's deterministic broker resolve the real ID and run
   the fixed read using the operator's local Azure identity.
5. Airlock sanitizes the result locally. The GUI shows raw-local and sanitized text
   separately and requires a second approval. A block-tier result can never be released.
6. Copilot receives only an opaque request/evidence ID and reads approved sanitized
   evidence through the existing `read_evidence` tool. It can then request another
   bounded read. Each read repeats both approvals.

The local model is the intent-to-typed-proposal planner and may assist with local
sanitization. It is **not** the shell/Azure command executor or approval authority.
The deterministic broker retains Azure identity, real resource IDs, scope enforcement,
fixed command construction, and execution. This keeps the project within the trust
boundary already specified in `SPEC.md` and `AGENTS.md`.

## Non-negotiable safety properties

- The Copilot-facing request accepts only an approved case ID and a natural-language
  goal naming approved aliases. It accepts no resource ID, command, KQL, URL, operation
  override, approval value, or file path.
- The local planner may return only the existing typed proposal. Its output is
  untrusted; the broker reloads and checks case, scope, alias, operation, expiry, and
  time bounds immediately before execution.
- Query approval and sanitized-result approval are independent, trusted-local GUI
  decisions. Neither Copilot nor either model can supply them.
- One request causes at most one fixed read. No automatic multi-query loop runs behind
  the user's back; Copilot must reason and explicitly request the next read.
- Raw Azure results and reverse maps never enter MCP arguments/results, request-queue
  files, logs, or Copilot context. Only explicitly released sanitized evidence is
  readable through `read_evidence`.
- Block-tier findings, cancellation, timeout, stale scope, invalid proposal, UI failure,
  GUI shutdown, or queue corruption fail closed. A request cannot be replayed to cause
  a second read.
- No network listener, general chat service, arbitrary tool execution, live Azure test,
  or Copilot traffic interception is added.

## T19 — Define the MCP-to-GUI handoff contract

Do this design/spike task before implementing the loop. Read `AGENTS.md`, `SPEC.md`,
`ARCHITECTURE.md`, `BUILD-PLAN.md`, and inspect the current MCP server, planner, broker,
investigation, case store, GUI, packaging, and MCP configuration.

### Recommended design

Use a short-lived, per-user local request queue in Airlock's existing private case-data
area; do not add a TCP/HTTP listener. The MCP process validates the approved case,
loads only alias/operation capabilities, and asks the local planner for one typed
proposal. Persist **only** the case ID, random request ID, typed proposal, timestamps,
and status—not the Copilot goal, real IDs, raw Azure result, or reverse map. Treat every
queue record as untrusted when the GUI consumes it. Use atomic file replacement/claim,
strict ID/path validation, a small payload cap, a short configurable expiry, and cleanup
of terminal records. Confirm the case-data directory is local and protected by the
current user's OS permissions; do not place queue state in the repo or a synced/shared
folder.

The GUI polls and claims at most one request at a time. It displays the real target only
in local query approval, then uses the existing fixed broker and result-release path.
The MCP process can read request status, but evidence remains accessible only through
the existing approved `read_evidence` implementation. A stale, malformed, expired,
duplicate, or already-claimed request must not cause an Azure read.

Before choosing this mechanism, verify that the existing case directory and process
lifecycle support it safely on the target Windows setup. If the queue cannot meet the
local-only, permission, or replay requirements, document the blocker and present a
safer alternative (for example, a host-supported MCP user-elicitation flow) before
coding. Do not silently substitute a network service.

### Tool/API contract to document in `ARCHITECTURE.md`

Keep the first public MCP surface narrow; names may be adjusted in the T19 decision, but
the shapes and trust rules should remain:

```text
request_investigation(case_id, goal)
  -> {status: "proposal_rejected"}
   | {request_id, status: "queued"}

investigation_status(case_id, request_id)
  -> {status, evidence_id?}

read_evidence(case_id, evidence_id)
  -> approved sanitized text only
```

`request_investigation` must not return a real resource ID or raw proposal details that
are unnecessary to Copilot. It plans locally and queues exactly one validated typed
proposal. The GUI presents the proposal and resolves it through the broker. The status
tool returns only a small allow-listed status and, after successful release, an evidence
ID. Copilot then calls `read_evidence` as it does today.

Document a finite state machine, for example:

```text
queued -> claimed -> awaiting_query_approval -> running
       -> awaiting_result_review -> released
       -> denied | rejected | blocked | failed | expired | cancelled
```

Terminal states are immutable. A request ID is random, case-bound, validated, and
single-use. MCP retries must not enqueue a second active copy for the same case. GUI
absence or shutdown expires/denies requests; it never approves implicitly.

Also document the local planning/execution split needed to keep the existing CLI
working while the MCP process plans and the GUI executes. The proposed contracts are:

```python
plan_investigation(case_id, goal, policy, directory=None) -> QueryProposal

run_investigation_proposal(
    case_id,
    proposal,
    policy,
    *,
    approve_query,
    approve_result,
    allow_rules_only=False,
    directory=None,
) -> InvestigationTurn

run_investigation_turn(...) -> InvestigationTurn  # compose both for current CLI/GUI use
```

`plan_investigation` reads only approved aliases/operations and asks the loopback model
for one typed proposal. `run_investigation_proposal` treats even a typed queue entry as
untrusted and delegates final authorization to the existing broker. Finalize names and
types in `ARCHITECTURE.md` during T19 before coding.

**T19 outcome (26 Sep 2026):** the recommended file queue was kept.
Final names and shapes are in `ARCHITECTURE.md` ("Copilot-to-GUI request handoff").
Deviations from the sketch above: the MCP request tool may also return `busy` (with
the active request ID) and `supervisor_unavailable`; the status tool may return
`unavailable` (transient) and `unknown` (invalid/cross-case); records carry separate
`claim_by` and `deadline_at` times; and a supervisor claims only requests created
after it started. Spike: `spikes/t19_handoff/` (run explicitly with pytest).

### T19 acceptance

- The transport choice, directory/permission assumptions, request state machine, typed
  proposal schema, expiry, duplicate handling, cancellation, and tool contracts are
  recorded in `ARCHITECTURE.md` before implementation.
- A small offline spike proves atomic enqueue/claim/status behavior and rejects malformed,
  cross-case, expired, duplicate, and replayed IDs. The spike does not call Azure.
- This plan records the ordered T20 implementation criteria below, and `BUILD-PLAN.md`
  links to it. Stop and report the design decision and tests; do not start T20 in the
  same task.

## T20 — Implement one Copilot-requested supervised read

1. Separate the existing investigation pipeline into a local planning step and an
   execution step that accepts a typed proposal. Preserve the current CLI/GUI behavior
   by having their existing one-turn API compose these steps.
2. Add the MCP request/status tools using only the T19-approved local transport. Validate
   the approved parent case and alias-only goal; run the local planner using that case's
   approved alias/operation capabilities; reject invalid or out-of-scope proposals
   before enqueue. Do not persist the free-text goal.
3. Add GUI polling/claiming on the UI event loop. Run broker/sanitizer work off the UI
   thread; the local planner runs in the MCP request handler. Reuse the existing
   approval bridge, fixed broker, and `release_evidence` path; do not duplicate
   authorization or sanitization logic.
4. Show local progress for the pending request and its real query approval. Keep the
   existing side-by-side result review and block guard. On successful release, write
   only the evidence ID/status to the queue; MCP reads the text through `read_evidence`.
5. On cancel/close/expiry, resolve pending work as denied. If an already-approved Azure
   read finishes after closure, do not release its result. Keep status responses generic
   and free of Azure output, identifiers, exception text, or mapping data.

### T20 acceptance

- A mocked end-to-end test starts with an MCP alias-only request, locally plans one
  typed read, routes it to the GUI approval path, mocks one Azure adapter call, reviews
  and releases sanitized evidence, and lets MCP read only that approved evidence.
- Tests prove query denial means zero adapter calls; result denial/block means no
  evidence; a successful turn performs exactly one fixed read; and an invalid alias,
  operation, range, case, status ID, or proposal cannot bypass broker checks.
- Queue contents and all MCP responses are checked for real IDs, raw Azure text, secrets,
  and reverse mappings. Repeated status polling does not rerun work; replay/duplicate,
  expiry, cancellation, GUI unavailable, and restart paths fail closed.
- Existing CLI and GUI behavior remains covered. Full pytest, Ruff, and format checks
  pass. All Azure calls are mocked; stop and report after T20.

## T21 — Adversarial evaluation and demo readiness

**Status (27 Sep 2026): in progress.** The evaluation harness and tests are present in
the current working tree; acceptance is not complete until the checks run and findings
are recorded.

- Add invented multi-resource investigations that require successive reads across VM
  CPU, Application Insights, Logic Apps, and SQL metrics. Measure useful evidence,
  missed/over-redacted identifiers, latency, and number of human approvals per turn.
- Add adversarial cases for prompt injection in Azure text, secret-like values, unknown
  customer identifiers, alias confusion, malicious/oversized queue records, forged
  status, timeouts, retries, and GUI restart. Verify raw content never reaches MCP.
- Run the tests and seeded detector evaluation locally. Document known gaps and exact
  demo limitations; do not describe seeded tests as proof of arbitrary customer-data
  privacy.
- Only after offline acceptance, propose a separate read-only Azure canary using
  invented/test resources and explicit operator authorization. Do not include live
  Azure setup or fault injection in T19–T21.

## Agent handoff instructions

Work from the Airlock project directory and follow `AGENTS.md`. Continue T21 only: review
the existing investigation evaluator and tests, use invented fixtures and mocked Azure
responses, run pytest and Ruff, and report measured output plus anything still
unverified. Update `ARCHITECTURE.md` before changing a missing contract. Do not contact
Azure or claim live Copilot/model validation based on mocked tests. Preserve unrelated
working-tree changes and do not commit or push unless explicitly requested.
