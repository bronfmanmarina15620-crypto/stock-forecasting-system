# Manual Task Scheduler Setup - If Automatic Fails

## Problem

The "Run with highest privileges" checkbox keeps unchecking itself.

This is a Windows permission issue.

---

## Solution 1: Automatic (Recommended)

### Step 1: Run as Administrator

**Right-click on:**
```
create_task_scheduler.bat
```

**Select:**
```
Run as administrator
```

**Click Yes** when Windows asks for permission.

**What it does:**
1. Deletes old task (if exists)
2. Creates new task with ALL correct settings
3. Sets "Run with highest privileges" automatically

---

## Solution 2: Manual (If automatic fails)

### Step 1: Delete Old Task

1. Open Task Scheduler: `Win + R` → `taskschd.msc`
2. Find: `Stock Forecast Daily Run`
3. Right-click → **Delete**
4. Confirm: **Yes**

### Step 2: Create New Task (from scratch)

**Click:** `Create Task...` (NOT "Create Basic Task")

### General Tab:
```
Name: Stock Forecast Daily Run
Description: Automated daily stock forecasting for PLTR after US market close

☑ Run whether user is logged on or not
☑ Run with highest privileges
Configure for: Windows 10
```

**IMPORTANT:** Make sure BOTH boxes are checked!

### Triggers Tab:

**Click New:**
```
Begin the task: On a schedule
Daily
Start: [Today's date]
Start time: 23:05:00
Recur every: 1 days

☑ Enabled
☑ Stop task if it runs longer than: 1 hour
```

**Click OK**

### Actions Tab:

**Click New:**
```
Action: Start a program

Program/script:
C:\Users\User\Desktop\marinaTradingProjects\stock-forecasting-system\scripts\run_daily.bat

Start in (optional):
C:\Users\User\Desktop\marinaTradingProjects\stock-forecasting-system
```

**Click OK**

### Conditions Tab:

```
☐ Start the task only if the computer is on AC power (UNCHECK!)
☑ Wake the computer to run this task
```

### Settings Tab:

```
☑ Allow task to be run on demand
☑ Run task as soon as possible after a scheduled start is missed
☑ If the task fails, restart every: 15 minutes
    Attempt to restart up to: 3 times
☑ Stop the task if it runs longer than: 1 hour
```

**If the running task does not end:**
```
Stop the existing instance
```

### Step 3: Save with Highest Privileges

**Click OK**

**Enter your Windows password when prompted**

**CRITICAL:** The password prompt is what actually saves the "highest privileges" setting!

If you don't get a password prompt, the setting won't stick.

---

## Solution 3: PowerShell Method

If both methods fail, try this PowerShell script:

### Run PowerShell as Administrator:

**Right-click PowerShell → Run as administrator**

**Run these commands:**

```powershell
# Delete old task
Unregister-ScheduledTask -TaskName "Stock Forecast Daily Run" -Confirm:$false -ErrorAction SilentlyContinue

# Create new task with highest privileges
$action = New-ScheduledTaskAction -Execute "C:\Users\User\Desktop\marinaTradingProjects\stock-forecasting-system\scripts\run_daily.bat" -WorkingDirectory "C:\Users\User\Desktop\marinaTradingProjects\stock-forecasting-system"

$trigger = New-ScheduledTaskTrigger -Daily -At 23:05

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName "Stock Forecast Daily Run" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Automated daily stock forecasting for PLTR after US market close"
```

---

## Verification

After creating the task (any method):

### 1. Open Task Scheduler

```
Win + R → taskschd.msc
```

### 2. Find the task

```
Stock Forecast Daily Run
```

### 3. Right-click → Properties

### 4. Check General tab:

**You MUST see:**
```
☑ Run whether user is logged on or not
☑ Run with highest privileges
```

**BOTH boxes checked!**

If not, it will fail to run.

### 5. Test it

**Right-click → Run**

**Wait 3-4 minutes**

**Check:**
- Last Run Time = now (not 1999!)
- Last Run Result = Success (0x0) or (0x1)

---

## Why This Happens

Windows requires BOTH:
1. ✅ Administrator privileges to CREATE the task
2. ✅ Your Windows password to SAVE the "highest privileges" setting

If either is missing, the setting reverts to default.

---

## Common Mistakes

❌ Creating task without admin rights
❌ Not entering password when prompted
❌ Canceling password prompt
❌ Wrong password
❌ User account doesn't have admin rights

✅ Run script as administrator
✅ Enter correct Windows password
✅ Wait for confirmation

---

## Summary

**Easiest:** Run `create_task_scheduler.bat` as administrator

**If that fails:** Delete and recreate manually with password

**If that fails:** Use PowerShell method

**One of these WILL work!** 💪
