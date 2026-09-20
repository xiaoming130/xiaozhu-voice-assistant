@echo off
rem speak.bat - launcher for the TTS notifier
rem keep this file ASCII-only; %~dp0 resolves the (possibly non-ASCII) folder at runtime
chcp 65001 >nul
pushd "%~dp0"
if "%~1"=="" (
    ".venv\Scripts\python.exe" "speak.py" --tasks
) else (
    ".venv\Scripts\python.exe" "speak.py" %*
)
popd
