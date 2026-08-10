@echo off
title Tattoo Bot
cd /d C:\Projects\tattoo_bot
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo ========================================
echo   Tattoo Bot - tatoo_asbest_best_bot
echo ========================================
echo.
echo Checking for running instances...

REM Kill old instances (only main.py)
for /f "tokens=2" %%i in ('wmic process where "commandline like '%%main.py%%' and name='python.exe'" get processid /value 2^>nul ^| find "ProcessId="') do (
    echo Killing old instance PID: %%i
    taskkill /F /PID %%i >nul 2>&1
)

timeout /t 2 /nobreak >nul
echo.
echo Starting bot...
echo ----------------------------------------

python main.py

echo.
echo ----------------------------------------
echo Bot stopped. Press any key...
pause >nul