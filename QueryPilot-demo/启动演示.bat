@echo off
setlocal
cd /d "%~dp0"
title QueryPilot Demo
REM ASCII-only. Do not add non-ASCII; cmd.exe will split UTF-8 as commands.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo Python 3.10+ not found. Install Python and check "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist "db\competition.duckdb" (
  echo Demo package incomplete: missing db\competition.duckdb
  pause
  exit /b 1
)
if not exist "ui\index.html" (
  echo Demo package incomplete: missing ui\index.html
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First launch: creating local environment...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv. Confirm Python 3.10+ is installed.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Failed to install dependencies. Check the network and try again.
    pause
    exit /b 1
  )
)

echo Starting demo. Keep this window open.
".venv\Scripts\python.exe" "%~dp0demo_server.py"
if errorlevel 1 pause
exit /b 0
