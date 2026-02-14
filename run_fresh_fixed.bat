@echo off
title Stock Forecast - Fresh Run

echo.
echo ============================================================
echo Stock Forecast - Fresh Data Run
echo ============================================================
echo.

REM Clear cache
if exist data_cache (
    echo Deleting old cache...
    rmdir /s /q data_cache
    echo Cache deleted
) else (
    echo No cache found
)

echo.
echo Running system...
echo.

REM Run
python run.py --ticker PLTR

echo.
echo ============================================================
if %ERRORLEVEL% EQU 0 (
    echo SUCCESS!
) else (
    echo FAILED!
)
echo ============================================================
echo.
pause
