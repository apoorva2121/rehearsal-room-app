@echo off
cd /d "%~dp0"
title Rehearsal Room

python --version >nul 2>&1
if %errorlevel%==0 (
    python server.py
    goto done
)

py --version >nul 2>&1
if %errorlevel%==0 (
    py server.py
    goto done
)

echo Python was not found on this machine.
echo Install Python 3 from python.org, then run this again.

:done
echo.
echo The app has stopped. Press any key to close this window.
pause >nul
