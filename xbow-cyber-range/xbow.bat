@echo off
rem XBow CyberRange platform manager (Windows). All logic lives in xbow.ps1.
rem Usage: xbow.bat start [--prod] / stop / restart / status / logs / install
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0xbow.ps1" %*
exit /b %ERRORLEVEL%
