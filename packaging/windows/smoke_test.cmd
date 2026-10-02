@echo off
set "EXE=%~dp0..\..\dist\windows\MIDI-Studio\MIDI-Studio-selftest.exe"
if not exist "%EXE%" (echo Not built yet: run build_windows.cmd first. & pause & exit /b 1)
"%EXE%"
echo.
echo exit code: %errorlevel%
pause
