@echo off
REM Run PowerShell script to create Task Scheduler task

echo.
echo Running PowerShell script to create task...
echo.
echo If this doesn't work, try:
echo   1. Right-click create_task_scheduler.ps1
echo   2. Select "Run with PowerShell"
echo.

PowerShell.exe -ExecutionPolicy Bypass -File "%~dp0create_task_scheduler.ps1"

pause
