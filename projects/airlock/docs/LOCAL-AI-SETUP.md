# Airlock local model setup

This guide configures the model used by the Airlock application. It is separate from the
[local coding assistant](../../local-ai-tools/README.md), which uses Aider to edit this
repository.

Airlock uses a local model for free-text detection and for proposing a typed Azure read.
For the current Copilot investigation loop, the planner requires the `lm_studio` provider
and an OpenAI-compatible chat-completions endpoint. The model can propose only an
operation, approved alias, and bounded time range; it cannot run Azure commands or grant
approval. Azure results remain local until sanitization and a separate human release.

## Configure LM Studio

1. Install and open LM Studio using your organization's approved process. Keep downloaded
   model files outside this repository.
2. Download/load a compatible instruct model. The default in `policy.yaml` is
   `qwen2.5-coder-7b-instruct`. The 7B Q4 model is the demo starting point; a 14B model
   can also be tested if the laptop has enough free memory. Use the exact model ID shown
   by LM Studio's `/v1/models` response.
3. Start the local server bound to loopback, normally `127.0.0.1:1234`. Do not expose it
   on the LAN or route it through a cloud provider.
4. In a PowerShell terminal, set the endpoint and verify the model is listed:

   ```powershell
   $env:AIRLOCK_LOCAL_MODEL_URL = 'http://127.0.0.1:1234/v1/chat/completions'
   (Invoke-RestMethod 'http://127.0.0.1:1234/v1/models').data | Select-Object id
   ```

   Set `model.name` in `policy.yaml` to the exact ID returned by LM Studio. The default
   policy is `lm_studio` + `qwen2.5-coder-7b-instruct`.

## Run model-backed checks

From `projects/airlock` with the local model endpoint set:

```powershell
.\.venv\Scripts\airlock.exe eval --with-model
.\.venv\Scripts\airlock.exe gui
```

To compare the 14B model in the detector evaluation, pass its LM Studio model ID:

```powershell
.\.venv\Scripts\airlock.exe eval --with-model --model-name qwen2.5-coder-14b-instruct
```

That command overrides the model for the detector evaluation only. To test the
investigation planner with another model, change `model.name` in `policy.yaml` and run
the investigation evaluation. Restore the demo default afterward if it was changed.

## Connect VS Code Copilot

The MCP process also needs `AIRLOCK_LOCAL_MODEL_URL`; setting it only in a terminal that
does not launch VS Code is not enough. Either launch VS Code from a PowerShell process
with the variable set, or configure the variable in the MCP server's local environment
settings. The root `.vscode/mcp.json` registers the server but intentionally does not
contain machine-specific model settings.

Keep `airlock gui` open with the approved case loaded. The GUI polls the local queue for
Copilot's alias-only requests and presents the trusted approvals. If the model endpoint
is missing, planning fails closed and no Azure query is issued.

## Provider boundary

The prose detector also has adapters for Foundry Local and Ollama, but the Copilot
investigation planner currently requires `model.provider: lm_studio`. Do not switch the
shared provider setting to Foundry Local or Ollama and expect the full investigation
loop to work; support for those planner APIs needs implementation and tests. Rules-only
case preparation is an explicit alternative for offline demonstration, not a substitute
for a model-backed privacy evaluation.

The coding assistant described in [`../../local-ai-tools/README.md`](../../local-ai-tools/README.md)
is not part of the Airlock runtime boundary. Running a local coding model does not make
Copilot or any other cloud model traffic private by itself.
