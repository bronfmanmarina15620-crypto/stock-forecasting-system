# PRIORITY 0: Exit Code Fixes - Step by Step Guide

## Goal
Ensure run.py and scripts/run_daily.bat use exit codes correctly so Task Scheduler shows reliable success/failure.

---

## Part 1: Update run_daily.bat

### Current Status
The current run_daily.bat has extra features (cache clearing, validation, latest_report copying).

### What We Need
A SIMPLE version that ONLY focuses on exit codes for testing.

### Steps

1. **Backup current version:**
```cmd
cd C:\Users\User\Desktop\marinaTradingProjects\stock-forecasting-system\scripts
copy run_daily.bat run_daily_full.bat.backup
```

2. **Replace with simple version:**

Download `run_daily_simple.bat` from above and:
```cmd
copy run_daily_simple.bat scripts\run_daily.bat
```

Or manually edit scripts\run_daily.bat to contain:

```batch
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
```

---

## Part 2: Verify run.py Exit Codes

### Check Current Behavior

Run this to test:
```cmd
cd C:\Users\User\Desktop\marinaTradingProjects\stock-forecasting-system

python run.py --ticker PLTR
echo Exit code: %ERRORLEVEL%
```

**Expected:**
- If successful: `Exit code: 0`
- If failed: `Exit code: 1` (or other non-zero)

### Fix run.py if Needed

The end of run.py should look like this:

```python
if __name__ == "__main__":
    try:
        success = main()
        if success:
            print("\n[OK] All agents completed successfully\n")
            print(f"Final Report: {report_path}")
            # ... other prints ...
            sys.exit(0)  # SUCCESS
        else:
            print("\n[FAIL] Some agents failed")
            sys.exit(1)  # FAILURE
    except Exception as e:
        print(f"\n[ERROR] Unhandled exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)  # FAILURE
```

**Key points:**
- `sys.exit(0)` = success
- `sys.exit(1)` = failure
- Always call sys.exit() explicitly
- Catch all exceptions

---

## Part 3: Test the Setup

### Test 1: Manual Run
```cmd
cd C:\Users\User\Desktop\marinaTradingProjects\stock-forecasting-system
scripts\run_daily.bat
```

**Look for:**
```
==============================================
PASS: run.py completed successfully
==============================================
```

**Check exit code:**
```cmd
echo %ERRORLEVEL%
```

Should be `0`.

### Test 2: Task Scheduler

1. Open Task Scheduler: `taskschd.msc`
2. Find: Stock Forecast Daily Run
3. Right-click → Run
4. Wait 3-4 minutes
5. Refresh (F5)
6. Check:
   - **Last Run Time:** [just now]
   - **Last Run Result:** `The operation completed successfully. (0x0)`

**If you see (0x0) = SUCCESS!** ✅

**If you see (0x1) = Something wrong** ❌

### Test 3: Check Logs

Task Scheduler doesn't create logs with this simple version, but you can add logging:

**Enhanced version with logging:**

```batch
@echo off
setlocal

set LOGFILE=logs\daily_run_%date:~10,4%%date:~4,2%%date:~7,2%_%time:~0,2%%time:~3,2%%time:~6,2%.log
set LOGFILE=%LOGFILE: =0%

echo ============================================== >> %LOGFILE%
echo DAILY RUN START (PLTR) >> %LOGFILE%
echo Time: %date% %time% >> %LOGFILE%
echo ============================================== >> %LOGFILE%

cd /d C:\Users\User\Desktop\marinaTradingProjects\stock-forecasting-system

python run.py --ticker PLTR >> %LOGFILE% 2>&1
set EXIT_CODE=%ERRORLEVEL%

echo. >> %LOGFILE%
echo ============================================== >> %LOGFILE%
if %EXIT_CODE% EQU 0 (
    echo PASS: run.py completed successfully >> %LOGFILE%
    echo PASS: run.py completed successfully
) else (
    echo FAIL: run.py returned exit code %EXIT_CODE% >> %LOGFILE%
    echo FAIL: run.py returned exit code %EXIT_CODE%
)
echo ============================================== >> %LOGFILE%

exit /b %EXIT_CODE%
```

---

## Part 4: Validation Checklist

After implementing, verify:

- [ ] run.py returns 0 on success
- [ ] run.py returns 1 on failure
- [ ] run_daily.bat captures exit code
- [ ] run_daily.bat prints PASS/FAIL clearly
- [ ] run_daily.bat returns exit code to Task Scheduler
- [ ] Task Scheduler shows (0x0) on success
- [ ] Task Scheduler shows (0x1) on failure
- [ ] No Unicode encoding errors

---

## Expected Results

### On Success:
**Console:**
```
==============================================
DAILY RUN START (PLTR)
==============================================

[All the run.py output...]

Run Status: SUCCESS

[OK] All agents completed successfully

Final Report: runs\PLTR\...

==============================================
PASS: run.py completed successfully
==============================================
```

**Task Scheduler:**
- Last Run Result: `The operation completed successfully. (0x0)`

### On Failure:
**Console:**
```
==============================================
DAILY RUN START (PLTR)
==============================================

[run.py output with errors...]

==============================================
FAIL: run.py returned exit code 1
==============================================
```

**Task Scheduler:**
- Last Run Result: `The operation completed successfully. (0x1)`

Note: Windows says "completed successfully" even for 0x1, but the exit code tells the truth!

---

## Troubleshooting

### Problem: Always shows PASS even when it failed
**Solution:** run.py doesn't call sys.exit(1) on failure. Fix run.py.

### Problem: Task Scheduler shows (0x41301) "Task has not run"
**Solution:** Task not configured correctly. Check:
- Run with highest privileges ✓
- Run whether user is logged on or not ✓

### Problem: Task Scheduler shows "Success (0x0)" but nothing happened
**Solution:** Path in Actions tab is wrong. Verify full path to run_daily.bat.

### Problem: Unicode errors still appearing
**Solution:** run.py still has Unicode characters. Re-run fix_unicode_encoding.py.

---

## Next Steps After PRIORITY 0

Once exit codes work reliably:
1. Add back latest_report.html copying (optional)
2. Add back validation (optional)
3. Move to PRIORITY 1: Implementing full artifact contract

But FIRST make sure PRIORITY 0 works perfectly!
