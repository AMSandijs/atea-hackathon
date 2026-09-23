# Build plan — Local AI Airlock

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

Implement `detect/model.py` against Foundry Local (OpenAI-compatible endpoint via
`FoundryLocalManager`), with an Ollama fallback selected by `policy.model.provider`.
Structured JSON output, retry ladder, hard span cap.

**Done when:** the model runs only over rule-free prose spans; invalid JSON retries once
then degrades to emitting nothing; seconds-per-call is recorded in the run log; recall on
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

---

## Demo checklist (Sunday)

- Recorded run, not live.
- Wire view showing the exact transmitted bytes.
- The blocked-key moment called out explicitly.
- Four numbers on one slide: recall, precision, quality delta, added latency.
- The honest sentence about recall never being 100%, and why a human approves.
