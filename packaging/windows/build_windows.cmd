@echo off
rem Double-click to build.  Bypasses the PowerShell script policy for this run only.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1"
echo.
if errorlevel 1 (echo BUILD FAILED - copy the red text above.) else (echo Build finished.)
pause
