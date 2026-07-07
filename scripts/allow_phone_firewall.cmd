@echo off
setlocal

set "RULE_NAME=Kalshi Research Bot 8765"
set "PORT=8765"

net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo Requesting administrator approval...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

netsh advfirewall firewall show rule name="%RULE_NAME%" >nul 2>&1
if "%errorlevel%"=="0" (
  netsh advfirewall firewall set rule name="%RULE_NAME%" new dir=in action=allow protocol=TCP localport=%PORT% remoteip=localsubnet profile=any
) else (
  netsh advfirewall firewall add rule name="%RULE_NAME%" dir=in action=allow protocol=TCP localport=%PORT% remoteip=localsubnet profile=any
)

echo.
echo Firewall rule is ready for local phone access on port %PORT%.
echo Open this on your phone: http://100.110.164.197:8765
echo.
pause
