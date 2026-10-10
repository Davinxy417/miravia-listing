"""一条命令跑全部离线测试:python tests/run_all.py(全部通过才打印 ALL OK)。"""
import os, subprocess, sys
from pathlib import Path

TESTS = ['smoke_test', 'regress_legacy', 'auxiliary_test', 'test_yollgo', 'test_images',
         'test_publish', 'test_auto', 'test_keywords', 'test_a6', 'test_a7']
here = Path(__file__).resolve().parent
env = dict(os.environ, PYTHONIOENCODING='utf-8')
failed = []
for name in TESTS:
    r = subprocess.run([sys.executable, str(here / f'{name}.py')], capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
    print(f"{'OK  ' if r.returncode == 0 else 'FAIL'} {name}")
    if r.returncode: failed.append(name); print((r.stdout + r.stderr)[-1500:])
print('ALL OK' if not failed else 'FAILED: ' + ', '.join(failed))
sys.exit(1 if failed else 0)
