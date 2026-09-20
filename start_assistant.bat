@echo off
rem start_assistant.bat - launch the voice assistant
rem ASCII-only on purpose; %~dp0 resolves the real folder at runtime
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
pushd "%~dp0"
echo ============================================
echo   Voice assistant starting...
echo   Say "Xiao Zhu" to wake it up.
echo   Ctrl+C or close this window to stop.
echo ============================================
echo.
".venv\Scripts\python.exe" "assistant.py" %*
echo.
echo Assistant stopped.
popd
pause
