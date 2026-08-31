@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev-windows.ps1" %*
exit /b %ERRORLEVEL%
