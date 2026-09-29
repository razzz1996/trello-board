param(
    [string]$ProjectRoot = "C:\Users\PC 19\Desktop\PRODUCTIVITY WEBSITE"
)
$ErrorActionPreference = "Continue"

$backgroundPython = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -match "^python" -and
        $_.CommandLine -and (
            $_.CommandLine -like "*backend\manage.py runscheduler*" -or
            $_.CommandLine -like "*backend\manage.py runworker*"
        )
    }

foreach ($process in $backgroundPython) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

foreach ($port in @(8000, 8080)) {
    $connections = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $connection.OwningProcess) -ErrorAction SilentlyContinue
        if ($process) {
            $name = [IO.Path]::GetFileNameWithoutExtension($process.Name)
            if ($name -in @("python", "caddy")) {
                Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

Write-Host "eMEGA Productivity local web/scheduler/worker/proxy processes stopped." -ForegroundColor Yellow
Write-Host "PostgreSQL remains running as a Windows service." -ForegroundColor DarkGray
