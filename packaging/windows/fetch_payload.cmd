@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fetch_payload.ps1"
echo.
if errorlevel 1 (echo FETCH FAILED - copy the red text above.) else (echo Payload ready.)
pause
