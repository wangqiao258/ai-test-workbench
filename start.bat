@echo off
rem Start AI Test Workbench - http://127.0.0.1:8501
rem Keep this window open to keep the service running.
title AI-Test-Workbench 127.0.0.1:8501
cd /d "%~dp0"
rem 不生成 __pycache__，保持目录干净（本地小工具，牺牲的编译缓存可忽略）
set PYTHONDONTWRITEBYTECODE=1
echo Starting AI Test Workbench... open http://127.0.0.1:8501 in browser
echo Close this window to stop the service.
"C:\Users\hzs-w\.workbuddy\binaries\python\envs\ai-test-platform\Scripts\python.exe" app.py
pause
