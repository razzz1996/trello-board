param(
    [string]$ProjectRoot = "C:\Users\PC 19\Desktop\PRODUCTIVITY WEBSITE"
)
$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Virtual environment Python is missing." }
. (Join-Path $ProjectRoot "ops\windows\runtime-env.ps1") -ProjectRoot $ProjectRoot
& $python -m waitress --listen=127.0.0.1:8000 --threads=8 productivity.wsgi:application
