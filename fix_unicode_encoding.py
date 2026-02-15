#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_unicode_encoding.py - Fix Unicode encoding issues in run.py

This script replaces Unicode symbols that don't work in Windows CMD
with ASCII alternatives.

Changes:
✓ → [OK]
✗ → [FAIL]
"""

import sys
from pathlib import Path


def fix_run_py():
    """Fix unicode encoding issues in run.py"""
    
    run_py = Path("run.py")
    
    if not run_py.exists():
        print("ERROR: run.py not found!")
        print("Make sure you're running this from the project directory.")
        return False
    
    print("Reading run.py...")
    content = run_py.read_text(encoding='utf-8')
    
    # Track changes
    original = content
    changes = []
    
    # Replace unicode checkmark ✓ with [OK]
    if '\u2713' in content:
        content = content.replace('\u2713', '[OK]')
        changes.append("✓ → [OK]")
    
    # Replace unicode x mark ✗ with [FAIL]
    if '\u2717' in content:
        content = content.replace('\u2717', '[FAIL]')
        changes.append("✗ → [FAIL]")
    
    # Also check for the actual symbols (in case they're in the file)
    if '✓' in content:
        content = content.replace('✓', '[OK]')
        if "✓ → [OK]" not in changes:
            changes.append("✓ → [OK]")
    
    if '✗' in content:
        content = content.replace('✗', '[FAIL]')
        if "✗ → [FAIL]" not in changes:
            changes.append("✗ → [FAIL]")
    
    if content == original:
        print("\nNo changes needed - file already fixed!")
        return True
    
    # Backup original
    backup = run_py.with_suffix('.py.backup')
    print(f"\nCreating backup: {backup}")
    backup.write_text(original, encoding='utf-8')
    
    # Write fixed version
    print("Writing fixed version...")
    run_py.write_text(content, encoding='utf-8')
    
    print("\nChanges made:")
    for change in changes:
        print(f"  - {change}")
    
    print("\n✅ SUCCESS!")
    print("\nThe original file has been backed up to:")
    print(f"  {backup}")
    print("\nYou can now run the system without encoding errors!")
    
    return True


if __name__ == "__main__":
    print("="*60)
    print("Fix Unicode Encoding in run.py")
    print("="*60)
    print()
    
    success = fix_run_py()
    
    sys.exit(0 if success else 1)
