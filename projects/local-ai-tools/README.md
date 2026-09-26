# Local coding assistant setup

## Aider + LM Studio for repository work

**Plan and first laptop check, 25 Sep 2026.** The setup below was run on one team
Windows laptop. Other team laptops still need their own hardware check.

## Team quick start

These are the steps for a teammate starting from a fresh Windows laptop. Use
PowerShell, or the PowerShell terminal in VS Code. Downloads and Git operations
need network access; model inference runs on the laptop.

1. Install [Git](https://git-scm.com/downloads/win),
   [Python](https://www.python.org/downloads/windows/), and
   [LM Studio](https://lmstudio.ai/download). Open LM Studio once. Check
   `git --version`, `python --version`, and `lms --help` in a new PowerShell window.
   Follow your organisation's software approval process.
2. Clone this repository, or pull its latest changes if you already have it:

   ```powershell
   git clone https://github.com/AMSandijs/atea-hackathon.git
   Set-Location .\atea-hackathon
   ```

3. In LM Studio's **Discover** tab, download
   `lmstudio-community/Qwen2.5-Coder-7B-Instruct-GGUF`, file **Q4_K_M** (about
   4.7 GB). Run `lms ls` to confirm it appears. Do not put model files in Git.
4. Install Aider and reopen PowerShell:

   ```powershell
   python -m pip install aider-install
   aider-install
   aider --version
   ```

5. From the repo root, check the local model and start the coding chat:

   ```powershell
   & .\projects\local-ai-tools\Start-LocalAI.ps1 -CheckOnly
   & .\projects\local-ai-tools\Start-LocalAI.ps1
   ```

   The script uses its own location to find the repo, so it also works after a
   clone to another directory. It checks for 7 GB of free RAM before loading
   the 7B model. If your organisation blocks PowerShell scripts, follow its
   approved process for running a local script; the manual commands are below.

**How to talk to it:** For ordinary chat, open LM Studio's **Chat** tab and
select the downloaded model. For file editing and Git, use the Aider terminal
started above. Type a plain-English request. Use `/read-only` to supply project
instructions, `/add` to select files it may edit, `/diff` to inspect its edits,
and `/git status --short` to inspect Git. Type `/help` for Aider's command list.
For example, after starting Aider:

```text
/read-only projects/airlock/AGENTS.md projects/airlock/docs/ARCHITECTURE.md projects/airlock/docs/BUILD-PLAN.md
What is the Airlock milestone explicitly marked active in the build plan? Explain its status and acceptance criteria before changing files.
```

The installed Qwen2.5-Coder models are text-only; they cannot interpret a
screenshot or photo. Image recognition would require a separate local vision
model and a compatible image-input workflow. [LM Studio image input](https://lmstudio.ai/docs/python/llm-prediction/image-input),
[Aider image commands](https://aider.chat/docs/usage/images-urls.html).

### Manual launch if PowerShell scripts are blocked

Run these commands from the repo root instead of the checked-in launcher. They
keep the server on localhost, chat history outside the repo, and Aider's
auto-commits disabled. If `local-coder` is already loaded, skip the load line.

```powershell
lms load qwen2.5-coder-7b-instruct --context-length 8192 --identifier local-coder --yes
lms server start --bind 127.0.0.1 --port 1234
$env:LM_STUDIO_API_BASE = 'http://127.0.0.1:1234/v1'
$env:LM_STUDIO_API_KEY = 'local-only'
New-Item -ItemType Directory -Force -Path "$env:LOCALAPPDATA\Aider" | Out-Null
aider --model lm_studio/local-coder --weak-model lm_studio/local-coder `
  --model-metadata-file .\projects\local-ai-tools\model-metadata.json `
  --no-auto-commits --no-dirty-commits --no-analytics --no-check-update `
  --no-gitignore --no-show-model-warnings `
  --chat-history-file "$env:LOCALAPPDATA\Aider\atea-chat-history.md" `
  --input-history-file "$env:LOCALAPPDATA\Aider\atea-input-history" `
  --read AGENTS.md --read docs/GROUND-RULES.md
```

## Recommendation

Run a coding model in **LM Studio** on each laptop and connect **Aider** to its
localhost API. LM Studio runs the model; Aider reads selected repository files,
edits code, runs shell commands and tests, and works with Git. On this laptop's
current workload, start with **Qwen2.5-Coder-7B-Instruct, Q4_K_M** (about
**4.7 GB**). **Qwen2.5-Coder-14B-Instruct, Q4_K_M** (about **9 GB**) is also
downloaded but needs more free RAM before a live trial. Other laptops may
support the 14B model more comfortably.

The checked machine was a Windows 11 Enterprise laptop with a Core Ultra 7 258V,
32 GB RAM, Intel Arc 140V graphics, and about 805 GB free storage. The reported
128 MB of dedicated graphics memory is not a 128 MB limit: this integrated GPU
also uses **shared system RAM**. The displayed 16 GB is therefore not a separate
16 GB graphics card. Model weights, context, Windows, VS Code and any test
processes all compete for the same 32 GB. Verify the other laptops before
copying these model choices to them. [Intel processor specifications](https://www.intel.com/content/www/us/en/products/sku/240957/intel-core-ultra-7-processor-258v-12m-cache-up-to-4-80-ghz/specifications.html),
[Microsoft's explanation of shared GPU memory](https://devblogs.microsoft.com/directx/gpus-in-the-task-manager/).

| Component | Choice | Job |
|---|---|---|
| Model runner | LM Studio, local GGUF model, localhost server | Inference on the laptop; try its llama.cpp Vulkan runtime and GPU offload, then compare with CPU if needed. |
| Coding assistant | Aider in the repo's terminal | Selects file context, proposes and applies edits, runs tests and Git commands. |
| Source control | Existing GitHub repo, one branch per person/task | Review diff, commit tested changes, push a branch and merge through the team's normal review. |
| Project inference | Foundry Local, with Ollama fallback, as specified in each project | Powers the *application's* local model features; it is a separate integration from the coding assistant. |

LM Studio supports Windows and a local API. GPU use on this integrated Arc is a
**trial to measure**, not a promised speedup; LM Studio's general Windows advice
recommends dedicated VRAM, which this machine lacks. Its load command can
estimate memory before loading and adjust GPU offload. Aider documents both
LM Studio connectivity and Git/shell commands. [LM Studio requirements](https://lmstudio.ai/docs/app/system-requirements),
[LM Studio model loading](https://lmstudio.ai/docs/cli/local-models/load),
[Aider commands](https://aider.chat/docs/usage/commands.html).

## Setup on each laptop

1. **Check the machine and tools.** In PowerShell run `git --version`,
   `python --version`, and `Get-ComputerInfo | Select-Object WindowsProductName, OsArchitecture`.
   Check Task Manager for RAM and GPU type. Use the same model only on machines
   with roughly the same available memory. Install VS Code, Git and Python if
   missing, through the team's normal IT-approved route.
2. **Install LM Studio** from its official site and launch it once. In Discover,
   find `lmstudio-community/Qwen2.5-Coder-7B-Instruct-GGUF` and choose
   `Q4_K_M`. Confirm the exact publisher and quantization before downloading.
   The published file is 4.68 GB. Keep model files outside this Git repo.
   [Model files](https://huggingface.co/lmstudio-community/Qwen2.5-Coder-7B-Instruct-GGUF),
   [LM Studio CLI](https://lmstudio.ai/docs/cli).
3. **Load conservatively.** In LM Studio select the llama.cpp Vulkan runtime if
   it detects the Arc GPU. Start with **8,192 context tokens** and automatic
   GPU offload (omit `--gpu`; this is the CLI default); use the memory
   estimate before loading. In PowerShell, after
   `lms ls` shows the downloaded model, the equivalent commands are:

   ```powershell
   lms ls
   lms load "<model-key-from-lms-ls>" --context-length 8192 --estimate-only
   lms load "<model-key-from-lms-ls>" --context-length 8192 --identifier local-coder
   lms server start --bind 127.0.0.1 --port 1234
   (Invoke-RestMethod http://127.0.0.1:1234/v1/models).data | Select-Object id
   ```

   The model list should contain `local-coder`. Keep the server bound to
   **127.0.0.1**. Do not enable network serving or cloud model routing for
   repository work. [LM Studio server binding](https://lmstudio.ai/docs/cli/serve/server-start),
   [offline behavior](https://lmstudio.ai/docs/app/offline).
4. **Install Aider separately from project Python environments.** The official
   installer uses a separate tool environment:

   ```powershell
   python -m pip install aider-install
   aider-install
   aider --version
   ```

   If `aider` is not found, reopen PowerShell and check the
   [official Windows install guidance](https://aider.chat/docs/install.html).
5. **Connect Aider to the local model.** Run the checked-in launcher from the
   repository root. It starts the localhost server, loads the 7B model at 8,192
   context tokens, checks the API, and starts Aider in the repository:

   ```powershell
   & .\projects\local-ai-tools\Start-LocalAI.ps1
   ```

The launcher and its [model metadata](model-metadata.json)
   are both in Git. Its API base is `http://127.0.0.1:1234/v1`; `local-only` is
   a dummy API-key value required by Aider, not a credential. The script
   disables auto-commits, analytics and update checks for the session, keeps
   chat history under the user's AppData, and reads the root repo rules.
   Aider's model calls go to localhost. [Aider LM Studio setup](https://aider.chat/docs/llms/lm-studio.html),
   [Git behavior and flags](https://aider.chat/docs/git.html),
   [configuration options](https://aider.chat/docs/config/options.html).

## How to build an idea with it

Start with `projects/airlock/`, the selected hackathon entry in
`../../DECISIONS.md`. Read that project's `AGENTS.md`, architecture and build plan
before asking Aider to edit anything. Work on **one explicitly active/next milestone**
and stop when its acceptance criteria and tests pass. T21 is currently active; T10–T12
are deferred parts of the original plan, not the next task. Do not ask a small local
model to implement the whole plan in one prompt.

For each task:

1. Create a branch with a unique name, for example
   `git switch -c local-ai/airlock-t9-sandijs`. Start with `git status --short`.
2. In Aider use `/read-only` for the relevant project instructions and plan,
   `/add` for only the files needed for that task, and `/ask` before `/code`
   when the design is unclear. Example request: *"Read the project architecture
   and the current T21 evaluation plan. Review only the existing T21 changes; don't
   implement T22. Run the focused and full tests, then report failures and the diff."*
3. Use Aider's `/run` or `/test` to run the project's documented checks.
   Use `/diff` to inspect edits. Aider's `/git status` and `/git diff --check`
   can run Git commands from the chat; the same commands work in PowerShell.
4. After a human reviews the diff and tests, commit only the intended files:
   `git add <files>`, `git commit -m "Complete Airlock T21 evaluation"`,
   `git push -u origin <branch>`. Aider's `/git` command can run those Git
   operations too. Open a pull request and merge after review. Avoid `git add .`
   when model outputs or local state may be present.

Aider can edit files and invoke shell/Git commands, but local models can still
misread instructions or produce malformed edits. Keep changes small, inspect
every diff and run the tests. Aider's defaults auto-commit edits; the startup
command above disables that so each task remains reviewable.

**Application model boundary:** the Airlock runtime has its own configurable local
model and separate setup guide in `../airlock/docs/LOCAL-AI-SETUP.md`. The coding
assistant described here is not part of the Airlock data path. Airlock has both a
standalone sanitized cloud-gateway workflow and a Copilot Azure-investigation pilot;
in either case, running Aider locally does not make cloud traffic private by itself.
The Attachment Clerk is a separate, currently unimplemented project specification.

## Results measured on the checked laptop (25 Sep 2026)

| Check | Measured result, 25 Sep 2026 |
|---|---|
| Installed tools | LM Studio 0.4.25+1; Aider 0.86.2; existing Git 2.55 and Python 3.12 |
| Models on disk | Qwen2.5-Coder 7B Q4_K_M, 4.68 GB; 14B Q4_K_M, 8.99 GB |
| Local API | Listening on `127.0.0.1:1234`; a tiny prompt returned `READY` in 1.2 seconds |
| 7B at 8,192 context | LM Studio reported 4.36 GiB loaded; cold load took 25 seconds, later load took 8 seconds; Vulkan offload requested GPU layers |
| CPU versus Arc Vulkan | Same prompt, 64 input and 140 output tokens: 15.9 seconds on CPU, 8.0 seconds with Vulkan; one run per mode |
| Coding smoke test | Aider fixed one file in a disposable Git repo; its test command passed, `git diff --check` passed, and `/git status --short` worked |
| Full small edit | A second one-file fix took 9.2 seconds including Aider startup; its test and diff check passed |
| Memory | About 1.2-1.9 GB free with 7B loaded in the current desktop session; about 10.7 GB free after unloading |
| 14B at 8,192 context | LM Studio estimates 9.63 GiB while roughly 10.5 GB was free; it was not loaded because the remaining headroom was too small |

The original tested launcher was in this laptop's AppData. Its portable version
is checked into `projects/local-ai-tools/Start-LocalAI.ps1`; run it from the
repository root as shown above. Add `-CheckOnly` to load the model and verify
the API without opening Aider. It uses the 7B model, reads the root repo rules,
and keeps Aider history under AppData. Aider's generated repository map cache
is ignored by Git. The launcher refuses to load the model if less than 7 GB RAM
is free. The model was unloaded after the original test to return memory to the laptop.
The CPU versus GPU comparison supports keeping automatic GPU offload as the
default here; these are single-run timings, not application latency figures.

## Acceptance check before the team adopts it

On each laptop, record: model load success, peak RAM use, whether GPU offload
actually occurred, prompt processing and generation speed, and one complete
small task's elapsed time. Test the 7B model at 8,192 context with automatic
GPU offload and CPU-only loading. Use the setup that is stable and faster **on
the actual laptop**. If 7B makes repeated unusable edits, trial 14B only when
free RAM exceeds LM Studio's estimate by at least 3 GB. Expand context to
16,384 only if a task needs it and memory remains comfortable. No speed
target is asserted until measured.

Success means Aider can (1) read a project instruction file, (2) change one
small code file, (3) run that project's test command, (4) show a clean
`git diff --check`, and (5) produce a reviewed commit on a branch. Repeat the
smoke test on each teammate's laptop. Model download needs internet; local
inference can then run offline. Git fetch/push, package installs and any
Airlock gateway call are network operations.

## Repo boundaries

Keep real customer data and credentials out of the repo, prompts, logs and
fixtures. Use invented data and mocks or test tenants as required by
`../../docs/GROUND-RULES.md`. Keep model files and local chat logs outside the repo.
Review staged files before pushing. A local model can read local files, so
limit Aider's file context to the task and never point it at real customer
material. Existing project instructions and build plans override generic
advice in this document.
