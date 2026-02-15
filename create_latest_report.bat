@echo off
REM Create latest_report.html from the most recent run

echo.
echo ============================================================
echo Create latest_report.html
echo ============================================================
echo.

REM Find latest run
for /f "delims=" %%i in ('dir /b /ad /o-d "runs\PLTR" 2^>nul ^| findstr /r "^20"') do (
    set "LATEST_RUN=%%i"
    goto :found
)

echo ERROR: No run found in runs\PLTR
echo.
pause
exit /b 1

:found
set "RUN_PATH=runs\PLTR\%LATEST_RUN%"

echo Latest run: %LATEST_RUN%
echo.

if not exist "%RUN_PATH%\final_report.html" (
    echo ERROR: final_report.html not found in %RUN_PATH%
    echo.
    pause
    exit /b 1
)

echo Copying %RUN_PATH%\final_report.html
echo      to latest_report.html
echo.

copy /y "%RUN_PATH%\final_report.html" "latest_report.html"

if %ERRORLEVEL% EQU 0 (
    echo [OK] Success!
    echo.
    echo You can now open latest_report.html
    echo.
    choice /C YN /M "Open latest_report.html now? (Y/N)"
    if errorlevel 2 goto :end
    if errorlevel 1 start latest_report.html
) else (
    echo [X] Failed to copy file
)

:end
echo.
pause
