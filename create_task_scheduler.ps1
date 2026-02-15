# ============================================================
# Create Task Scheduler Task - PowerShell Version
# Run this as Administrator if the batch file doesn't work
# ============================================================

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Create Task Scheduler Task - Stock Forecast Daily Run" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Get current directory
$projectDir = Get-Location
$scriptPath = Join-Path $projectDir "scripts\run_daily.bat"

Write-Host "Project Directory: $projectDir" -ForegroundColor Yellow
Write-Host "Script Path: $scriptPath" -ForegroundColor Yellow
Write-Host ""

# Check if script exists
if (-not (Test-Path $scriptPath)) {
    Write-Host "ERROR: Script not found at: $scriptPath" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please make sure you're running this from the project directory" -ForegroundColor Red
    Write-Host "and that scripts\run_daily.bat exists." -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if running as administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "WARNING: Not running as Administrator!" -ForegroundColor Yellow
    Write-Host "The task may be created but 'Run with highest privileges' may not stick." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "For best results:" -ForegroundColor Yellow
    Write-Host "  1. Right-click PowerShell" -ForegroundColor Yellow
    Write-Host "  2. Select 'Run as administrator'" -ForegroundColor Yellow
    Write-Host "  3. Run this script again" -ForegroundColor Yellow
    Write-Host ""
    $continue = Read-Host "Continue anyway? (y/n)"
    if ($continue -ne 'y') {
        exit 0
    }
}

# Delete existing task (if exists)
Write-Host "Checking for existing task..." -ForegroundColor Yellow
try {
    Unregister-ScheduledTask -TaskName "Stock Forecast Daily Run" -Confirm:$false -ErrorAction Stop
    Write-Host "Deleted existing task" -ForegroundColor Green
} catch {
    Write-Host "No existing task found (this is OK)" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Creating new task..." -ForegroundColor Yellow
Write-Host ""

try {
    # Create task action
    $action = New-ScheduledTaskAction `
        -Execute $scriptPath `
        -WorkingDirectory $projectDir.Path

    # Create trigger (daily at 23:05)
    $trigger = New-ScheduledTaskTrigger `
        -Daily `
        -At "23:05"

    # Create settings
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -WakeToRun `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 15)

    # Create principal (RUN WITH HIGHEST PRIVILEGES!)
    $principal = New-ScheduledTaskPrincipal `
        -UserId $env:USERNAME `
        -LogonType Interactive `
        -RunLevel Highest

    # Register the task
    Register-ScheduledTask `
        -TaskName "Stock Forecast Daily Run" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Automated daily stock forecasting for PLTR after US market close"

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "SUCCESS! Task created successfully!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Task Details:" -ForegroundColor Cyan
    Write-Host "  Name: Stock Forecast Daily Run" -ForegroundColor White
    Write-Host "  Schedule: Daily at 23:05 (11:05 PM)" -ForegroundColor White
    Write-Host "  Run Level: Highest" -ForegroundColor White
    Write-Host "  User: $env:USERNAME" -ForegroundColor White
    Write-Host "  Script: $scriptPath" -ForegroundColor White
    Write-Host ""
    Write-Host "The task will run daily at 23:05 PM." -ForegroundColor Green
    Write-Host ""
    Write-Host "To verify:" -ForegroundColor Cyan
    Write-Host "  1. Open Task Scheduler (taskschd.msc)" -ForegroundColor White
    Write-Host "  2. Find 'Stock Forecast Daily Run'" -ForegroundColor White
    Write-Host "  3. Right-click -> Properties -> General tab" -ForegroundColor White
    Write-Host "  4. Verify 'Run with highest privileges' is CHECKED" -ForegroundColor White
    Write-Host ""
    Write-Host "To test now:" -ForegroundColor Cyan
    Write-Host "  Right-click the task and select 'Run'" -ForegroundColor White
    Write-Host ""

} catch {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "ERROR: Failed to create task!" -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Error details:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Please try:" -ForegroundColor Yellow
    Write-Host "  1. Right-click PowerShell" -ForegroundColor White
    Write-Host "  2. Select 'Run as administrator'" -ForegroundColor White
    Write-Host "  3. Run this script again" -ForegroundColor White
    Write-Host ""
}

Read-Host "Press Enter to exit"
