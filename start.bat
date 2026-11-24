@echo off
setlocal
rem Starts LITMO with the project's own Python environment (.venv).
rem Works from anywhere, e.g. by double-click: first switch to the folder of this file.
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

rem A server is already running (e.g. in another window): just open the tool instead of failing on the port.
rem (Get-NetTCPConnection instead of netstat: netstat prints the state in the Windows language, e.g. ABHOEREN.)
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 (
    echo A server is already running on port 8000 - opening the tool in the browser.
    start "" http://localhost:8000/app
    rem short pause so the message can be read (ping instead of timeout: works without a console too)
    ping -n 3 127.0.0.1 >nul
    exit /b 0
)

if not exist "%VENV_PY%" (
    echo Creating the Python environment .venv ...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist "%VENV_PY%" (
        echo.
        echo ERROR: Could not create .venv. Please install Python 3 from https://www.python.org/
        pause
        exit /b 1
    )
)

echo Checking dependencies ...
"%VENV_PY%" -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 (
    echo WARNING: Installing the dependencies failed - trying to start anyway.
)

echo.
echo LITMO: http://localhost:8000/app
echo Stop with Ctrl+C. Keep this window open while you work.
echo.
"%VENV_PY%" -m uvicorn app:app --port 8000

echo.
echo The server has stopped.
pause
