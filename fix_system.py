# fix_system.py - תיקון אוטומטי של המערכת
import os

print("🔧 מתקן את המערכת...")

# תיקון 1: datasources/base.py
base_py_path = "datasources/base.py"
print(f"\n1️⃣ מתקן את {base_py_path}...")

with open(base_py_path, 'r', encoding='utf-8') as f:
    content = f.read()

# בדוק אם כבר יש import os
if 'import os' not in content:
    # הוסף import os אחרי ה-docstring
    lines = content.split('\n')
    new_lines = []
    added = False
    
    for i, line in enumerate(lines):
        new_lines.append(line)
        # אחרי ה-docstring, הוסף import os
        if '"""' in line and i > 0 and not added:
            new_lines.append('import os')
            added = True
    
    content = '\n'.join(new_lines)
    
    with open(base_py_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ התיקון הצליח!")
else:
    print("✅ הקובץ כבר מתוקן!")

# תיקון 2: agents/memory_learning_agent.py
memory_py_path = "agents/memory_learning_agent.py"
print(f"\n2️⃣ מתקן את {memory_py_path}...")

with open(memory_py_path, 'r', encoding='utf-8') as f:
    content = f.read()

# הסר import os מהסוף אם קיים
lines = content.split('\n')
# מוחק שורות ריקות ו-import os בסוף
while lines and (lines[-1].strip() == '' or lines[-1].strip() == 'import os'):
    lines.pop()

# וודא שיש import os בראש הקובץ
if 'import os' not in '\n'.join(lines[:10]):
    # הוסף import os אחרי ה-docstring
    new_lines = []
    added = False
    
    for i, line in enumerate(lines):
        new_lines.append(line)
        if '"""' in line and i > 0 and not added:
            new_lines.append('import os')
            added = True
    
    content = '\n'.join(new_lines)
else:
    content = '\n'.join(lines)

with open(memory_py_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ התיקון הצליח!")

print("\n" + "="*60)
print("✅ כל התיקונים הושלמו בהצלחה!")
print("="*60)
print("\nעכשיו הריצי:")
print("python run.py --ticker PLTR")