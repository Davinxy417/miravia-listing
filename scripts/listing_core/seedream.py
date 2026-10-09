"""从旧 seedream.py 搬入的 BytePlus 接口；密钥永不进入文件或诊断。"""
import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request
from decimal import Decimal

from PIL import Image

from .common import Problem, atomic_bytes, guard_images, inside, read_json, require, write_json
from .image_workflow import make_plan, plan_mode, read_path, select

ENDPOINT = 'https://ark.ap-southeast.bytepluses.com/api/v3/images/generations'
MODEL = 'dola-seedream-5-0-pro-260628'
GEN_SIZE = '1440x1440'


def api_key():
    key = os.environ.get('ARK_API_KEY', '').strip()
    if not key and sys.platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as handle:
                value = winreg.QueryValueEx(handle, 'ARK_API_KEY')[0]
                key = value.strip() if isinstance(value, str) else ''
        except OSError: pass
    require(key, 'ARK_API_KEY 没设置；请在 Windows 用户环境变量中新增 ARK_API_KEY，填入 BytePlus API Key，再打开新终端。不要把密钥发到对话或写入仓库。')
    return key


def data_uri(path):
    with Image.open(path) as source:
        im = source.convert('RGB')
        im.thumbnail((1600, 1600))
        stream = io.BytesIO(); im.save(stream, 'JPEG', quality=90)
    return 'data:image/jpeg;base64,' + base64.b64encode(stream.getvalue()).decode()


def generate(prompt, images, key):
    body = dict(model=MODEL, prompt=prompt, size=GEN_SIZE, response_format='b64_json',
                output_format='jpeg', watermark=False, stream=False,
                sequential_image_generation='disabled')
    uris = [data_uri(p) for p in images]
    if uris: body['image'] = uris[0] if len(uris) == 1 else uris
    request = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(),
              headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})
    try:
        with urllib.request.urlopen(request, timeout=300) as response: data = json.load(response)
        item = data['data'][0]
        require('b64_json' in item, 'Seedream 未返回图片；请检查 BytePlus 控制台的调用记录，不要重复扣费。')
        raw = base64.b64decode(item['b64_json'], validate=True)
        with Image.open(io.BytesIO(raw)) as im: im.verify()
        return raw
    except urllib.error.HTTPError as exc:
        # Do not print provider bodies: some services echo request headers/prompt.
        raise Problem(f'Seedream HTTP {exc.code}；请检查 BytePlus 控制台的套餐、权限和额度。未自动重试。') from None
    except (urllib.error.URLError, TimeoutError):
        raise Problem('Seedream 网络失败或超时；先核对控制台是否已扣费，再决定重试。') from None
    except Problem: raise
    except Exception:
        raise Problem('Seedream 返回格式不正确或图片损坏；请查看控制台调用记录。') from None


def run(batch, only=None, all_missing=False, yes=False, client=None, key_reader=None):
    path = batch / 'image_plan.json'
    require(path.is_file(), '缺 image_plan.json；请先运行 images-plan。')
    saved = read_json(path)
    current = make_plan(batch, plan_mode(batch))
    # Refuse paid execution of stale/editable plan instructions.
    expected = {j['id']: j for j in current['jobs']}
    require(isinstance(saved.get('jobs'), list), 'image_plan.json 缺 jobs；请重新 images-plan。')
    require([j['id'] for j in saved['jobs']] == [j['id'] for j in current['jobs']],
            '商品或主推变体改变了；请重新 images-plan 再运行 seedream。')
    selected = select(saved['jobs'], only=only)
    jobs, skipped = [], []
    for old in selected:
        j = expected[old['id']]
        require(all(old.get(k) == j.get(k) for k in ('prompt', 'refs', 'method', 'output', 'raw_dir')),
                f"{j['id']} 清单已过期或被手改；请重新 images-plan。")
        if j['method'] in ('copy', 'derive') or (all_missing and j['status'] != 'missing'):
            skipped.append(j['id']); continue
        if j['raw'] and j['status'] != 'redo': skipped.append(j['id']); continue
        jobs.append(j)
    units = sum(Decimal('1.36') + max(0, len(j['refs'])-1)*Decimal('0.09') for j in jobs)
    result = dict(count=len(jobs), ids=[j['id'] for j in jobs], skipped=skipped,
                  estimated_units=float(units), size=GEN_SIZE, model=MODEL,
                  message=f'将生成 {len(jobs)} 张，预计扣 {units:.2f} 套餐单位（1440×1440；额外参考图每张 0.09）。这是旧套餐口径估算，请以账户控制台为准。')
    if not yes:
        return dict(result, needs_confirm=True, exit_code=2,
                    errors=['尚未出图；确认张数和预计单位后，原命令加 --yes 才会调用付费接口。'])
    guard_images(batch)
    if not jobs: return dict(result, needs_confirm=False, message='没有需要调用 Seedream 的图片。')
    issues = []
    log_path = batch / 'seedream_log.json'
    inside(batch, log_path)
    log = read_json(log_path) if log_path.is_file() else {}
    for j in jobs:
        if len(log.get(j['id'], [])) >= 2: issues.append(j['id'] + ' 已尝试两次；请补素材并人工处理，不再自动扣费。')
        issues += [j['id'] + '：' + b for b in j['blockers']]
        for ref in j['refs']:
            if not read_path(batch, ref).is_file(): issues.append(j['id'] + ' 缺参考图 ' + ref)
        require(len(j['refs']) <= 10, j['id'] + ' 参考图超过接口上限 10 张；请减少素材。')
    if issues: raise Problem(issues)
    key = (key_reader or api_key)()
    client = client or generate
    produced, errors = [], []
    for j in jobs:
        attempts = log.setdefault(j['id'], [])
        n = len(attempts) + 1
        attempts.append(dict(attempt=n, state='started'))
        write_json(log_path, log)  # Record before network; ambiguous timeouts never auto-retry.
        try:
            raw = client(j['prompt'], [read_path(batch, r) for r in j['refs']], key)
            with Image.open(io.BytesIO(raw)) as im:
                fmt = im.format; im.verify()
            require(fmt in ('PNG', 'JPEG'), '接口图片不是 PNG/JPG。')
            target = batch / j['raw_dir'] / f"{j['slot']}-seedream-v{n:02d}{'.png' if fmt == 'PNG' else '.jpg'}"
            inside(batch, target)
            require(not target.exists(), f'{target} 已存在；为保护原始图请先核对日志。')
            atomic_bytes(target, raw)
            attempts[-1].update(state='saved', raw=str(target.relative_to(batch)).replace('\\', '/'))
            produced.append(j['id'])
        except Exception as exc:
            attempts[-1]['state'] = 'failed'
            # Custom clients may echo sensitive material too; keep diagnostics local and safe.
            message = '；'.join(exc.errors) if isinstance(exc, Problem) else '接口或保存失败；请核对控制台调用记录。'
            errors.append(j['id'] + '：' + message.replace(key, '[密钥已隐藏]'))
        write_json(log_path, log)
        if errors: break  # A network/permission failure must not consume the whole batch.
    return dict(result, needs_confirm=False, produced=produced, errors=errors,
                message=f'原始图已保存 {len(produced)} 张；请跑 images-finish，再逐字校对并审阅。')
