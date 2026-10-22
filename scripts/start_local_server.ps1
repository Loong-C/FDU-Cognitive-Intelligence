param([int]$GpuLayers = 99, [int]$Port = 8081, [ValidateSet(512,1024)][int]$MaxTokens = 512)
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$runtimeDirectory = Join-Path $repositoryRoot 'outputs\runtime'
$serverCandidates = @(Get-ChildItem -LiteralPath (Join-Path $runtimeDirectory 'llama-b11669') -Filter 'llama-server.exe' -Recurse)
if ($serverCandidates.Count -ne 1) { throw 'Run scripts/bootstrap_local.py first; expected one llama-server.exe.' }
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) { throw "Port $Port is already in use." }
$modelFile = Join-Path $runtimeDirectory 'Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
if (-not (Test-Path -LiteralPath $modelFile)) { throw 'Model file is missing.' }
$logDirectory = Join-Path $runtimeDirectory ('server-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $logDirectory | Out-Null
$serverArguments = @('-m', ('"' + $modelFile + '"'), '--alias', 'qwen3-4b-instruct-2507-q4-k-m', '-ngl', $GpuLayers, '-c', '8192', '-np', '1', '-b', '512', '-ub', '128', '-fa', 'on', '--seed', '42', '--temp', '0', '-n', $MaxTokens, '--no-context-shift', '--no-cache-prompt', '--host', '127.0.0.1', '--port', $Port, '--no-webui', '--log-timestamps', '-lv', '4')
$serverProcess = Start-Process -FilePath $serverCandidates[0].FullName -ArgumentList $serverArguments -WorkingDirectory $serverCandidates[0].DirectoryName -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'stdout.log') -RedirectStandardError (Join-Path $logDirectory 'stderr.log') -PassThru
$startup = [ordered]@{pid=$serverProcess.Id; created_at=(Get-Date).ToUniversalTime().ToString('o'); backend_release='b11669'; gpu_layers_requested=$GpuLayers; port=$Port; log_directory=$logDirectory; arguments=$serverArguments; executable=$serverCandidates[0].FullName}
$startup | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runtimeDirectory 'server.json') -Encoding utf8
$startup | ConvertTo-Json -Depth 5
