param([string]$ConfigPath = 'configs/experiment_14b_v3.json', [int]$GpuLayers = -1)
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $repositoryRoot
try {
    & '.venv\Scripts\python.exe' 'scripts\server_14b.py' start --config $ConfigPath --gpu-layers $GpuLayers
    if ($LASTEXITCODE -ne 0) { throw '14B startup failed; inspect the printed diagnostic directory.' }
} finally { Pop-Location }
