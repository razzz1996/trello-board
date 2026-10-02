param(
    [string]$ProjectRoot = "C:\Users\PC 19\Desktop\PRODUCTIVITY WEBSITE",
    [string]$LanHost = "",
    [int]$Port = 5173
)
$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot

. (Join-Path $ProjectRoot "ops\windows\lan-network.ps1")
$lan = Get-ProductivityLanBinding
if (-not $LanHost) {
    $LanHost = $lan.Host
}

& (Join-Path $ProjectRoot "ops\windows\start-local.ps1") -ProjectRoot $ProjectRoot

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    foreach ($row in $listener) {
        Stop-Process -Id $row.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 500
}
$runner = Join-Path $ProjectRoot "ops\windows\run-vite-lan.ps1"
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"' + $runner + '"'),
    "-ProjectRoot", ('"' + $ProjectRoot + '"'), "-LanHost", $LanHost, "-Port", $Port
)

$url = "http://${LanHost}:$Port/"
$deadline = (Get-Date).AddSeconds(25)
do {
    Start-Sleep -Milliseconds 500
    try {
        $ready = Invoke-RestMethod -Uri ($url + "api/v1/health/ready") -TimeoutSec 2
        if ($ready.status -eq "ready") {
            Start-Process $url
            Write-Host "eMEGA team access is ready: $url" -ForegroundColor Green
            Write-Host "Allowed office subnet: $($lan.NetworkCidr)" -ForegroundColor DarkGray
            exit 0
        }
    } catch {
        # Continue until the startup deadline.
    }
} while ((Get-Date) -lt $deadline)

throw "LAN access did not become ready within 25 seconds for $url"
