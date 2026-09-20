@echo off
rem play_once.bat - play the dressing briefing once, right now (no reboot needed)
rem ASCII-only on purpose; %~dp0 resolves the real (non-ASCII) folder at runtime
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
pushd "%~dp0"
echo ============================================
echo   Dressing briefing - play once now
echo   (launch exe + speak + close window)
echo ============================================
echo.
".venv\Scripts\python.exe" "dressing_brief.py"
echo.
echo Done. This window can be closed.
pause
popd
