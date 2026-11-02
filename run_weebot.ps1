# Start weebot backend and web UI, each in its own PowerShell window.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Start-Process powershell -WorkingDirectory $root -ArgumentList '-NoExit', '-Command', "& '$py' -m weebot.interfaces.web.main"
Start-Process powershell -WorkingDirectory (Join-Path $root "weebot-ui") -ArgumentList '-NoExit', '-Command', 'npm run dev'

Write-Host "Backend starting. Web UI: http://localhost:3000"
