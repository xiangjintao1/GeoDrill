$ErrorActionPreference = 'Stop'
$docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $docker) {
    $docker = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
}
if (-not (Test-Path -LiteralPath $docker)) { throw 'Docker Desktop is not installed.' }
& $docker info --format '{{.ServerVersion}}' 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop first. WSL 2 and BIOS virtualization must be enabled.' }
$compose = Join-Path $PSScriptRoot 'compose.yaml'
& $docker compose -f $compose up -d --wait --wait-timeout 300
if ($LASTEXITCODE -ne 0) { throw 'Container startup failed. Check docker compose logs.' }
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        $response = Invoke-WebRequest 'http://127.0.0.1:8887' -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            Write-Host 'OpenSPG is ready: http://127.0.0.1:8887'
            & (Join-Path $PSScriptRoot 'start-embedding.ps1')
            & (Join-Path $PSScriptRoot 'start-web.ps1')
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 5
}
throw 'Containers started, but the OpenSPG page is not ready. Check server logs.'
