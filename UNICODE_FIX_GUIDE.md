# Quick Fix Guide - Unicode Encoding Error

## Problem

The system runs successfully but crashes at the end with:

```
UnicodeEncodeError: 'charmap' codec can't encode character '\u2713'
```

**This happens because:**
- `run.py` uses Unicode symbols: ✓ and ✗
- Windows CMD with Hebrew encoding (cp1255) can't display these
- The script exits with error code 1 (even though it worked!)

## Solution

Replace the Unicode symbols with ASCII alternatives:
- ✓ → `[OK]`
- ✗ → `[FAIL]`

---

## Quick Fix (Automatic)

### Option 1: Run the fix script

**Copy to project root:**
- `fix_unicode_encoding.py`
- `fix_encoding.bat`

**Then run:**
```cmd
fix_encoding.bat
```

**Or:**
```cmd
python fix_unicode_encoding.py
```

This will:
1. Backup `run.py` to `run.py.backup`
2. Replace Unicode symbols with ASCII
3. Save the fixed version

---

## Manual Fix (If you prefer)

**Open `run.py` in a text editor**

**Find and replace:**

1. Replace `\u2713` with `[OK]`
2. Replace `\u2717` with `[FAIL]`
3. Replace `✓` with `[OK]`  
4. Replace `✗` with `[FAIL]`

**Save the file**

---

## Verification

**After fixing, run:**
```cmd
python run.py --ticker PLTR
```

**You should see at the end:**
```
[OK] All agents completed successfully
Run Status: SUCCESS
```

**No error!** ✅

---

## Impact

### Before Fix:
- ❌ Exit code 1 (failure)
- ❌ Task Scheduler thinks it failed
- ✅ System actually worked fine

### After Fix:
- ✅ Exit code 0 (success)
- ✅ Task Scheduler happy
- ✅ System works fine

---

## Why This Happened

Windows uses different character encodings:
- **cmd.exe** defaults to `cp1255` (Hebrew)
- **Python print()** uses this encoding
- Unicode symbols (✓✗) aren't in cp1255
- → Error!

**The fix:** Use ASCII symbols instead (`[OK]` `[FAIL]`)

---

## Files Created

- `fix_unicode_encoding.py` - Automatic fix script
- `fix_encoding.bat` - Windows batch wrapper
- `run.py.backup` - Backup of original (after running fix)

---

## Quick Summary

**Problem:** Unicode symbols crash on Hebrew Windows
**Solution:** Replace with ASCII: ✓→[OK], ✗→[FAIL]
**How:** Run `fix_encoding.bat` or edit manually
**Result:** No more encoding errors!
