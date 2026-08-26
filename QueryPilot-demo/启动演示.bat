@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
title QueryPilot Demo

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  mshta "javascript:alert('未检测到 Python 3.10+。请先安装 Python（勾选 Add python.exe to PATH），然后再次双击本文件。');close()"
  exit /b 1
)

if not exist "db\competition.duckdb" (
  mshta "javascript:alert('演示包不完整：缺少 db\\competition.duckdb');close()"
  exit /b 1
)
if not exist "ui\index.html" (
  mshta "javascript:alert('演示包不完整：缺少 ui\\index.html');close()"
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo 首次启动，正在准备本机环境（只需一次）...
  %PY% -m venv .venv
  if errorlevel 1 (
    mshta "javascript:alert('创建虚拟环境失败。请确认已安装 Python 3.10+。');close()"
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    mshta "javascript:alert('依赖安装失败。请检查网络后再次双击本文件。');close()"
    pause
    exit /b 1
  )
)

echo 正在启动演示，请保持本窗口打开...
".venv\Scripts\python.exe" "%~dp0demo_server.py"
if errorlevel 1 pause
exit /b 0
