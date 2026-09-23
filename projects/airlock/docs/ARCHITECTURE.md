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
  gateway.py        The ONLY module that makes an off-machine network call
  rehydrate.py      Restores originals in the cloud answer; reports unmapped
  checkpoint.py     Renders the approval view, collects the decision
  mcpserver.py      Stretch: local MCP server front door
  clipboard.py      Stretch: clipboard guard
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
- Retry ladder: parse failure -> re-prompt once with the parser error appended -> on
  second failure emit nothing and log, never crash.
- Hard cap on span length; chunk longer prose.

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
  provider: foundry_local      # foundry_local | ollama
  name: qwen2.5-7b
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
    def __init__(self, key: bytes, path: Path | None = None): ...
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
5. Deduplicate overlapping findings — **longest match wins**, then highest score. A
   finding inside an `AZURE_RESOURCE_ID` is absorbed by it.
6. `classify`.
7. If any `block` finding exists, return immediately with `blocked` populated and
   `text` unchanged. Do not build a mapping, do not proceed.
8. Replace `swap` findings right-to-left by offset so earlier offsets stay valid.

## Gateway (`gateway.py`)

The only place bytes leave the machine.

```python
def send(sanitized: Sanitized, prompt: str, policy: Policy) -> tuple[str, int]: ...
```

Assert on entry that `sanitized.blocked` is empty; raise if not. Record the exact
transmitted payload for the demo's wire view. Read credentials from the env vars named
in policy; never accept them as function arguments that could be logged.

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
