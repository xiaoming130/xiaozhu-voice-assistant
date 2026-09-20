@echo off
rem start_watch.bat - start the headphone-arrival dressing briefing watcher
rem ASCII-only on purpose; %~dp0 resolves the real (non-ASCII) folder at runtime
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
pushd "%~dp0"
echo ============================================
echo   Headphone watch - starting...
echo   Target device : Realtek(R) Audio headset
echo   On arrival    : launch desktop dressing exe + speak
echo ============================================
echo.
".venv\Scripts\python.exe" "watch_ctl.py" start
echo.
".venv\Scripts\python.exe" "watch_ctl.py" status
echo.
pause
popd
