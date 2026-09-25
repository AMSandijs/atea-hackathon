param(
    [string]$RepoPath,
    [string]$ModelKey = 'qwen2.5-coder-7b-instruct',
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'

# This environment variable can be inherited from an Electron-based terminal.
# LM Studio needs its own Electron runtime, not Node mode.
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue

if (-not $RepoPath) {
    $RepoPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
}
$RepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $RepoPath 'AGENTS.md'))) {
    throw "Expected the repository root with AGENTS.md: $RepoPath"
}

function Find-Tool {
    param([string]$Name, [string]$Fallback)

    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    if (Test-Path -LiteralPath $Fallback) { return $Fallback }
    throw "Missing $Name. Follow docs/LOCAL-AI-SETUP.md, then reopen PowerShell."
}

$lms = Find-Tool 'lms.exe' (Join-Path $env:USERPROFILE '.lmstudio\bin\lms.exe')
$aider = Find-Tool 'aider.exe' (Join-Path $env:USERPROFILE '.local\bin\aider.exe')
$metadata = Join-Path $PSScriptRoot 'model-metadata.json'
$stateDirectory = Join-Path $env:LOCALAPPDATA 'Aider'
New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null

$availableModels = @(& $lms ls --json | ConvertFrom-Json)
if ($LASTEXITCODE -ne 0) { throw 'Could not list LM Studio models. Open LM Studio once, then retry.' }
if (-not ($availableModels | Where-Object modelKey -eq $ModelKey | Select-Object -First 1)) {
    throw "Model '$ModelKey' is not downloaded. Download Qwen2.5-Coder-7B-Instruct Q4_K_M in LM Studio first."
}

$loadedModels = @(& $lms ps --json | ConvertFrom-Json)
if ($LASTEXITCODE -ne 0) { throw 'Could not query loaded LM Studio models.' }
$loadedCoder = $loadedModels | Where-Object identifier -eq 'local-coder' | Select-Object -First 1
if ($loadedCoder -and $loadedCoder.modelKey -ne $ModelKey) {
    throw "Identifier 'local-coder' is already used by '$($loadedCoder.modelKey)'. Unload that model first."
}
if ($loadedCoder -and $loadedCoder.contextLength -ne 8192) {
    throw "The loaded model has $($loadedCoder.contextLength) context tokens; expected 8192. Unload and restart it."
}
if (-not $loadedCoder) {
    $freeGb = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB
    if ($freeGb -lt 7) {
        throw ('Only {0:N1} GB RAM is free. Close unused apps before loading the 7B model.' -f $freeGb)
    }
    & $lms load $ModelKey --context-length 8192 --identifier local-coder --yes
    if ($LASTEXITCODE -ne 0) { throw "Could not load model '$ModelKey'." }
}

& $lms server start --bind 127.0.0.1 --port 1234
if ($LASTEXITCODE -ne 0) { throw 'Could not start the LM Studio localhost server.' }

$listeners = @(Get-NetTCPConnection -LocalPort 1234 -State Listen -ErrorAction SilentlyContinue)
if ($listeners | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1') }) {
    throw 'Port 1234 is listening beyond this laptop. Bind the LM Studio server to 127.0.0.1 before continuing.'
}

$model = (Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/models' -TimeoutSec 15).data |
    Where-Object id -eq 'local-coder' |
    Select-Object -First 1
if (-not $model) { throw 'The local-coder API model is unavailable on localhost:1234.' }

if ($CheckOnly) {
    Write-Output 'Ready: local-coder on http://127.0.0.1:1234/v1'
    return
}

$env:LM_STUDIO_API_BASE = 'http://127.0.0.1:1234/v1'
$env:LM_STUDIO_API_KEY = 'local-only'

Push-Location $RepoPath
try {
    & $aider --model lm_studio/local-coder `
        --weak-model lm_studio/local-coder `
        --model-metadata-file $metadata `
        --no-auto-commits --no-dirty-commits --no-analytics --no-check-update `
        --no-gitignore --no-show-model-warnings `
        --chat-history-file (Join-Path $stateDirectory 'atea-chat-history.md') `
        --input-history-file (Join-Path $stateDirectory 'atea-input-history') `
        --read AGENTS.md --read docs/GROUND-RULES.md
}
finally {
    Pop-Location
}
