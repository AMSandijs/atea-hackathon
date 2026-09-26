# T21 — Adversarial evaluation of the Copilot investigation loop (26 Sep 2026)

**Bottom line:** this prototype is **not ready for customer data or a live Azure canary**.
The seeded investigation run found that two of four read types do not release useful
evidence (F2, F3), common resource names can be blocked (F1), and a resource name mapped
inside an ID can remain in prose (F5). Several adversarial checks demonstrate useful
fail-closed behavior, but the current full suite is not green; do not summarize the
adversarial suite as passing. These issues need resolution before a canary.

**Latest verification during the documentation pass (26 Sep 2026):** full pytest reported
215 passed, 4 xfailed, and 3 failed. Failures include acceptance of an extra `command`
field in a planner proposal, an extra `kql` field in a queue record, and the associated
adversarial expectation. `ruff check .` reported three findings in the in-progress T21
files. These results supersede any earlier targeted-run summary below.

**T22 update (27 Sep 2026):** that 3-failure run coincided with a deliberate mutation
check that briefly loosened the planner schema (`extra="forbid"` → `"ignore"`) to prove
the tests catch it; the failing tests are exactly the ones that change breaks. With the
source restored, those tests pass, and the three Ruff findings were fixed. After the T22
fixes (see "T22 results" below), the full suite is **235 passed, 0 failed, 0 xfailed**,
Ruff is clean, and F1, F2, F3, F5 and F6 are resolved; F4 is resolved by the F3 fix.
The canary still requires explicit operator authorization.

Everything here is offline: invented tenant, faked `az` subprocess, scripted operator.
The local model (LM Studio, `qwen2.5-coder-7b-instruct`, loopback) was used for the
`--with-model` runs. No Azure tenant, Copilot session, or network service was contacted.
These results come from seeded, invented data; they are not evidence of privacy for
arbitrary customer data.

## What was run

| Run | Command | Output |
|---|---|---|
| Detector corpus, rules only | `airlock eval` | `eval/results-2026-09-26.json` |
| Detector corpus, local model | `airlock eval --with-model` | `eval/results-2026-09-26-lm-studio-qwen2-5-coder-7b-instruct.json` |
| Investigation loop, scripted planner | `python -m eval.investigations` | `eval/results-2026-09-26-investigations.json` |
| Investigation loop, local model | `python -m eval.investigations --with-model` | `eval/results-2026-09-26-investigations-lm-studio-…json` |
| Adversarial suite | `pytest tests/test_adversarial.py` | 25 tests |
| Harness invariants | `pytest tests/test_investigation_eval.py` | 7 tests + 4 strict `xfail` pinning F1–F3, F5 |

The investigation harness (`eval/investigations.py`, described in `EVAL.md`) runs the real
MCP tools, planner parsing, queue, supervisor, broker, fixed adapter (including its Logic
App projection), sanitizer, and result gate. Only the `az` process and operator clicks
are simulated. Three invented scenarios, 14 turns: a four-service walk
(App Insights → VM → SQL → Logic App), hostile Azure output plus operator denials, and
alias confusion.

## Results

### Detector corpus (18 seeds, 9 files)

| | Recall | Precision | Local-model latency per eligible file |
|---|---|---|---|
| Rules only | 16/18 (89%) — misses: `Mira` (PERSON), `Meridian Logistics` (ORG) in ticket prose | 16/29 (55%) | — |
| + local model | 18/18 (100%) | 18/31 (58%) | median 2.9 s, worst 21.3 s |

Precision is low: most false positives are extra `HOSTNAME` and `SECRET_UNKNOWN` hits.
The `SECRET_UNKNOWN` ones are block-tier, which is how F1 shows up in the corpus.

### Investigation loop (14 turns)

| | Scripted planner | Local model |
|---|---|---|
| Reached the intended status | 9/14 | 9/14 |
| Acceptable planner outcome | 14/14 (scripted; not a model measurement) | 14/14 (2 with poor time windows, F6) |
| Released / useful | 3 / 3 | 4 / 4 |
| Approvals per released read | 2.0 (query + result) | 2.0 |
| Leaked secrets | 0 | 0 |
| Leaked deterministic identifiers | 1 — case text (F5) | 1 — case text (F5) |
| Leaked prose identifiers | 1 — `Fjordvik Shipping` in a Logic App error | 0 |
| Over-redacted pass tokens | 0 | 0 |
| Injection text reaching Copilot | 1 turn (expected; see gaps) | 1 turn |
| Latency, planning (MCP request) | median 14 ms | median 1.9 s, worst 2.7 s |
| Latency, supervision (excl. Azure and human time) | median 1.9 s, worst 2.8 s | median 1.5 s, worst 3.4 s |

All five turns that missed their intended status failed **closed** (`blocked` or
`failed`, nothing released). Every one traces to F2 or F3.

### Adversarial coverage — latest suite has a failure

- **Prompt injection in goals:** goals without exactly one alias never reach the model.
  Hostile model replies (extra `command` field, unknown operation, a resource ID as
  alias, alias switched, operation/target mismatch, 100,000-minute range) are covered;
  the extra-`command` case currently fails because the proposal is queued.
- **Prompt injection in Azure output:** released as data. Real identifiers inside it are
  swapped, and any follow-up Copilot request still needs fresh approval.
- **Secrets in Azure output:** a connection string, SAS URL, bearer JWT, PEM key, or
  unknown high-entropy token blocks release even when the operator clicks approve;
  status reads `blocked`, and no fragment appears in MCP output, queue, or evidence files.
- **Tampered queue:** an in-scope alias swap shows the *actual* target in the approval
  dialog, and that is what runs. An operation/target mismatch is rejected with no read.
  300 junk records, a directory posing as a record, and an 8 MB record don't prevent a
  valid claim.
- **Forged status:** a record rewritten to `released` with a fake evidence ID is shown by
  `investigation_status` (the file is trusted), but `read_evidence` refuses the
  unapproved evidence and the forged record never triggers a read.
- **Timeouts:** a planner HTTP timeout gives `proposal_rejected`. An `az` timeout inside
  the real adapter gives `failed` with no detail or evidence. An unanswered GUI approval
  times out as `denied` with no read.
- **Retries and restart:** a retry after denial is a new request needing new approval;
  concurrent MCP retries produce at most one read; a restarted GUI never resumes work
  claimed by a crashed one, which then reads `expired`.

The latest full suite did **not** pass: the hostile-model test showed that a proposal
containing an extra `command` field was queued instead of rejected. A malformed queue
record with an extra `kql` field was also treated as valid. Keep these assertions as
release gates and update this report after they pass.

Mutation checks: breaking the release block guard, the planner's strict schema, or the
one-alias rule each makes the suite fail.

## Findings

| # | Finding | Effect | Severity |
|---|---|---|---|
| F1 | The entropy detector flags hyphenated names of 20+ characters as `SECRET_UNKNOWN` (block tier), including inside full resource IDs, because it tokenises on `/`. 8 of 10 realistic naming-convention names are blocked (`contoso-payments-api-prd`, `kv-nordbro-shared-weu-001`, `vnet-hub-westeurope-001`, …). | Any case or read mentioning such a resource cannot be released. | **High** (usability) |
| F2 | Azure's own SQL metric name `physical_data_read_percent` trips the same check. | **Every** `sql_metrics` read is blocked. | **High** |
| F3 | The `AZURE_RESOURCE_ID` stand-in generator raises on App Insights metric IDs (`…/components/x/providers/Microsoft.Insights/metrics/requests/failed`, odd segment count). | **Every** `app_failures` read fails (closed). | **High** |
| F4 | Metric-ID suffixes are treated as resource instances and swapped: `providers/Microsoft.Insights/metrics/Percentage CPU` becomes `providers/Summit.Summit/metrics/Meridian CPU`. | Garbled but harmless; the metric name survives in the `name` field. | Low |
| F5 | A resource name that appears bare elsewhere in the same text (e.g. an alert description) is not replaced, even though the vault already maps it from the resource ID. | The real name reaches Copilot via `read_case`. | **High** (privacy) |
| F6 | The 7B planner gets time windows wrong: "restart VM_1, then show its CPU" → 1 minute; "last 3 days" → 168 minutes. | Safe (bounded, shown for approval) but less useful. | Low |

F1–F3 and F5 are pinned by strict `xfail` tests in `tests/test_investigation_eval.py`,
which will fail loudly once each is fixed, so the marker gets removed.

## Proposed T22 — detector and vault fixes (not started)

1. **F1/F2:** don't treat lowercase, separator-delimited tokens made of dictionary-like
   or naming-convention segments as unknown secrets. For example, require mixed
   case/digits or base64/hex character-class structure, and skip tokens inside an
   already-detected `AZURE_RESOURCE_ID`, but only after the block-tier check that step 5
   of `sanitize` requires. Add Azure metric names to the pass list. Re-run both evals:
   secret recall on the corpus must not drop.
2. **F3/F4:** make the `AZURE_RESOURCE_ID` detector stop at `/providers/Microsoft.Insights/metrics/`
   (and similar extension routes), or make the generator preserve unknown trailing
   extension segments instead of raising or swapping them.
3. **F5:** after resource IDs are swapped, replace other occurrences of names the vault
   already maps anywhere in the same text. This is deterministic and cheap.
4. **F6:** add an explicit unit instruction and examples to the planner prompt; consider
   rejecting a proposal whose range differs from an explicit number in the goal.

Loosening a secret detector trades recall for usability, so the F1/F2 design needs
explicit sign-off.

## T22 results (27 Sep 2026)

T22 was requested by the operator, which covered the F1/F2 sign-off. Contracts are in
`ARCHITECTURE.md` (entropy naming rule, resource-ID boundary, sanitize step 7, planner
time windows).

| Finding | Fix | Evidence |
|---|---|---|
| F1, F2 | Entropy skips lowercase, `-`/`_`-separated tokens whose segments are words (≤16 letters), counters (≤4 digits), or short alphanumerics (≤4). | 0/10 realistic names falsely blocked (was 8/10); SQL reads release. Random lowercase-alphanumeric, hex, vendor-style and mixed-case secrets still flag. |
| F3, F4 | `AZURE_RESOURCE_ID` matches type/name pairs and stops before a nested `/providers/` route. | App Insights reads release; `/providers/Microsoft.Insights/metrics/Percentage CPU` is kept intact. |
| F5 | New sanitize step: other mentions of originals the vault already maps (from the same text or a preloaded case map) are swapped with the same stand-in; not inside longer `[\w-]` tokens; at least 5 characters. | No deterministic identifier in case text or evidence. |
| F6 | The prompt sets a 60-minute default and minutes conversion; a single explicit duration in the goal must match the proposal, and a stated duration above 24 hours is rejected before the model is called. | "restart VM_1…" → 60 min (was 1); "last 3 days" → rejected (was 168 min). |

Re-run after the fixes:

| | Before T22 | After T22 |
|---|---|---|
| Detector corpus, rules only | recall 16/18, precision 16/29 | recall 16/18 (every secret type still found), precision 16/28 |
| Detector corpus, local model | recall 18/18, precision 18/31 | recall 18/18, precision 18/30 |
| Loop, scripted: intended status / released / leaks (det., prose, secret) | 9/14 / 3 / 1, 1, 0 | **14/14 / 6 / 0, 1, 0** (prose leak is the known rules-only gap) |
| Loop, local model: intended status / released / leaks | 9/14 / 4 / 1, 0, 0 | **14/14 / 7 / 0, 0, 0** |
| Loop, local model latency (planning; supervision, excl. Azure and human time) | 1.9 s; 1.5 s median | 1.8 s; 3.1 s median, 7.8 s worst |

Supervision latency rose because more reads now reach the local-model prose sweep
instead of stopping early at a false block.

Full suite: 235 passed. The four T21 `xfail` markers were removed because the tests now
pass. Mutation checks on the new logic: six of seven are caught. The survivor, dropping
the entropy rule's explicit "no uppercase" test, is equivalent, because the segment
pattern accepts lowercase letters only.

The **Known gaps** below still apply. With F1–F6 fixed, the remaining precondition for
the canary is the operator's explicit authorization.

## Known gaps (true after T22 as well)

- **Injected instructions in Azure text reach Copilot as data.** Sanitization swaps
  identifiers; it does not remove instructions. Mitigations: the operator sees the text
  at result review; Copilot can only file alias-only read requests, each needing two new
  approvals; there is no tool that mutates anything. The Investigator agent should be
  told to treat evidence as untrusted data.
- **Prose identifiers depend on the local model.** Rules-only mode missed
  `Fjordvik Shipping`, `Mira`, and `Meridian Logistics`. Rules-only release should stay
  an explicit, discouraged opt-in.
- **`investigation_status` trusts the queue file.** A same-user process can forge a
  status. It cannot forge approved evidence or trigger a read, but it can mislead
  Copilot about progress. The OS account is in the trust base, as documented in T19.
- **Latency excludes Azure and human time.** Real `az monitor metrics list` calls add
  seconds per metric; SQL makes two calls. Planning adds about 2 s with the 7B model.
- **Precision is 55–58%.** Over-flagging trains operators to click through. F1 is the
  largest contributor.

## Demo limitations (as of this evaluation)

- Demo with **VM CPU and Logic App run history only**, or with short resource names,
  until F1–F3 are fixed. SQL and App Insights reads will block or fail.
- Keep resource names out of alert descriptions and other case prose until F5 is fixed,
  or review the case checkpoint carefully.
- Run the demo from the recorded evaluation, not a live tenant (the build plan already
  requires this).
- Do not present seeded recall as a privacy guarantee. Say that recall is not 100%,
  which is why a human approves every query and every result.

## Proposed read-only Azure canary (not executed)

To be run only **after T22 passes both evaluations offline**, and only with the
operator's explicit, written go-ahead:

- **Target:** a disposable subscription containing only invented test resources (one VM,
  one App Insights component, one SQL database, one Logic App) with invented names that
  include realistic naming-convention names (to confirm F1 in the live output shape) and
  planted fake secrets in a Logic App error.
- **Identity:** the operator's own account with **Reader** role on that subscription
  only; no write permissions.
- **Procedure:** one case, one scope, one Copilot-requested read per service through the
  GUI, each with both approvals; capture the raw-versus-sanitized views for review.
- **Pass criteria:** each read releases useful evidence; nothing in MCP output or
  evidence matches the planted identifiers or secrets; the planted secret blocks.
- **Stop conditions:** any unexpected identifier in MCP output, any `az` command other
  than the four fixed reads, or any error text containing Azure output. On a stop,
  delete the case folder and the subscription's test resources.
- **Not in scope:** fault injection, customer tenants, or any write operation.
