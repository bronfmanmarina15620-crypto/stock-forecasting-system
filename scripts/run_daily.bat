@echo off
setlocal enabledelayedexpansion

REM ===== CONFIG =====
set PROJECT_DIR=C:\Users\User\Desktop\marinaTradingProjects\stock-forecasting-system
set TICKER=PLTR
set PYTHON=python
set RUNS_DIR=%PROJECT_DIR%\runs\%TICKER%
set LOG_DIR=%PROJECT_DIR%\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set TS=%date:~-4%%date:~3,2%%date:~0,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set TS=%TS: =0%
set LOGFILE=%LOG_DIR%\daily_%TICKER%_%TS%.log

echo ==== DAILY RUN START (%TICKER%) ==== > "%LOGFILE%"
echo Project: %PROJECT_DIR% >> "%LOGFILE%"
echo Time: %date% %time% >> "%LOGFILE%"

cd /d "%PROJECT_DIR%" || (echo FAIL: cannot cd to project >> "%LOGFILE%" & exit /b 1)

REM 1) Run pipeline
%PYTHON% run.py --ticker %TICKER% >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo FAIL: run.py returned non-zero >> "%LOGFILE%"
  exit /b 1
)

REM 2) Find latest RUN_ID folder
set LATEST_RUN=
for /f "delims=" %%D in ('dir "%RUNS_DIR%" /b /ad /o-d 2^>nul') do (
  set LATEST_RUN=%%D
  goto :found
)
:found

if "%LATEST_RUN%"=="" (
  echo FAIL: No run folders found in %RUNS_DIR% >> "%LOGFILE%"
  exit /b 1
)

set RUN_PATH=%RUNS_DIR%\%LATEST_RUN%
echo Latest run: %RUN_PATH% >> "%LOGFILE%"

REM 3) Validate run (artifact contract)
%PYTHON% validate_run.py --run "%RUN_PATH%" >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo FAIL: validate_run.py failed >> "%LOGFILE%"
  exit /b 1
)

echo PASS: Daily run + validation succeeded >> "%LOGFILE%"
exit /b 0
