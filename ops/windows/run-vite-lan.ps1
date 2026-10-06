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

# Bind to all local interfaces so DHCP address changes do not kill the Vite
# listener. Windows Firewall remains restricted to the office subnet.
$BindHost = "0.0.0.0"
$env:PRODUCTIVITY_LAN_HOST = $LanHost
$env:PRODUCTIVITY_LAN_HOSTNAME = [System.Net.Dns]::GetHostName()

Set-Location (Join-Path $ProjectRoot "frontend")
$npm = "C:\Program Files\nodejs\npm.cmd"
if (-not (Test-Path $npm)) {
    throw "npm was not found at $npm"
}

& $npm run dev -- --host $BindHost --port $Port --strictPort
