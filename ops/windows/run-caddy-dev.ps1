param(
    [string]$ProjectRoot = "C:\Users\PC 19\Desktop\PRODUCTIVITY WEBSITE"
)
$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot

$caddy = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\CaddyServer.Caddy_*\caddy.exe" |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $caddy) { throw "Caddy is not installed." }

& $caddy run --config (Join-Path $ProjectRoot "config\Caddyfile.development")
