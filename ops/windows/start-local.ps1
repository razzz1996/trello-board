param(
    [string]$ProjectRoot = "C:\Users\PC 19\Desktop\PRODUCTIVITY WEBSITE"
)
$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot

function Test-Port([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Test-ProjectProcess([string]$Needle) {
    return [bool](Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like ("*" + $Needle + "*") } |
        Select-Object -First 1)
}

$postgres = Get-Service postgresql-x64-18 -ErrorAction Stop
if ($postgres.Status -ne "Running") {
    throw "PostgreSQL is not running. Start the PostgreSQL 18 service as an administrator, then retry."
}

if (-not (Test-Port 8000)) {
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + (Join-Path $ProjectRoot "ops\windows\run-web.ps1") + '"')
    )
}

if (-not (Test-ProjectProcess "run-scheduler.ps1")) {
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + (Join-Path $ProjectRoot "ops\windows\run-scheduler.ps1") + '"')
    )
}

if (-not (Test-ProjectProcess "run-worker.ps1")) {
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + (Join-Path $ProjectRoot "ops\windows\run-worker.ps1") + '"')
    )
}

if (-not (Test-Port 8080)) {
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + (Join-Path $ProjectRoot "ops\windows\run-caddy-dev.ps1") + '"')
    )
}

$deadline = (Get-Date).AddSeconds(20)
do {
    Start-Sleep -Milliseconds 500
    try {
        $ready = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v1/health/ready" -TimeoutSec 2
        if ($ready.status -eq "ready") {
            Start-Process "http://127.0.0.1:8080/"
            Write-Host "eMEGA Productivity is ready: http://127.0.0.1:8080/" -ForegroundColor Green
            exit 0
        }
    } catch {
        # Continue until deadline.
    }
} while ((Get-Date) -lt $deadline)

throw "The local stack did not become ready within 20 seconds. Run ops\manage.py doctor for diagnostics."
