param(
    [string]$ProjectRoot = "C:\Users\PC 19\Desktop\PRODUCTIVITY WEBSITE",
    [string]$LanHost = "",
    [int]$Port = 5173
)
$ErrorActionPreference = "Stop"

if (-not $LanHost) {
    . (Join-Path $ProjectRoot "ops\windows\lan-network.ps1")
    $LanHost = (Get-ProductivityLanBinding).Host
}

Set-Location (Join-Path $ProjectRoot "frontend")
$npm = "C:\Program Files\nodejs\npm.cmd"
if (-not (Test-Path $npm)) {
    throw "npm was not found at $npm"
}

& $npm run dev -- --host $LanHost --port $Port --strictPort
