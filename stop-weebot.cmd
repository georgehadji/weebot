@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Stops the processes listening on Weebot's standard backend/frontend ports.
rem It does not scan for or stop unrelated Python or Node.js processes.

call :stop_port 8000 "Weebot Backend"
call :stop_port 3000 "Weebot Frontend"

echo.
echo Weebot stop command finished.
endlocal
exit /b 0

:stop_port
set "PORT=%~1"
set "LABEL=%~2"
set "PID="

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do set "PID=%%P"

if not defined PID (
  echo %LABEL% is not running on port %PORT%.
  exit /b 0
)

echo Stopping %LABEL% ^(PID %PID%^)...
taskkill /PID %PID% /T /F >nul 2>&1
if errorlevel 1 (
  echo Could not stop %LABEL%. It may require an elevated terminal.
) else (
  echo %LABEL% stopped.
)
exit /b 0
