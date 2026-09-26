# Local AI Airlock

A chamber between the laptop and the cloud model. Customer-identifying material is
detected and swapped locally, detected secrets stop release, and the approved sanitized
text can be used for cloud reasoning. The answer is rebuilt with the real names on the
laptop. The boundary applies to data routed through Airlock; unknown identifiers can
still be missed, so the operator reviews the output before releasing a case.

Built for a local-AI hackathon: kickoff Fri 25 Sep 14:00 CEST, delivery Mon 28 Sep
08:00 CEST (09:00 Riga), short presentation immediately after.

## Constraints that shape every decision

- Runs on a **CPU-only corporate laptop**. No GPU. Assume a 4B-8B quantized model.
- **Deterministic first.** The LLM only handles what regex and format checks cannot.
- Team of 3, ~2.5 working days. Scope is protected by `docs/BUILD-PLAN.md`.
- The eval (`docs/EVAL.md`) is **not optional** — it is the differentiator.

## Start here

| File | What it is |
|---|---|
| `AGENTS.md` | Rules for any AI agent working in this repo. Read first. |
| `docs/SPEC.md` | What the product is and why. Product decisions, not code. |
| `docs/ARCHITECTURE.md` | Module contracts, data shapes, algorithms. |
| `docs/BUILD-PLAN.md` | Ordered tasks with acceptance criteria. Work through in order. |
| `docs/EVAL.md` | Corpus, metrics, reporting format. |

## Quickstart (Windows PowerShell)

From the repo root, enter `projects/airlock` first (or open that folder by
itself). Keep the virtual environment and all raw data local.

```powershell
Set-Location .\projects\airlock
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\airlock.exe scan samples\vm-cpu-alert.json
.\.venv\Scripts\airlock.exe prepare samples\vm-cpu-alert.json --rules-only
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp
```

## Non-goals

Listed in `AGENTS.md` and enforced there. The short version: no chat UI, no browser
extension, no MITM of Copilot traffic, no inline-completion interception.

## Azure/Copilot pilot

The local pilot starts from an exported Azure alert or resource snapshot. Airlock scans
it locally, asks for approval, and gives GitHub Copilot an opaque case ID. Copilot reads
only the approved sanitized snapshot through the local MCP server. To investigate beyond
that snapshot, the local CLI and desktop GUI support one supervised read per turn
across approved VM CPU, Application Insights failure metrics, Logic App run summaries,
and Azure SQL metrics. Airlock obtains a local typed proposal, shows the real target for
operator approval, and requires a second checkpoint before exposing sanitized evidence
through MCP. The operator manually transfers Copilot's next alias-only request to the local CLI
or GUI and repeats; Copilot cannot directly execute Azure commands. Save the final answer
to a local text file and restore the real names on the laptop.

For the desktop workflow, run `airlock gui` after installing the project. It provides
the same local case/scope setup, one-query approval, and separate raw-versus-sanitized
result review in a single-user Tkinter window. It does not add a listener or automate
Copilot; you still paste Copilot's alias-only next-read request and share only the
released opaque evidence ID.
The separate `airlock ask` cloud-gateway route also requires a configured loopback
model and aborts if its prose sweep fails; an unconfigured gateway remains a local
echo for offline testing.

1. Open the **repository root** in VS Code and install the Python dependencies above.
   The root `.vscode/mcp.json` registers the local `airlock` MCP server using
   `projects/airlock/.venv`. The project-level config also works if you open only
   `projects/airlock` in VS Code. Select the
   **Airlock Investigator** custom agent and verify that only its `airlock` tool is
   enabled for the investigation.
2. Run a local model such as LM Studio, Foundry Local, or Ollama and set
   `AIRLOCK_LOCAL_MODEL_URL` to its loopback chat endpoint. Foundry Local expects
   `/v1/chat/completions`; Ollama expects `/api/chat` and `model.provider: ollama` in
   `policy.yaml`. LM Studio also supports `/v1/chat/completions`; set
   `model.provider: lm_studio` and use a model ID returned by its `/v1/models` endpoint.
   On the validation laptop, LM Studio was listening at `http://127.0.0.1:1234`,
   with Qwen2.5-Coder 7B and 14B downloaded. Install/load a compatible model on
   your own machine; the default policy targets the LM Studio 7B model ID.
   Start with:

   ```powershell
   $env:AIRLOCK_LOCAL_MODEL_URL = 'http://127.0.0.1:1234/v1/chat/completions'
   .\.venv\Scripts\airlock.exe eval --with-model
   ```

   LM Studio can load the downloaded model when first called. The 14B comparison is:
   `airlock eval --with-model --model-name qwen2.5-coder-14b-instruct`.
   To use Foundry Local instead, set `model.provider: foundry_local`, set its model name
   in `policy.yaml`, and point the URL at the Foundry Local server. For Foundry Local on Windows:

   ```powershell
   foundry model download qwen2.5-7b-instruct-generic-cpu
   foundry model load qwen2.5-7b-instruct-generic-cpu
   foundry server status
   $env:AIRLOCK_LOCAL_MODEL_URL = 'http://127.0.0.1:<reported-port>/v1/chat/completions'
   ```

   Replace `<reported-port>` with the actual port from `foundry server status`.
3. Run `airlock prepare samples/vm-cpu-alert.json`, inspect the checkpoint, and approve.
   The command prints a random case ID. For an offline rules-only demo, use
   `airlock prepare samples/vm-cpu-alert.json --rules-only`; that mode is explicit
   because it has no local prose-model sweep.
   For a model-backed demo that visibly swaps unkeyed names in free text, use
   `samples/vm-cpu-alert-with-prose.json`; do not use `--rules-only` for that file.
   To read a real resource's configuration with your existing Azure CLI sign-in, run
   `airlock capture <full Azure resource ID>` in your local terminal. This uses the
   read-only Azure `resource show` command, then applies the same checkpoint. The
   optional `--metric "Percentage CPU"` also reads that resource's last hour of Azure
   Monitor measurements. Alert history, guest processes, SQL query text, Logic App
   action inputs/outputs, and Log Analytics traces still require a local export and
   `airlock prepare` for a deeper causal investigation.
4. In the local terminal, define the resources Copilot may ask about. Each ID is entered
   through a hidden local prompt, then displayed only on the local approval screen:

   ```powershell
   .\.venv\Scripts\airlock.exe scope <case ID> --alias VM_1 --alias APP_1
   ```

   Assign aliases that you can safely share with Copilot. The scope is private and
   cannot be changed in place; create a new case to change it.
5. In the Airlock Investigator agent, ask: `Analyze case <case ID>. What likely caused
   the CPU alert? Cite evidence, uncertainty, and one next read using only the approved
   aliases.` Keep original customer details out of the prompt and other Copilot tools.
   Copy its alias-only next-read request into the local terminal:

   ```powershell
   .\.venv\Scripts\airlock.exe investigate <case ID> --goal "Check VM_1 CPU over the last 30 minutes"
   ```

   Review and approve the exact real Azure target/query locally, then separately inspect
   and approve the sanitized result. `--rules-only` is an explicit opt-in for evidence
   scanning, but the local planner model is still required. Only after approval does the
   CLI print an evidence ID. Ask Copilot to read that evidence using Airlock's
   `read_evidence` tool, then repeat with its next alias-only request.
6. Save the final Copilot answer to a local file outside the VS Code workspace and run
   `airlock restore <case ID> answer.txt`. Keep raw exports and the restored answer
   outside the Copilot workspace and out of its open editor tabs.

The current capture command can read one live resource's configuration or one metric,
or the pilot can use an exported telemetry bundle. Broker reads are fixed and read-only;
the CLI supervisor handles one query at a time and does not automatically receive MCP
requests from Copilot. No alert-history fetch or portal interaction is implemented.
A Copilot chat prompt, portal/browser tool, terminal command, workspace
file, or direct Azure MCP tool can still send original data to the model if enabled or
used. The custom agent narrows its tool list, but operators must verify the active tool
selection and keep customer-specific text out of the prompt. The original-to-stand-in
map is stored locally under `.airlock/cases` in the user's profile; protect that folder
like other customer data. Detector metrics on invented data are not a guarantee for a
new customer environment.

## Current validation (25 Sep 2026)

The seeded corpus has 18 sensitive items. Rules-only detection finds 16/18.
Both of the user's LM Studio models found 18/18 and produced the same 60% strict
match-to-seed rate:

| LM Studio model | Recall | Model sweep per eligible file, median / worst |
|---|---:|---:|
| Qwen2.5-Coder 7B | 18/18 | 1.7 s / 3.3 s |
| Qwen2.5-Coder 14B | 18/18 | 6.2 s / 33.4 s |

The 7B model is the demo default: it also completed a model-backed sample case that
swapped an unkeyed person, organisation, and VM identifier, then restored them locally.
These are small, invented-data results, not a privacy guarantee. Several legitimate
findings are not yet labeled in the corpus, so the 60% seed-match rate should not be
presented as production precision. Answer-quality comparison against Copilot,
customer-environment testing, and an actual VS Code Copilot session remain unverified.
