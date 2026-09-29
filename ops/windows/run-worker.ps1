param(
    [string]$ProjectRoot = "C:\Users\PC 19\Desktop\PRODUCTIVITY WEBSITE"
)
$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
. (Join-Path $ProjectRoot "ops\windows\runtime-env.ps1") -ProjectRoot $ProjectRoot
& $python backend\manage.py runworker
