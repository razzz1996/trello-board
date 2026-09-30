param(
    [string]$ProjectRoot = "C:\Users\PC 19\Desktop\PRODUCTIVITY WEBSITE",
    [int]$Port = 5173
)
$ErrorActionPreference = "Continue"

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($row in $listener) {
    $process = Get-Process -Id $row.OwningProcess -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -eq "node") {
        Stop-Process -Id $row.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

& (Join-Path $ProjectRoot "ops\windows\stop-local.ps1") -ProjectRoot $ProjectRoot
Write-Host "eMEGA team access stopped." -ForegroundColor Yellow
