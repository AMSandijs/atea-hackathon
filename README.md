# Local AI Airlock

Local AI Airlock is a Windows-first prototype for investigating Azure alerts with a
cloud reasoning assistant while keeping original resource identifiers and raw Azure
responses on the operator's machine by design. Current evaluation has found identifier
coverage gaps, so this is a prototype boundary—not a guarantee for arbitrary data. It is
the selected project in this Atea local-AI hackathon workspace.

The Airlock is the controlled bridge: local models help interpret requests and inspect
text, a deterministic broker runs a small set of fixed Azure reads, and a person approves
both the query and any sanitized evidence released to GitHub Copilot.

## How an investigation works

1. The operator prepares an exported alert/snapshot locally and approves a sanitized case.
   Real Azure resources are bound to private aliases such as `VM_1` in an approved scope.
2. Copilot reads only the sanitized case through Airlock's local MCP server. It reasons
   over aliases and asks for one bounded follow-up read at a time.
3. A local model turns that alias-only goal into a typed proposal: an allowed operation,
   approved alias, and bounded time range. It does **not** execute shell or Azure commands.
4. Airlock's deterministic broker revalidates the proposal, resolves the real resource
   ID locally, builds a fixed read-only Azure request, and runs it with the operator's
   local Azure CLI identity. The local GUI asks the operator to approve the real target
   and query first.
5. The Azure result returns to Airlock, is sanitized locally, and is shown for a separate
   release decision. Only approved sanitized evidence becomes readable to Copilot.
   Copilot can reason over it and request another read; the loop repeats one turn at a
   time. The final answer can be restored locally.

The implemented read adapters cover VM CPU metrics, Application Insights failures,
Logic App run summaries, and Azure SQL metrics. Query construction is fixed in code; the
model cannot provide a command, URL, KQL, or mutation. The local model proposes what to
read, but the broker—not the model—executes the Azure read. Current T21 results show
App Insights and SQL reads fail to release because of sanitizer/vault defects; those
paths are not demo-ready yet.

## Safety boundary and current limits

- Query approval and sanitized-result approval are separate, trusted-local GUI actions.
- MCP exposes approved sanitized cases/evidence and a narrow request/status interface;
  it does not expose arbitrary files, raw Azure results, the reverse map, or a restore tool.
- The Copilot session must not also have direct Azure, portal/browser, terminal, or
  workspace-file tools that can expose customer data. Airlock cannot sanitize data sent
  through another tool or pasted directly into the prompt.
- Raw Azure results and the original-to-alias map remain local. Protect Airlock's case
  directory as customer data.
- T21 evaluation has identified a privacy gap: a resource name detected inside an Azure
  resource ID may remain unchanged when the same name appears separately in case prose.
  Review [`projects/airlock/docs/T21-EVALUATION.md`](projects/airlock/docs/T21-EVALUATION.md)
  and treat the current build as not ready for customer data.
- The same evaluation found that the entropy detector blocks common long Azure resource
  names. Until those findings are fixed, its demo guidance is limited to VM CPU and Logic
  App reads with short resource names.
- The Azure investigation path has offline tests with mocked Azure responses. A live
  VS Code/Copilot session, a real local-model investigation, and live-tenant behavior are
  not yet validated. Passing invented-data tests is not a privacy guarantee for arbitrary
  customer environments.
- Do not use production resources or real customer data for the hackathon demo. Follow
  [`docs/GROUND-RULES.md`](docs/GROUND-RULES.md).

## Run and test the project

Requirements: Windows, Python 3.11+, and PowerShell. From the repository root:

```powershell
Set-Location .\projects\airlock
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\airlock.exe --help
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp
```

For the desktop supervisor, start a compatible loopback model and configure
`AIRLOCK_LOCAL_MODEL_URL` as described in the [Airlock local-model guide](projects/airlock/docs/LOCAL-AI-SETUP.md).
From the repository root, run `.\projects\airlock\.venv\Scripts\airlock.exe gui`.
For Copilot integration, open the repository root in VS Code,
install Airlock's dependencies, configure the local model endpoint in the MCP server
environment, and select the Airlock Investigator agent. The [Airlock README](projects/airlock/README.md)
has the demo workflow and exact setup links.

## Repository guide

| Path | Purpose |
|---|---|
| [`projects/airlock/`](projects/airlock/README.md) | Selected project: CLI, local GUI, MCP server, Azure read broker, tests, and docs |
| [`projects/airlock/docs/SPEC.md`](projects/airlock/docs/SPEC.md) | Product scope and security decisions |
| [`projects/airlock/docs/ARCHITECTURE.md`](projects/airlock/docs/ARCHITECTURE.md) | Module boundaries, data contracts, and trust model |
| [`projects/airlock/docs/BUILD-PLAN.md`](projects/airlock/docs/BUILD-PLAN.md) | Milestone status and acceptance criteria |
| [`projects/airlock/docs/EVAL.md`](projects/airlock/docs/EVAL.md) | Seeded detector and investigation-loop evaluation |
| [`projects/attachment-clerk/`](projects/attachment-clerk/README.md) | Separate, documented alternative; not the selected build |
| [`ideas/`](ideas/README.md) | Original idea briefs and decision status |
| [`DECISIONS.md`](DECISIONS.md) | Why Airlock was selected |
| [`docs/GROUND-RULES.md`](docs/GROUND-RULES.md) | Data handling and demo rules |
| [`docs/HACKATHON.md`](docs/HACKATHON.md) | Event schedule and judging context |
| [`docs/WORKING-WITH-AI.md`](docs/WORKING-WITH-AI.md) | Guidance for reviewing ideas and implementing tasks with agents |
| [`projects/local-ai-tools/README.md`](projects/local-ai-tools/README.md) | Local coding-assistant setup (Aider + LM Studio); separate from Airlock runtime |

For agent-assisted code changes, read the repository [`AGENTS.md`](AGENTS.md) and then
the selected project's [`AGENTS.md`](projects/airlock/AGENTS.md). Work from its build
plan one task at a time; keep all examples invented and all Azure tests mocked unless a
separate, explicit test-tenant plan is approved.
