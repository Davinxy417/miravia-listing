"""测试公共执行器；测试工作区只放仓库 .tmp/。"""
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures'
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts'))


def workspace(prefix):
    (ROOT / '.tmp').mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=ROOT / '.tmp'))


def cli(ws, *args, ok=True):
    result = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/mlist.py'), *map(str,args), '--ws', str(ws), '--json'],
                            cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                            env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    try: data = json.loads(result.stdout)
    except ValueError as exc: raise AssertionError(f'不是单个 JSON 对象：{result.stdout}\n{result.stderr}') from exc
    assert isinstance(data.get('ok'), bool) and isinstance(data.get('warnings'), list) and isinstance(data.get('errors'), list), data
    assert bool(result.returncode == 0) == data['ok'], (result.returncode, data)
    assert data['ok'] == ok, data
    assert not result.stderr, result.stderr
    return data


def csv_rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def json_write(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
