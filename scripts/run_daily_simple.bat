@echo off
setlocal

echo ==============================================
echo DAILY RUN START (PLTR)
echo ==============================================

cd /d C:\Users\User\Desktop\marinaTradingProjects\stock-forecasting-system

python run.py --ticker PLTR
set EXIT_CODE=%ERRORLEVEL%

echo.
echo ==============================================
if %EXIT_CODE% EQU 0 (
    echo PASS: run.py completed successfully
) else (
    echo FAIL: run.py returned exit code %EXIT_CODE%
)
echo ==============================================

exit /b %EXIT_CODE%
