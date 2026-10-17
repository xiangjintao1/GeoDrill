$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $workspace '.venv/Scripts/python.exe'
$script = Join-Path $workspace 'kag/examples/drilling/web.py'
$logs = 'D:\GeoDrill-local\logs'
try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8090/health' -TimeoutSec 3
    if ($health.app -eq 'geodrill') { Write-Host 'GeoDrill is ready: http://127.0.0.1:8090'; exit 0 }
} catch { }
New-Item -ItemType Directory -Path $logs -Force | Out-Null
Start-Process -FilePath $python -ArgumentList @('-u', ('"' + $script + '"')) `
    -WorkingDirectory $workspace -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logs 'workbench.out.log') `
    -RedirectStandardError (Join-Path $logs 'workbench.err.log') | Out-Null
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8090/health' -TimeoutSec 2
        if ($health.app -eq 'geodrill') { Write-Host 'GeoDrill is ready: http://127.0.0.1:8090'; exit 0 }
    } catch { }
}
throw "GeoDrill did not start. Check $logs/workbench.err.log"
