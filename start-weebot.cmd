@echo off
setlocal

rem Starts the Weebot API and Next.js interface in separate command windows.
rem This uses the virtual environment's Python directly, so PowerShell's
rem execution policy never needs to be changed.

set "WEEBOT_ROOT=%~dp0"
set "BACKEND_PYTHON=%WEEBOT_ROOT%.venv\Scripts\python.exe"
set "FRONTEND_DIR=%WEEBOT_ROOT%weebot-ui"

if not exist "%BACKEND_PYTHON%" (
  echo The Python virtual environment was not found:
  echo %BACKEND_PYTHON%
  echo Run the project setup first, then try again.
  pause
  exit /b 1
)

if not exist "%FRONTEND_DIR%\package.json" (
  echo The frontend folder was not found:
  echo %FRONTEND_DIR%
  pause
  exit /b 1
)

start "Weebot Backend" /D "%WEEBOT_ROOT%" cmd /k ""%BACKEND_PYTHON%" -m weebot.interfaces.web.main"
start "Weebot Frontend" /D "%FRONTEND_DIR%" cmd /k "npm.cmd run dev"

echo Weebot is starting in two new windows.
echo Open http://localhost:3000 once both services report that they are ready.
endlocal
