@echo off
rem AI Test Workbench - resident runner
rem Polls queued runs on the platform and executes them.
rem Keep this window open to keep the runner alive; close it to stop.
title AI-Test-Workbench Runner
cd /d "%~dp0"

rem Keep the directory clean (no __pycache__)
set PYTHONDONTWRITEBYTECODE=1

if not defined PLATFORM_URL set PLATFORM_URL=http://127.0.0.1:8501

rem Read the first line of data\api-token.txt (never hardcode the token here)
for /f "usebackq delims=" %%i in ("data\api-token.txt") do (
  if not defined API_TOKEN set API_TOKEN=%%i
)

rem Test env uses a self-signed certificate
set VERIFY_SSL=0
set POLL_SECONDS=5
rem UI runs: set HEADLESS=0 to watch the browser (selector debugging)
set HEADLESS=1

set PY="C:\Users\hzs-w\.workbuddy\binaries\python\envs\ai-test-platform\Scripts\python.exe"

if "%API_TOKEN%"=="" (
  echo [ERROR] Cannot read token from data\api-token.txt
  pause
  exit /b 1
)

rem Chromium is needed only by UI cases; install it once on first run.
if not exist "%LOCALAPPDATA%\ms-playwright" (
  echo [setup] First run: installing Chromium for UI cases...
  %PY% -m playwright install chromium
)

echo Runner starting. Platform: %PLATFORM_URL%
echo Any queued run will be executed automatically. Close this window to stop.
echo.
%PY% -m runner
pause
