# Local AI Airlock

Airlock is a local privacy boundary for cloud-assisted Azure incident investigation.
It combines local detection and planning, a deterministic read-only Azure broker, a
trusted local approval UI, and GitHub Copilot's cloud reasoning over approved sanitized
evidence. It is a prototype boundary, not a guarantee that all identifying values are
detected or removed.

This is a hackathon prototype, not a production security product. The full threat model,
contracts, and current milestone status are in the linked design documents below.

## The investigation loop

```text
Azure alert/snapshot
       │
       ▼
local case preparation ── operator reviews sanitized case
       │
       ▼
Copilot reads approved case and asks for one alias-only follow-up
       │
       ▼
local model proposes one typed read (operation, alias, bounded time)
       │
       ▼
Airlock GUI approves real target/query ── deterministic broker runs fixed Azure read
       │
       ▼
local sanitizer ── operator separately approves sanitized evidence
       │
       └──────────► Copilot reads evidence and reasons; repeat as needed
```

The model planner never runs `az`, constructs arbitrary commands, or approves its own
proposal. Airlock's broker resolves the alias and executes only fixed read adapters with
the operator's local Azure CLI identity. Query approval and evidence-release approval
are separate. MCP does not directly expose raw Azure results or the reverse map and does
not accept real resource IDs as Copilot arguments. However, current T21 evaluation found
that a resource name mapped inside an Azure resource ID may still appear unchanged in
other case prose; until that gap is fixed, assume identifying text could reach Copilot.

## What is implemented

- CLI workflows to scan, prepare, capture a read-only resource snapshot, define a private
  alias scope, investigate one turn, and restore a saved answer locally.
- A local stdio MCP server for approved sanitized cases/evidence and Copilot-requested
  investigation handoff.
- A single-user Tkinter GUI that handles query approval, result review, and the local
  queue of alias-only MCP requests. It opens no network listener.
- Fixed read adapters for VM CPU, Application Insights failures, Logic App run summaries,
  and Azure SQL metrics.
- Seeded detector evaluation and a T21 multi-resource investigation evaluation in
  progress. Tests use invented data and mock the Azure CLI; see [`docs/EVAL.md`](docs/EVAL.md).

The default MCP-to-GUI request queue is a local file queue under the private case-data
directory. Queue records contain only opaque IDs, a typed alias-level proposal, status,
and timestamps. The GUI must be running with the approved case loaded to pick up a
request. Requests expire; queueing never implies approval.

## Try the project

From this directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\airlock.exe --help
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp
```

For model-backed case preparation, the investigation planner, and the desktop workflow,
configure a supported local model endpoint on loopback using the [local model setup guide](docs/LOCAL-AI-SETUP.md).
Install Azure CLI and authenticate locally only when you intentionally choose to run a
read against an approved test subscription. The committed automated tests do not
contact Azure.

Run the GUI from this project directory with
`.\.venv\Scripts\airlock.exe gui`.

For Copilot, open the repository root in VS Code so the root `.vscode/mcp.json` resolves
the Airlock environment correctly. Set `AIRLOCK_LOCAL_MODEL_URL` in the MCP server's
environment (or launch VS Code from a shell where it is set), keep `airlock gui` open
with the case loaded, select the Airlock Investigator agent, and confirm its enabled
tools. Disable direct Azure, portal/browser, terminal, and workspace-file access for the
protected investigation; Airlock cannot protect data sent through another tool.

For an offline sample case, prepare the invented sample with the explicitly opted-in
rules-only path:

```powershell
.\.venv\Scripts\airlock.exe prepare samples\vm-cpu-alert.json --rules-only
```

Review the local checkpoint carefully. Rules-only mode omits the local free-text model
sweep and is not equivalent to the protected model-backed workflow.

## Safety and unverified behavior

- Azure collection adapters are read-only and strictly allow-listed, but an operator
  approval is still required before every query and before each result is shared.
- Local data directories contain original identifiers and reverse mappings. Treat them
  as customer data and keep them out of synchronized/shared folders.
- The automated Azure tests are mocked. A real tenant, live Copilot session, and the
  local model's planning performance have not been validated end to end.
- T21 found a mapped resource-name leak in case prose, and current tests are not green;
  see [`docs/T21-EVALUATION.md`](docs/T21-EVALUATION.md) and
  [`docs/BUILD-PLAN.md`](docs/BUILD-PLAN.md). Do not use with customer data.
- The current seeded run also found that App Insights and SQL results fail closed and
  common long resource names may be blocked. Until fixed, follow the T21 report's narrow
  demo guidance rather than presenting all four adapters as a working end-to-end demo.
- Detectors can miss unknown identifiers or block legitimate values. Evaluation uses a
  small invented corpus and is not a guarantee of privacy. Inspect approvals and do not
  send real customer material in the hackathon demo.
- The standalone `airlock ask` gateway and the Copilot Azure-investigation workflow are
  distinct paths; see [`docs/SPEC.md`](docs/SPEC.md). Neither intercepts Copilot traffic.

## Project documents

| Document | Use it for |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Rules for agents changing Airlock code |
| [`docs/SPEC.md`](docs/SPEC.md) | Product scope and decisions |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Trust boundaries, modules, contracts, and data flow |
| [`docs/BUILD-PLAN.md`](docs/BUILD-PLAN.md) | Task acceptance criteria and implementation status |
| [`docs/EVAL.md`](docs/EVAL.md) | Seeded detection and multi-turn investigation evaluation |
| [`docs/T21-EVALUATION.md`](docs/T21-EVALUATION.md) | Measured findings, known gaps, and demo limitations from T21 |
| [`docs/MCP-LOOP-IMPLEMENTATION-PLAN.md`](docs/MCP-LOOP-IMPLEMENTATION-PLAN.md) | T19–T21 handoff implementation record and remaining evaluation work |
| [`docs/LOCAL-AI-SETUP.md`](docs/LOCAL-AI-SETUP.md) | Airlock local planner/detector model setup |
