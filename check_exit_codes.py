"""
Verify and fix exit codes in run.py

This script checks if run.py properly returns:
- sys.exit(0) on success
- sys.exit(1) on failure

Usage:
    python check_exit_codes.py
"""

import sys
import os
import re

def check_run_py():
    """Check if run.py has proper exit codes"""
    
    if not os.path.exists('run.py'):
        print("[ERROR] run.py not found in current directory")
        print("Please run this from the project root:")
        print("  cd C:\\Users\\User\\Desktop\\marinaTradingProjects\\stock-forecasting-system")
        return False
    
    with open('run.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    print("=" * 60)
    print("Checking run.py Exit Codes")
    print("=" * 60)
    print()
    
    issues = []
    
    # Check for sys.exit calls
    has_exit_0 = 'sys.exit(0)' in content or 'exit(0)' in content
    has_exit_1 = 'sys.exit(1)' in content or 'exit(1)' in content
    
    print(f"✓ Found sys.exit(0): {has_exit_0}")
    print(f"✓ Found sys.exit(1): {has_exit_1}")
    print()
    
    if not has_exit_0:
        issues.append("Missing sys.exit(0) for success case")
    
    if not has_exit_1:
        issues.append("Missing sys.exit(1) for failure case")
    
    # Check for implicit returns (bad!)
    if 'if __name__ == "__main__":' in content:
        main_block = content.split('if __name__ == "__main__":')[1]
        
        # Check if main() is called without exit handling
        if 'main()' in main_block and 'sys.exit' not in main_block:
            issues.append("main() called but no sys.exit() found")
            print("⚠ WARNING: main() called without explicit exit code")
            print()
    
    # Check for exception handling
    if 'try:' not in content or 'except' not in content:
        issues.append("No exception handling in __main__ block")
        print("⚠ WARNING: No try/except in main block")
        print()
    
    if issues:
        print("=" * 60)
        print("ISSUES FOUND:")
        print("=" * 60)
        for i, issue in enumerate(issues, 1):
            print(f"{i}. {issue}")
        print()
        print("run.py needs to be fixed!")
        print()
        return False
    else:
        print("=" * 60)
        print("✓ All checks passed!")
        print("=" * 60)
        print()
        print("run.py appears to have proper exit code handling.")
        print()
        return True

def show_recommended_pattern():
    """Show the recommended pattern for main block"""
    
    print("=" * 60)
    print("RECOMMENDED PATTERN:")
    print("=" * 60)
    print()
    print('''
if __name__ == "__main__":
    import sys
    
    try:
        # Run the main function
        success = main()
        
        if success:
            print("\\n[OK] All agents completed successfully\\n")
            sys.exit(0)  # EXIT CODE 0 = SUCCESS
        else:
            print("\\n[FAIL] Some agents failed\\n")
            sys.exit(1)  # EXIT CODE 1 = FAILURE
            
    except KeyboardInterrupt:
        print("\\n[INTERRUPTED] User cancelled execution")
        sys.exit(1)
        
    except Exception as e:
        print(f"\\n[ERROR] Unhandled exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)  # EXIT CODE 1 = ERROR
''')
    print()
    print("=" * 60)
    print()

def main():
    """Main function"""
    
    print()
    print("=" * 60)
    print("Exit Code Checker for run.py")
    print("=" * 60)
    print()
    
    # Check current directory
    cwd = os.getcwd()
    print(f"Current directory: {cwd}")
    print()
    
    # Check run.py
    result = check_run_py()
    
    if not result:
        print()
        show_recommended_pattern()
        print("Please update run.py with proper exit code handling.")
        print()
        return False
    
    print()
    print("Next steps:")
    print("1. Test: python run.py --ticker PLTR")
    print("2. Check: echo %ERRORLEVEL%")
    print("3. Should see: 0 (if successful)")
    print()
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
