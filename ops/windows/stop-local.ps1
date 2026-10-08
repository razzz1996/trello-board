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
            $isProjectProcess = (
                $process.CommandLine -like ("*" + $ProjectRoot + "*") -or
                $process.CommandLine -like "*waitress*productivity.wsgi*" -or
                $process.CommandLine -like "*Caddyfile.development*"
            )
            if ($name -in @("python", "caddy") -and $isProjectProcess) {
                # The Windows venv Python launcher can leave an interpreter child
                # behind when Stop-Process targets only one PID. taskkill /T closes
                # the whole process tree so the old backend cannot keep port 8000.
                & taskkill.exe /PID $connection.OwningProcess /T /F 2>$null | Out-Null
            }
        }
    }
}

Start-Sleep -Milliseconds 400
foreach ($port in @(8000, 8080)) {
    $remaining = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($remaining) {
        throw "Unable to stop the eMEGA listener on port $port."
    }
}

Write-Host "eMEGA Productivity local web/scheduler/worker/proxy processes stopped." -ForegroundColor Yellow
Write-Host "PostgreSQL remains running as a Windows service." -ForegroundColor DarkGray
