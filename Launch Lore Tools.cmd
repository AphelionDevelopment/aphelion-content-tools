@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\launcher\launch.ps1" -RepositoryRoot "%~dp0."
if errorlevel 1 pause
endlocal
