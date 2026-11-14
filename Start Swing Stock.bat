@echo off
setlocal
cd /d "%~dp0"

set "URL=http://127.0.0.1:8000"

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/defaults' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
if not errorlevel 1 (
    start "" "%URL%"
    exit /b 0
)

start "" /b powershell -NoProfile -Command "$url='http://127.0.0.1:8000/api/defaults'; for ($i=0; $i -lt 30; $i++) { try { $r=Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 1; if ($r.StatusCode -eq 200) { Start-Process 'http://127.0.0.1:8000'; exit 0 } } catch {}; Start-Sleep -Seconds 1 }; Write-Error 'The app did not start within 30 seconds. Check the Uvicorn terminal window.'"
python -m uvicorn main:app --host 127.0.0.1 --port 8000
