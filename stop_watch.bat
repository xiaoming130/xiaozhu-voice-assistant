@echo off
rem stop_watch.bat - stop the headphone-arrival dressing briefing watcher
rem ASCII-only on purpose; %~dp0 resolves the real (non-ASCII) folder at runtime
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
pushd "%~dp0"
echo ============================================
echo   Headphone watch - stopping...
echo ============================================
echo.
".venv\Scripts\python.exe" "watch_ctl.py" stop
echo.
".venv\Scripts\python.exe" "watch_ctl.py" status
echo.
pause
popd
