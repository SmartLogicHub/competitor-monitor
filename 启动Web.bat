@echo off
setlocal
cd /d "%~dp0"

set "WEB_URL=http://127.0.0.1:8765"
set "HEALTH_URL=http://127.0.0.1:8765/api/health"

echo Starting competitor monitor Web console...

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-RestMethod -Uri '%HEALTH_URL%' -TimeoutSec 2; if ($r.status -eq 'ok') { Start-Process '%WEB_URL%'; exit 0 } } catch { }; exit 1"
if %ERRORLEVEL% EQU 0 exit /b 0

set "PY_EXE="
where pythonw >nul 2>nul
if not errorlevel 1 set "PY_EXE=pythonw"

if not defined PY_EXE (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python was not found. Please install Python or add it to PATH.
    pause
    exit /b 1
  )
  set "PY_EXE=python"
)

if not exist "competitor_monitor\web_server.py" (
  echo Web server entry was not found: competitor_monitor\web_server.py
  pause
  exit /b 1
)

echo Starting local service: %WEB_URL%
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PY_EXE%' -ArgumentList @('competitor_monitor\web_server.py') -WorkingDirectory '%CD%' -WindowStyle Hidden"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline = (Get-Date).AddSeconds(20); while ((Get-Date) -lt $deadline) { try { $r = Invoke-RestMethod -Uri '%HEALTH_URL%' -TimeoutSec 2; if ($r.status -eq 'ok') { Start-Process '%WEB_URL%'; exit 0 } } catch { }; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 (
  echo Web service failed to start or timed out.
  echo Please run this manually from the project folder:
  echo python competitor_monitor\web_server.py
  pause
  exit /b 1
)

exit /b 0
