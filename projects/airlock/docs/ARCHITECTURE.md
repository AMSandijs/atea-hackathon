# Architecture — Local AI Airlock

Implement against these contracts. If a signature here is wrong or insufficient, change
this file first and say so, rather than improvising in code.

## Module map

```
airlock/
  cli.py            Typer app: scan, ask, eval
  config.py         Loads and validates policy.yaml
  models.py         Finding, Sanitized, AirlockResult dataclasses
  detect/
    rules.py        Presidio analyzer + custom recognizers. Deterministic.
    entropy.py      High-entropy string detection for unknown secret formats
    model.py        Local LLM sweep over prose. Runs ONLY on rule-free spans.
    review.py       Second-opinion pass over already-sanitized text
  classify.py       Finding -> tier, using policy.yaml
  vault.py          Deterministic structure-preserving stand-ins + reverse lookup
  sanitize.py       Orchestrates detect -> classify -> swap
  gateway.py        Sole outbound cloud-model request after sanitization
  rehydrate.py      Restores originals in the cloud answer; reports unmapped
  checkpoint.py     Renders the approval view, collects the decision
  mcpserver.py      Stretch: local MCP server front door
  clipboard.py      Stretch: clipboard guard
  cases.py          Local approved case store; only sanitized case text is readable by MCP
  azure.py          Read-only Azure CLI resource capture, with local identity
  planner.py        Local model proposes one typed, bounded read; never executes tools
  broker.py         Deterministic scope checks and fixed Azure read adapters
  investigation.py  One supervised query/sanitize/release turn; no MCP approval path
  gui.py            Single-user local desktop supervisor; no server or chat UI
eval/
  corpus/           Seeded fixtures (invented orgs, realistic shapes)
  seeds.yaml        Ground truth: what was planted where
  score.py          Computes the four numbers
tests/
policy.yaml
```

## Data shapes (`models.py`)

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Finding:
    entity_type: str      # AZURE_SUBSCRIPTION_ID, HOSTNAME, PERSON, SECRET_KEY, ...
    text: str             # the exact matched substring
    start: int            # offset into the source text
    end: int
    detector: str         # "rules" | "entropy" | "model" | "review"
    score: float          # 0.0-1.0 detector confidence
    tier: str = "swap"    # set by classify.py: "block" | "swap" | "pass"

@dataclass
class Sanitized:
    text: str                        # safe to transmit
    findings: list[Finding]
    mapping: dict[str, str]          # stand_in -> original
    blocked: list[Finding]           # block-tier hits; non-empty means do not send
    low_confidence: list[Finding]    # below policy review threshold; shown at checkpoint

@dataclass
class AirlockResult:
    answer: str                      # rehydrated
    sanitized: Sanitized
    sent: str                        # exact bytes that left the machine
    received: str                    # exact bytes that came back
    unmapped: list[str]              # stand-ins that could not be restored
    latency_ms: dict[str, int]       # per stage
```

## Detection

### `detect/rules.py`

Presidio analyzer with the built-in recognizers plus custom ones. Custom recognizers to
implement, each with its own unit test:

| Entity type | Pattern notes |
|---|---|
| `AZURE_SUBSCRIPTION_ID` | GUID appearing after `/subscriptions/` or a `subscriptionId` key |
| `AZURE_TENANT_ID` | GUID after `tenantId`, `/tenants/`, or in an authority URL |
| `AZURE_RESOURCE_ID` | full `/subscriptions/.../resourceGroups/.../providers/...` path |
| `AZURE_RESOURCE_NAME` | the trailing name segments of a resource ID; also `name:` keys in ARM/Bicep |
| `HOSTNAME` | FQDN, with `*.cloudapp.azure.com`, `*.azurewebsites.net` etc. treated as high confidence |
| `PUBLIC_IP` | IPv4/IPv6 excluding RFC1918, loopback, link-local |
| `CONNECTION_STRING` | `Endpoint=`, `AccountKey=`, `Server=...;Password=`, `DefaultEndpointsProtocol=` |
| `SAS_TOKEN` | `sig=`, `sv=`, `se=` query parameter cluster |
| `BEARER_TOKEN` | `Bearer ey...` / JWT three-segment base64 |
| `PRIVATE_KEY` | PEM armour blocks |
| `NATIONAL_ID_LV` | 11-digit Latvian personal code with checksum |
| `NATIONAL_ID_DK` | 10-digit Danish CPR with date plausibility check |
| `IBAN` | mod-97 checksum, not just shape |

Signature:

```python
def detect(text: str, config: Policy) -> list[Finding]: ...
```

### `detect/entropy.py`

Catches secrets whose format you do not know. Tokenize on non-alphanumeric boundaries,
score Shannon entropy per token, flag tokens above a configurable threshold that are
longer than a configurable minimum and are not in an allowlist (known base64 of public
data, git SHAs, etc.). Emits `SECRET_UNKNOWN` findings. Expect false positives; that is
what the checkpoint is for.

### `detect/model.py`

Runs **only on spans no rule matched**, and only on spans that look like prose (comments,
commit messages, docstrings, ticket text, markdown paragraphs). Its job is the judgement
rules cannot make: is this token an organisation name, is this a person.

- Use structured JSON output, not tool calling. Small models choose tools badly and fill
  schemas well.
- Retry ladder: parse failure -> re-prompt once with the parser error appended. A
  protected case aborts on the second failure; an unprotected diagnostic scan can
  return no model findings.
- Hard cap on span length; chunk longer prose.
- The model endpoint comes from `AIRLOCK_LOCAL_MODEL_URL` and must resolve to a
  loopback address. Foundry Local and LM Studio use `/v1/chat/completions`;
  Ollama uses `/api/chat`. Missing endpoint means the detector is inactive and the
  operator sees a rules-only warning at case preparation.
- Protected case preparation runs the model in strict mode: connection failure or
  two invalid structured responses abort the case before approval or persistence.

```python
def detect_prose(spans: list[tuple[int, str]], config: Policy) -> list[Finding]: ...
```

### `detect/review.py`

The second-opinion pass. Takes already-sanitized text and asks the local model one
question: does anything here still identify a specific organisation or person? Findings
go to the checkpoint as warnings. **Never auto-redact from this pass** — it would hide
the fact that the primary detectors missed something, which is exactly what you need to
see during the eval.

## Classification (`classify.py`)

```python
def classify(findings: list[Finding], policy: Policy) -> list[Finding]: ...
```

Maps `entity_type` to tier via `policy.yaml`. An entity type not listed anywhere
defaults to `swap` and emits a warning — fail safe, not fail open.

## Policy (`policy.yaml`, loaded by `config.py`)

```yaml
version: 1

tiers:
  block:
    - SECRET_KEY
    - SECRET_UNKNOWN
    - CONNECTION_STRING
    - SAS_TOKEN
    - PRIVATE_KEY
    - PASSWORD
    - BEARER_TOKEN
  swap:
    - AZURE_SUBSCRIPTION_ID
    - AZURE_TENANT_ID
    - AZURE_RESOURCE_ID
    - AZURE_RESOURCE_NAME
    - HOSTNAME
    - PUBLIC_IP
    - ORG_NAME
    - PERSON
    - EMAIL_ADDRESS
    - IBAN
    - NATIONAL_ID_LV
    - NATIONAL_ID_DK
  pass:
    - AZURE_SERVICE_NAME
    - AZURE_REGION
    - SKU
    - API_VERSION
    - ERROR_CODE

thresholds:
  model_min_score: 0.55        # below this the model finding is discarded
  review_below: 0.80           # below this it is shown at the checkpoint as uncertain
  entropy_min_bits: 3.6
  entropy_min_length: 20

model:
  provider: lm_studio          # lm_studio | foundry_local | ollama
  name: qwen2.5-coder-7b-instruct
  max_span_chars: 4000

gateway:
  provider: azure_openai       # azure_openai | openai | anthropic
  endpoint_env: AIRLOCK_CLOUD_ENDPOINT
  api_key_env: AIRLOCK_CLOUD_KEY
  model: gpt-4o
```

## Vault (`vault.py`)

The single most important correctness requirement: **the same original must always
produce the same stand-in within a session**, or the cloud model loses coreference and
the answer becomes nonsense.

```python
class Vault:
    def __init__(self, key: bytes, path: Path | None = None, initial_pairs: dict[str, str] | None = None): ...
    def stand_in(self, finding: Finding) -> str: ...
    def original(self, stand_in: str) -> str | None: ...
    def pairs(self) -> dict[str, str]: ...
    def save(self) -> None: ...
```

Derivation: `seed = HMAC-SHA256(key, entity_type + "|" + normalize(text))`, then a
per-type generator consumes the seed. Normalization is lowercase plus whitespace
collapse, so `Nordbro` and `nordbro` map to the same stand-in.

Generators — every one preserves the **shape** of what it replaces:

| Entity type | Generator |
|---|---|
| `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID` | a valid v4 UUID built from the seed |
| `PUBLIC_IP` | an address in `192.0.2.0/24` or `198.51.100.0/24` (RFC 5737 documentation ranges) |
| `HOSTNAME` | replace only the customer-identifying leftmost labels; preserve segment count and the real suffix (`westeurope.cloudapp.azure.com` stays) |
| `AZURE_RESOURCE_NAME` | preserve separators, segment count, casing style and the environment suffix (`-prd`, `-uat`); swap only the identifying token |
| `AZURE_RESOURCE_ID` | retain the `/subscriptions/.../resourceGroups/.../providers/...` structure; replace the subscription GUID, resource group and each resource instance name with the same stand-ins used when those values occur alone |
| `ORG_NAME` | a word from a fixed invented list (`alpha`, `bravo`, `meridian`, ...), stable per original |
| `PERSON` | `Firstname Lastname` from a fixed invented list |
| `EMAIL_ADDRESS` | `personNN@example.invalid` |
| `IBAN` | same country code and length, recomputed valid mod-97 checksum |
| `NATIONAL_ID_*` | same format, recomputed valid checksum, never a real-looking date of birth |

Persistence: JSON at `~/.airlock/vault-<session>.json`, mode 0600. The key comes from
the environment or is generated per session; it is never written next to the vault.

## Sanitize (`sanitize.py`)

```python
def sanitize(text: str, policy: Policy, vault: Vault) -> Sanitized: ...
```

Order matters:

1. `rules.detect` over the whole text.
2. `entropy.detect` over the whole text.
3. Compute spans not covered by any finding; filter to prose-looking spans.
4. `model.detect_prose` over those spans only.
5. Classify deterministic findings and abort immediately if **any** block-tier finding
   exists, even if it overlaps a longer swap-tier finding. Keep text unchanged and the
   mapping empty. This check precedes the local prose model as well.
6. Classify model findings, then deduplicate remaining overlaps — longest match wins,
   then highest score. A finding inside an `AZURE_RESOURCE_ID` is absorbed by it.
7. Replace `swap` findings right-to-left by offset so earlier offsets stay valid.

## Gateway (`gateway.py`)

The only place bytes leave the machine.

```python
def send(sanitized: Sanitized, policy: Policy) -> tuple[str, int]: ...
```

Assert on entry that `sanitized.blocked` is empty; raise if not. Record the exact
transmitted payload for the demo's wire view. Read credentials from the env vars named
in policy; never accept them as function arguments that could be logged.
The gateway sends `sanitized.text` only. It must never append the original prompt, a
file name, or any other unsanitized text to the request.

## Copilot case boundary (`cases.py`, `mcpserver.py`)

`cases.py` prepares a local file with `sanitize`, an explicit checkpoint, and a random
case ID. It persists the approved sanitized text and the reverse map locally. The MCP
server exposes only approved sanitized case/evidence readers. It has no tool for
preparing arbitrary input, reading arbitrary paths, or returning originals. The operator
saves Copilot's answer to a local file and uses `airlock restore` to resolve stand-ins.
The MCP server uses stdio and does not open a network port.

The protected Copilot session must use only Airlock's tool for customer context.
Copilot tool calls and prompts themselves reach GitHub; case IDs are opaque, and
original Azure identifiers must never be supplied as arguments. The Azure collection
adapter is read-only and uses the signed-in user's local identity. Azure CLI requests
go to the customer's Azure tenant and are distinct from the outbound model boundary
managed by `gateway.py`; no raw Azure output is sent to GitHub by the collector.
The collector supports a generic `az resource show` and an optional read-only Azure
Monitor metric query for the same resource. The metric name is supplied locally and
validated before invoking the CLI. Logs and application traces remain export-based.

## Local investigation planner and broker (`planner.py`, `broker.py`)

The local planner accepts a Copilot investigation goal containing case aliases only,
plus a case summary that has already been sanitized. It returns a strict structured
proposal containing exactly one operation, target alias, and bounded time range. The
first implementation supports LM Studio's JSON Schema response format. The parser
rejects malformed output, unknown fields, aliases outside the case scope, unsupported
operation/alias combinations, and ranges outside the configured limit. A model response
is a suggestion, never an authorization decision.

The broker is the only component permitted to resolve aliases or invoke Azure reads.
It rechecks the proposal against a private case scope and fixed service adapter, asks
for operator approval before a query in the supervised pilot, and independently
sanitizes and gates the resulting evidence before MCP can return it. It constructs
argument arrays or fixed API requests from validated typed fields; it never executes
model-generated shell text, arbitrary KQL, generic REST URLs, mutations, or model-selected
extensions. A rejected plan, missing local model, scope mismatch, timeout, or block-tier
finding produces no command side effect and no raw cloud-visible result. Query approval
and result-release approval are separate state transitions.

T14 implements the scope and authorization boundary, not an Azure adapter. The private
`<case-id>.scope.json` file binds opaque aliases to validated ARM resource IDs and a
fixed operation set inferred from each resource's provider/type. Scope creation requires
an explicit trusted-local approval callback and an approved case. The planner receives
only `case_capabilities()` (aliases and operations). `authorize_query()` reloads the
approved case and private scope, checks expiry and the proposal's alias/operation/time
range, and requires a separate trusted-local per-query approval. Only then does it return
an internal `AuthorizedRead` containing the real resource ID for a future fixed adapter.
The callback must be implemented by the local CLI/GUI, never by an LLM or MCP client.
The scope file is private local state, not cryptographic protection against a malicious
process running as the same user; OS account/device security remains in the trust base.
No Azure command is executed by T14, and no query result is made MCP-readable by it.

T15 adds `broker.execute_query()` as the only production path from an untrusted
proposal to an Azure read. It performs the T14 scope and operator checks, then sends
the returned capability to fixed adapter code in `azure.py`. The adapter supports
only `vm_cpu` (`Percentage CPU`), `app_failures` (`requests/failed` and
`exceptions/count`), `sql_metrics` (`cpu_percent`, `physical_data_read_percent`,
`log_write_percent`, `deadlock`, with separate aggregation sets), and `logic_runs`
(HTTP GET of the fixed Logic workflow-runs route). The metric names, HTTP method, API version, interval, and record
limit are constants; time range and resource ID come only from the approved capability.
The Logic App request uses the fixed `StartTime ge` filter and `$top=100`.
No KQL, URL, CLI flag, or shell text comes from the model. Logic run results are
filtered to the approved time window and projected to status/timing/error metadata;
trigger/action inputs and outputs are excluded. Azure responses are capped at 1 MiB.
The command output remains raw local data returned to the local caller and is not
persisted or exposed through MCP in T15. The following result-release task must sanitize
it and obtain separate operator approval before Copilot can receive anything.

```python
execute_query(case_id, proposal, *, approve_query, directory=None) -> str | None
```

The function returns `None` for a rejected proposal or denied approval. Azure failures
are reported without echoing CLI output or resource identifiers. Tests inject/mock the
process runner; T15 does not run a query against a tenant.

T16 adds a separate result-release boundary in `cases.py`:

```python
release_evidence(case_id, raw_result, policy, *, decision=None,
                 approve_result=None, allow_rules_only=False, directory=None) -> str | None
read_evidence(case_id, evidence_id, directory=None) -> str
```

`release_evidence` requires an already-approved parent case, caps raw result input at
1 MiB, sanitizes locally using the same stand-ins for values already mapped by that
case, and obtains a distinct local result approval. The CLI uses the existing local
checkpoint; a desktop caller may supply `approve_result(raw_result, sanitized)` to
present and decide the same candidate. This is independent of query approval. A blocked
result or rejected checkpoint creates no evidence or map file, even if a callback
returns approval. Rules-only processing is refused unless explicitly opted into. On
approval, only the sanitized text and opaque evidence ID are written as the MCP-readable
evidence;
the expanded reverse map is stored in a separate private sidecar. Raw Azure output is
never persisted or logged. `read_evidence` revalidates both the parent case and evidence
approval and returns only sanitized text. MCP exposes it as `read_evidence(case_id,
evidence_id)`; the IDs are format-checked and no paths or real Azure identifiers are
accepted. Local restore merges the case map with maps belonging to approved evidence.
An orphan map from an interrupted write is ignored unless its evidence record exists
and is approved.

The MCP reader does not execute Azure queries or make approval decisions. The local
supervisor calls `execute_query`, presents its raw local result to
`release_evidence`, and only shares the returned evidence ID after a successful local
release. Per-query approval and per-result release approval remain distinct. T16 tests
the release/store/read boundary offline and does not query a live tenant.

```python
create_case_scope(case_id, resource_ids, *, approve_scope, expires_in_minutes=...)
case_capabilities(case_id) -> dict[str, tuple[str, ...]]
authorize_query(case_id, proposal, *, approve_query) -> AuthorizedRead | None
```

Planner response contract:

```json
{
  "operation": "vm_cpu",
  "target_alias": "VM_1",
  "time_range_minutes": 30
}
```

The operation enum and alias enum are derived from the case's approved capabilities.
The broker also validates the relationship between the chosen operation and target;
JSON Schema alone cannot enforce all cross-field policy. Planner prompts, replies, and
raw Azure results are not written to logs. Only sanitized evidence and minimal decision
metadata may enter the case audit record.

## Local supervised investigation turn (`investigation.py`, `cli.py`)

T17 supplies a terminal supervisor for one proposal at a time. A Copilot-generated
goal is manually copied to the local CLI and must name exactly one approved case alias.
The configured loopback planner proposes one operation/alias/time range; the CLI then
shows the real ARM resource ID and exact query to the local operator. Only a local
approval callback reaches `broker.execute_query`. The resulting raw response is passed
to `release_evidence`, which independently sanitizes and checkpoints it. Only a
successful release prints an opaque evidence ID, which Copilot can read with the
existing `read_evidence` MCP tool. The operator repeats this turn after Copilot reasons
over the newly released evidence. This first slice deliberately uses a manual handoff;
it does not let Copilot invoke Azure or supply approval decisions.

```python
@dataclass(frozen=True)
class InvestigationTurn:
    proposal: QueryProposal
    status: Literal["proposal_rejected", "query_denied", "result_not_released", "released"]
    evidence_id: str | None

def run_investigation_turn(
    case_id: str,
    goal: str,
    policy: Policy,
    *,
    approve_query: Callable[[QueryReview], bool] | None,
    result_decision: bool | None = None,
    approve_result: Callable[[str, Sanitized], bool] | None = None,
    allow_rules_only: bool = False,
    directory: Path | None = None,
) -> InvestigationTurn
```

The function loads approved case capabilities, calls `plan_query`, and returns without
Azure access for a rejected proposal. Otherwise it calls `execute_query` with the
trusted local query-approval callback, then `release_evidence` with an independent
result decision. `result_decision=None` uses the existing local terminal checkpoint;
the CLI never accepts a model-provided approval. It does not loop invisibly: each
proposal and result is shown and approved before the next Copilot turn. Errors fail
closed. Offline tests inject the planner response and Azure adapter; no live tenant
query is run.

`airlock scope CASE_ID --alias VM_1 ...` prompts for each full ARM resource ID without
echoing it into the shell command/history, then shows the full targets and collects
local approval before saving scope. Real resource IDs are supplied to the local CLI,
never in Copilot tool arguments. `airlock investigate CASE_ID --goal "... ALIAS ..."`
runs one supervised turn. Rules-only evidence release remains an explicit
`--rules-only` opt-in; local planner availability is still required.

## Local desktop supervisor (`gui.py`)

T18 adds `airlock gui`, a single-user Tkinter desktop interface. It is a UI over the
existing `create_case_scope` and `run_investigation_turn` paths, not another execution
or approval implementation. No HTTP listener or background network service is opened.
The UI accepts an approved case ID, alias-to-resource scope entries, and an alias-only
Copilot goal. Real resource identifiers are masked while entered and displayed only in
the explicit local scope/query approval views. A worker thread runs the planner and
fixed broker read; all UI approvals are marshalled to the main UI thread and default
to rejection on cancellation, window close, or callback failure.

The query dialog shows the operation, target alias, real ARM ID, and time window. The
result dialog shows raw local evidence and the exact sanitized candidate side by side,
lists findings/uncertainty, and offers release only when no block-tier finding exists.
To support that view, `release_evidence` accepts
`approve_result(raw_result, sanitized) -> bool`; the release code enforces the block
guard independently of the GUI callback and persists only after an explicit `True`.
The GUI shows the opaque evidence ID after successful release; Copilot reads it through
the existing MCP tool. The operator continues by pasting Copilot's next alias-only goal.
No customer data or reverse mapping is logged or sent to the GUI over a network. Tests
use mocked planner/Azure responses and exercise approval dispatch without requiring an
interactive desktop or live Azure tenant.

## Re-hydration (`rehydrate.py`)

Harder than redaction, and the part most implementations get wrong.

```python
def rehydrate(answer: str, mapping: dict[str, str]) -> tuple[str, list[str]]: ...
```

The cloud model will not hand your stand-in back verbatim. Handle at minimum:

- **Case changes** — uppercased in a heading, title-cased in prose. Match
  case-insensitively.
- **Line-break splitting** — a long stand-in wrapped inside a code block or a table cell.
  Normalize by collapsing whitespace inside candidate matches before comparing.
- **Partial use** — the model refers to `alpha-rmq-prd` when the stand-in was the full
  FQDN. Index stand-ins by their identifying segments too, longest first.
- **Invented neighbours** — the model writes `alpha-rmq-uat` which was never a stand-in.
  Do not map it. Leave it and flag it.

Algorithm: build an alternation regex of all stand-ins sorted longest-first, replace
case-insensitively with the literal original, then re-scan the result for any residual
stand-in fragment and return those in `unmapped`. A non-empty `unmapped` must be shown
to the user: *"3 references could not be restored"* beats a quietly broken answer.

## Checkpoint (`checkpoint.py`)

Renders, via `rich`, before anything is sent:

- Findings grouped by tier, with entity type, the matched text, and the stand-in.
- Anything below `review_below` marked as uncertain.
- A unified diff of original vs. what will be transmitted.
- Blocked findings shown in red with a rotation warning, and the reason the request
  cannot proceed.

Returns an explicit approve/reject. In `scan` mode it renders and exits without sending.

## Logging

Append-only JSONL at `~/.airlock/runs.jsonl`: timestamp, source, counts per tier and
entity type, whether approved, latency per stage, unmapped count. **Never log the
original values or the mapping.** The log is a control artifact; it must be safe to hand
to an auditor.
