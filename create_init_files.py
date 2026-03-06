"""
Запустите этот скрипт из корня проекта (рядом с main.py).
Он создаст все недостающие __init__.py и выведет итоговую структуру.

    python create_init_files.py
"""

import os

INIT_PATHS = [
    "piano/__init__.py",
    "piano/midi/__init__.py",
    "piano/ui/__init__.py",
]

for path in INIT_PATHS:
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# auto-generated package marker\n")
        print(f"[created]  {path}")
    else:
        print(f"[exists]   {path}")

print("\nГотово. Структура пакетов:")
for root, dirs, files in os.walk("piano"):
    dirs.sort()
    level = root.count(os.sep)
    indent = "  " * level
    print(f"{indent}{os.path.basename(root)}/")
    for f in sorted(files):
        print(f"{indent}  {f}")
