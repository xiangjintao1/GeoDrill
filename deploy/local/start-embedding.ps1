$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $workspace '.venv/Scripts/python.exe'
$script = Join-Path $PSScriptRoot 'embedding_server.py'
$logs = 'D:\GeoDrill-local\logs'
try {
    $health = Invoke-RestMethod 'http://127.0.0.1:9230/health' -TimeoutSec 3
    if ($health.model -eq 'BAAI/bge-small-zh-v1.5') {
        Write-Host 'Local embeddings are already ready.'
        exit 0
    }
} catch { }
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$process = Start-Process -FilePath $python -ArgumentList @('-u', ('"' + $script + '"')) `
    -WorkingDirectory $workspace -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logs 'embedding.out.log') `
    -RedirectStandardError (Join-Path $logs 'embedding.err.log')
Write-Host "Embedding service PID: $($process.Id). First launch downloads the model into D:\GeoDrill-local\models."
