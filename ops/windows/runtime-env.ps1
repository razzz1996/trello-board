param(
    [string]$ProjectRoot = "C:\Users\PC 19\Desktop\PRODUCTIVITY WEBSITE"
)
$ErrorActionPreference = "Stop"

. (Join-Path $ProjectRoot "ops\windows\lan-network.ps1")
$lan = Get-ProductivityLanBinding

$env:PRODUCTIVITY_DB_USER = "productivity_app"
$env:PRODUCTIVITY_DB_PASSWORD_FILE = Join-Path $ProjectRoot "runtime\secrets\postgres_app_secret.txt"
$env:PRODUCTIVITY_DB_HOST = "127.0.0.1"
$env:PRODUCTIVITY_DB_PORT = "5432"
$env:PRODUCTIVITY_LAN_HOST = $lan.Host
$env:PRODUCTIVITY_MAINTENANCE_DB_USER = "productivity_maintenance"
$env:PRODUCTIVITY_MAINTENANCE_DB_PASSWORD_FILE = Join-Path $ProjectRoot "runtime\secrets\postgres_maintenance_secret.txt"
$env:PYTHONPATH = Join-Path $ProjectRoot "backend"

foreach ($required in @(
    $env:PRODUCTIVITY_DB_PASSWORD_FILE,
    $env:PRODUCTIVITY_MAINTENANCE_DB_PASSWORD_FILE
)) {
    if (-not (Test-Path $required)) {
        throw "Required runtime secret file is missing: $required"
    }
}
