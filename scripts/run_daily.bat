@echo off
REM ============================================================
REM Daily Stock Forecast Automated Run - Improved Version
REM Copies report BEFORE validation to ensure latest_report.html exists
REM ============================================================

setlocal EnableDelayedExpansion

REM Set timestamp for logging
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set "TIMESTAMP=%dt:~0,8%_%dt:~8,6%"

REM Change to script directory
cd /d "%~dp0.."

REM Setup log directory
if not exist "logs" mkdir logs
set "LOGFILE=logs\daily_run_%TIMESTAMP%.log"

REM Start logging
echo ============================================================ > "%LOGFILE%"
echo Daily Stock Forecast Run >> "%LOGFILE%"
echo Timestamp: %TIMESTAMP% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo. >> "%LOGFILE%"

REM Clear cache for fresh data
echo [%time%] Clearing cache... >> "%LOGFILE%"
if exist data_cache (
    rmdir /s /q data_cache >> "%LOGFILE%" 2>&1
    echo [%time%] Cache cleared >> "%LOGFILE%"
) else (
    echo [%time%] No cache to clear >> "%LOGFILE%"
)

REM Run the system
echo [%time%] Starting system run... >> "%LOGFILE%"
python run.py --ticker PLTR >> "%LOGFILE%" 2>&1
set RUN_EXIT=%ERRORLEVEL%

if %RUN_EXIT% NEQ 0 (
    echo [%time%] ERROR: System run failed with exit code %RUN_EXIT% >> "%LOGFILE%"
    echo FAILED: System run >> "%LOGFILE%"
    exit /b %RUN_EXIT%
)

echo [%time%] System run completed successfully >> "%LOGFILE%"

REM Find latest run directory
for /f "delims=" %%i in ('dir /b /ad /o-d "runs\PLTR" 2^>nul ^| findstr /r "^20"') do (
    set "LATEST_RUN=%%i"
    goto :found_run
)

echo [%time%] ERROR: No run directory found >> "%LOGFILE%"
echo FAILED: No run directory >> "%LOGFILE%"
exit /b 1

:found_run
set "RUN_PATH=runs\PLTR\%LATEST_RUN%"
echo [%time%] Latest run: %RUN_PATH% >> "%LOGFILE%"

REM Copy report BEFORE validation (so it's always available)
echo [%time%] Copying latest report... >> "%LOGFILE%"
if exist "%RUN_PATH%\final_report.html" (
    copy /y "%RUN_PATH%\final_report.html" "latest_report.html" >nul 2>&1
    echo [%time%] Latest report copied to latest_report.html >> "%LOGFILE%"
) else (
    echo [%time%] WARNING: final_report.html not found in run >> "%LOGFILE%"
)

REM Validate the run
echo [%time%] Validating run... >> "%LOGFILE%"
python validate_run.py --run "%RUN_PATH%" >> "%LOGFILE%" 2>&1
set VALIDATE_EXIT=%ERRORLEVEL%

if %VALIDATE_EXIT% NEQ 0 (
    echo [%time%] ERROR: Validation failed with exit code %VALIDATE_EXIT% >> "%LOGFILE%"
    echo FAILED: Validation >> "%LOGFILE%"
    exit /b %VALIDATE_EXIT%
)

echo [%time%] Validation passed >> "%LOGFILE%"

REM Success
echo. >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo SUCCESS: Daily run completed and validated >> "%LOGFILE%"
echo Run ID: %LATEST_RUN% >> "%LOGFILE%"
echo Log: %LOGFILE% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

exit /b 0
