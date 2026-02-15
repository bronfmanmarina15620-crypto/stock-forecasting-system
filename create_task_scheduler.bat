@echo off
REM ============================================================
REM Create Task Scheduler Task for Stock Forecast Daily Run
REM This script creates the task with all correct settings
REM ============================================================

echo.
echo ============================================================
echo Create Task Scheduler Task - Stock Forecast Daily Run
echo ============================================================
echo.

REM Get the current directory (project root)
set "PROJECT_DIR=%CD%"
set "SCRIPT_PATH=%PROJECT_DIR%\scripts\run_daily.bat"

echo Project Directory: %PROJECT_DIR%
echo Script Path: %SCRIPT_PATH%
echo.

REM Check if script exists
if not exist "%SCRIPT_PATH%" (
    echo ERROR: Script not found at: %SCRIPT_PATH%
    echo.
    echo Please make sure you're running this from the project directory
    echo and that scripts\run_daily.bat exists.
    echo.
    pause
    exit /b 1
)

REM Delete existing task (if exists)
echo Deleting existing task (if exists)...
schtasks /Delete /TN "Stock Forecast Daily Run" /F >nul 2>&1

REM Create the task
echo.
echo Creating new task...
echo.

schtasks /Create ^
    /TN "Stock Forecast Daily Run" ^
    /TR "\"%SCRIPT_PATH%\"" ^
    /SC DAILY ^
    /ST 23:05 ^
    /RL HIGHEST ^
    /F ^
    /RU "%USERNAME%" ^
    /IT

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================================
    echo SUCCESS! Task created successfully!
    echo ============================================================
    echo.
    echo Task Details:
    echo   Name: Stock Forecast Daily Run
    echo   Schedule: Daily at 23:05 (11:05 PM)
    echo   Run Level: Highest
    echo   User: %USERNAME%
    echo   Script: %SCRIPT_PATH%
    echo.
    echo The task will run daily at 23:05 PM.
    echo.
    echo To test it now:
    echo   1. Open Task Scheduler (taskschd.msc)
    echo   2. Find "Stock Forecast Daily Run"
    echo   3. Right-click and select "Run"
    echo.
) else (
    echo.
    echo ============================================================
    echo ERROR: Failed to create task!
    echo ============================================================
    echo.
    echo This might be because you need to run this script as Administrator.
    echo.
    echo Please:
    echo   1. Right-click on this script
    echo   2. Select "Run as administrator"
    echo   3. Try again
    echo.
)

pause
