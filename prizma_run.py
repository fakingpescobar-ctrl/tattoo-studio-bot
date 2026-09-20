# PRIZMA runner: запускает скрипт проекта через embeddable Python,
# у которого sys.path жёстко задан _pth-файлом (каталог скрипта и PYTHONPATH игнорируются).
# Использование: python prizma_run.py <script.py> [args...]
import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if len(sys.argv) < 2:
    sys.exit('usage: prizma_run.py <script.py> [args...]')

target = sys.argv[1]
if not os.path.isabs(target):
    target = os.path.join(os.getcwd(), target)

sys.argv = [target] + sys.argv[2:]
# run_path возвращает dict globals (а не None) — sys.exit(dict) дал бы код 1.
# SystemExit из целевого скрипта пробрасывается сам с корректным кодом.
runpy.run_path(target, run_name='__main__')