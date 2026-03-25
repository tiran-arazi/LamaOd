# Windows Server 2019+ pilot (no Docker). Run from PowerShell after venv + pip install.
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path "$Root\.venv\Scripts\open-webui.exe")) {
    Write-Error "Missing venv. Create: py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt"
    exit 1
}

$EnvPath = "$Root\.env"
if (Test-Path $EnvPath) {
    Get-Content $EnvPath | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
        $pair = $_ -split '=', 2
        if ($pair.Length -eq 2) {
            Set-Item -Path "env:$($pair[0].Trim())" -Value $pair[1].Trim()
        }
    }
}

if (-not $env:DATA_DIR) { $env:DATA_DIR = Join-Path $Root "data" }
if (-not $env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL = "http://127.0.0.1:11434" }
if (-not $env:OFFLINE_MODE) { $env:OFFLINE_MODE = "true" }
if (-not $env:ENABLE_VERSION_UPDATE_CHECK) { $env:ENABLE_VERSION_UPDATE_CHECK = "false" }
if (-not $env:WEBUI_AUTH) { $env:WEBUI_AUTH = "false" }

New-Item -ItemType Directory -Force -Path $env:DATA_DIR | Out-Null
& "$Root\.venv\Scripts\open-webui.exe" serve --host 127.0.0.1 --port 8080
