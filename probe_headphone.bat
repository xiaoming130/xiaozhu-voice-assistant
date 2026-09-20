@echo off
rem probe_headphone.bat - watch whether the headset power state is visible to Windows
rem ASCII-only on purpose; %~dp0 resolves the real (non-ASCII) folder at runtime
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
pushd "%~dp0"
echo ============================================================
echo   Headphone state probe  /  耳机状态探针
echo ============================================================
echo   It will watch for 150 seconds. Please do this while it runs:
echo.
echo     1) POWER OFF your headset, wait about 15 seconds
echo     2) POWER ON  your headset again
echo.
echo   Any change will be printed with a *** mark.
echo ============================================================
echo.
".venv\Scripts\python.exe" "device_state_probe.py" 150
echo.
echo ------------------------------------------------------------
echo Done. Log saved to:  device_state_probe.log
echo ------------------------------------------------------------
pause
popd
