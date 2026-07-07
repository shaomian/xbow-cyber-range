@echo off
REM XBow CyberRange launcher - pure ASCII to avoid cmd codepage issues.
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"

echo ============================================================
echo   XBow CyberRange platform launcher
echo ============================================================

REM ---- check python ----
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] python not found in PATH. Install Python 3.10+ first.
  pause
  exit /b 1
)

REM ---- check npm ----
where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm not found in PATH. Install Node.js 18+ first.
  pause
  exit /b 1
)

REM ---- backend deps: install if fastapi/docker missing ----
python -c "import fastapi, docker" >nul 2>nul
if errorlevel 1 (
  echo [setup] backend deps missing, installing...
  pushd "%ROOT%backend"
  python -m pip install -r requirements.txt
  popd
) else (
  echo [ok] backend deps present.
)

REM ---- frontend deps: install if node_modules absent ----
if not exist "%ROOT%frontend\node_modules" (
  echo [setup] frontend deps missing, installing...
  pushd "%ROOT%frontend"
  call npm install
  popd
) else (
  echo [ok] frontend deps present.
)

echo.
echo [1/2] Starting backend  (uvicorn @ http://127.0.0.1:8000) ...
start "XBowCyberRange-Backend" cmd /k "cd /d %ROOT%backend && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

timeout /t 3 /nobreak >nul

echo [2/2] Starting frontend (vite    @ http://127.0.0.1:5173) ...
start "XBowCyberRange-Frontend" cmd /k "cd /d %ROOT%frontend && npm run dev"

echo.
echo ============================================================
echo   Started. Open in browser:
echo     Frontend :  http://127.0.0.1:5173
echo     API docs :  http://127.0.0.1:8000/docs
echo     Login    :  admin / admin123   (change it ASAP)
echo ============================================================
echo.
echo Two console windows were opened. Close them to stop services.
endlocal
