# Atea Local AI Hackathon — team workspace

Shared folder for our hackathon team. Clone it, open the **root folder** in VS Code
(not a subfolder — the AI instructions live at the root), and read this page.

**Kickoff Fri 25 Sep 14:00 CEST. Delivery Mon 28 Sep 08:00 CEST — 09:00 Riga time.**

## What's in here

| Path | What it's for |
|---|---|
| `docs/HACKATHON.md` | The event: schedule, prize, what the organisers asked for, who's judging |
| `docs/WORKING-WITH-AI.md` | **Read this one.** How to think *and* build with AI in this repo |
| `docs/LOCAL-AI-SETUP.md` | Fresh-laptop setup, chat and coding instructions for local AI |
| `docs/GROUND-RULES.md` | Data handling and demo safety. Short, non-negotiable |
| `ideas/` | One-pager per idea. Template included. Add yours |
| `projects/airlock/` | Build-ready spec for the AI Airlock — our primary entry |
| `projects/attachment-clerk/` | Build-ready spec for the Attachment Clerk — fallback / after |
| `projects/local-ai-tools/` | Portable launcher and model settings for the team's coding assistant |
| `DECISIONS.md` | What we chose and why, so we don't relitigate it on Saturday |
| `scratch/` | Your own mess. Git-ignored |

## First 10 minutes

1. Open the root folder in VS Code.
2. Read `docs/WORKING-WITH-AI.md`. It's short and it's the thing that makes the rest work.
3. Skim `docs/HACKATHON.md` so you know what we're being judged on.
4. To use the local coding assistant, follow the setup below.
5. Look at `ideas/`. If you have one that isn't there, copy `ideas/_TEMPLATE.md` and
   fill it in — it takes fifteen minutes and the template does the hard thinking for you.

## Set up local AI on a Windows laptop

LM Studio runs the model on your laptop. Aider connects to it in a terminal so
you can ask questions, edit repo files, run checks and use Git. The setup below
uses the **Qwen2.5-Coder-7B-Instruct Q4_K_M** model (about 4.7 GB). It was tested
on one 32 GB RAM laptop; check your own machine before using the same model.
The launcher requires at least 7 GB of free RAM before loading it.

1. Install [VS Code](https://code.visualstudio.com/download),
   [Git](https://git-scm.com/downloads/win),
   [Python](https://www.python.org/downloads/windows/) and
   [LM Studio](https://lmstudio.ai/download) through your organisation's
   approved process. Open LM Studio once. In a new PowerShell terminal, check:

   ```powershell
   git --version
   python --version
   lms --help
   ```

2. Clone the repo and open its **root folder** in VS Code:

   ```powershell
   git clone https://github.com/AMSandijs/atea-hackathon.git
   Set-Location .\atea-hackathon
   code .
   ```

   If you already cloned it, go to its root and run `git pull --ff-only`
   instead of cloning again. If `code .` is unavailable, use **File > Open
   Folder** in VS Code.

3. In LM Studio's **Discover** tab, download
   `lmstudio-community/Qwen2.5-Coder-7B-Instruct-GGUF` and select the **Q4_K_M**
   file. Confirm the publisher and file before downloading. In PowerShell, run
   `lms ls` to check that `qwen2.5-coder-7b-instruct` is listed. Keep model
   files outside the repo.

4. Install Aider in its own tool environment, then reopen PowerShell:

   ```powershell
   python -m pip install aider-install
   aider-install
   aider --version
   ```

5. From the repo root, verify the local model and start Aider:

   ```powershell
   & .\projects\local-ai-tools\Start-LocalAI.ps1 -CheckOnly
   & .\projects\local-ai-tools\Start-LocalAI.ps1
   ```

   The script loads the model, starts LM Studio's server on `127.0.0.1:1234`,
   then opens Aider in this repo. If script execution is blocked, use the
   [manual launch commands](docs/LOCAL-AI-SETUP.md#manual-launch-if-powershell-scripts-are-blocked)
   or your organisation's approved way to run local scripts.

### Talk to it and build with it

- **Ordinary chat:** Open LM Studio's **Chat** tab, select the downloaded model,
  and type a message. This is for conversation, not repo editing.
- **Coding chat:** Type plain English at the Aider prompt. It already reads the
  root `AGENTS.md` and `docs/GROUND-RULES.md`. Add the chosen project's rules
  and plan as reference:

  ```text
  /read-only projects/airlock/AGENTS.md projects/airlock/docs/ARCHITECTURE.md projects/airlock/docs/BUILD-PLAN.md
  What is the lowest-numbered unfinished task? Explain it before changing files.
  ```

  Before an edit, use `/add` followed by each existing file it may change.
  Ask it to implement **one** build-plan task and run that task's tests. Use
  `/diff` to review edits, `/git status --short` to inspect Git, and `/help`
  for other Aider commands.
- **Git:** Create a task branch, for example
  `git switch -c local-ai/airlock-t9-alex` (replace the task and name). Review
  `git diff`, run the project's tests and `git diff --check`, then stage only
  intended files with `git add`. Commit and push the branch for team review:

  ```powershell
  git commit -m "Complete selected build task"
  git push -u origin HEAD
  ```

  The launcher turns off Aider's automatic commits.

Keep customer data and secrets out of prompts and files; use invented examples
and mocks. The installed coding model is text-only, so screenshots and photos
need a separate vision model. The [full setup guide](docs/LOCAL-AI-SETUP.md)
has hardware checks, manual commands and troubleshooting details.

## If you want to build rather than think

Go to `projects/airlock/`, read its `AGENTS.md`, then open `docs/BUILD-PLAN.md` and take
the lowest-numbered unfinished task. Same pattern in `attachment-clerk/`.

## Have an idea of your own?

Good — that's what this folder is for, and it is explicitly not too late. Write it up with
the template, run the pressure-test prompt in `docs/WORKING-WITH-AI.md` against it, and
put it in the channel. An idea that survives the four questions beats one that's just
been around longer.
