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
from .preflight import run as preflight

ENDPOINT = 'https://ark.ap-southeast.bytepluses.com/api/v3/images/generations'
MODEL = 'dola-seedream-5-0-pro-260628'
GEN_SIZE = '1440x1440'


def job_units(job):
    return Decimal('1.36') + max(0, len(job['refs']) - 1) * Decimal('0.09')


def spending(log):
    """Count every attempt, including failures and uncertain started requests."""
    require(isinstance(log, dict), 'seedream_log.json 应是对象；请核对调用记录。')
    groups = {}
    for jid, attempts in log.items():
        if jid == 'over_budget': continue
        require(isinstance(attempts, list), f'{jid} 调用记录应是数组；请核对 seedream_log.json。')
        group = jid.split('/')[0]
        for attempt in attempts:
            require(isinstance(attempt, dict), f'{jid} 调用记录格式不对；请核对 seedream_log.json。')
            value = attempt.get('units', 1.36)
            require(type(value) in (int, float), f'{jid} units 应是正数；请核对调用记录。')
            amount = Decimal(str(value))
            require(amount.is_finite() and amount > 0, f'{jid} units 应是有限正数；请核对调用记录。')
            groups[group] = groups.get(group, Decimal(0)) + amount
    return sum(groups.values(), Decimal(0)), groups


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
                output_format='jpeg', watermark=False)  # 5.0 Pro 不接受 stream/sequential_image_generation,带了回 400
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


def run(batch, only=None, all_missing=False, yes=False, client=None, key_reader=None, auto=False, shop=None):
    from .workspace import AUTO_DEFAULTS
    require(not (auto and yes), '--auto 与 --yes 不能同时使用。')
    config = (shop or {}).get('auto', AUTO_DEFAULTS)
    require(not auto or config['enabled'], '店铺未开启全自动,请用 --yes 并先问用户')
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
    units = sum((job_units(j) for j in jobs), Decimal(0))
    log_path = batch / 'seedream_log.json'
    log = read_json(log_path) if log_path.is_file() else {}
    spent, group_spent = spending(log)
    budget = {k: config[k] for k in ('budget_units_per_group', 'budget_units_per_batch')}
    result = dict(count=len(jobs), ids=[j['id'] for j in jobs], skipped=skipped,
                  spent_units=float(spent), budget=budget, over_budget=[],
                  estimated_units=float(units), size=GEN_SIZE, model=MODEL,
                  message=f'将生成 {len(jobs)} 张，预计扣 {units:.2f} 套餐单位（1440×1440；额外参考图每张 0.09）。这是旧套餐口径估算，请以账户控制台为准。')
    if not yes and not auto:
        return dict(result, needs_confirm=True, exit_code=2,
                    errors=['尚未出图；确认张数和预计单位后，原命令加 --yes 才会调用付费接口。'])
    guard_images(batch)
    if not jobs: return dict(result, needs_confirm=False, message='没有需要调用 Seedream 的图片。')
    inside(batch, log_path)
    # Skip unaffordable work before any key access; cost admission is repeated
    # after each actual attempt, so blockers never reserve another job's budget.
    affordable = [j for j in jobs if
                  group_spent.get(j['group'], Decimal(0)) + job_units(j) <= Decimal(str(budget['budget_units_per_group']))
                  and spent + job_units(j) <= Decimal(str(budget['budget_units_per_batch']))]
    if not affordable:
        result['over_budget'] = [j['id'] for j in jobs]
        log['over_budget'] = list(dict.fromkeys(log.get('over_budget', []) + result['over_budget']))
        write_json(log_path, log)
        return dict(result, needs_confirm=False, produced=[], errors=[], message='本次图片超出预算，已跳过；没有调用 Seedream。')
    from .workspace import load_shop
    ws = batch.parent.parent
    readiness = preflight(ws, batch, shop or load_shop(ws))
    result['preflight'] = readiness
    if readiness['account_blockers']:
        return dict(result, needs_confirm=False, produced=[], errors=readiness['account_blockers'])
    admitted, blocked = [], []
    for j in jobs:
        issues = list(j['blockers']) + readiness['group_blockers'].get(j['group'], [])
        if len(log.get(j['id'], [])) >= 2: issues.append('已尝试两次；请补素材并人工处理，不再自动扣费。')
        for ref in j['refs']:
            if not read_path(batch, ref).is_file(): issues.append('缺参考图 ' + ref)
        if len(j['refs']) > 10: issues.append('参考图超过接口上限 10 张；请减少素材。')
        if issues:
            blocked.append(dict(id=j['id'], reasons=issues)); skipped.append(j['id'])
        else: admitted.append(j)
    result['blocked'] = blocked
    blocked_errors = [b['id'] + '：' + '；'.join(b['reasons']) for b in blocked]
    if not admitted: return dict(result, needs_confirm=False, produced=[], errors=blocked_errors)
    try: key = (key_reader or api_key)()
    except Problem as exc:
        return dict(result, needs_confirm=False, produced=[], errors=exc.errors)
    client = client or generate
    produced, errors = [], []
    for j in admitted:
        group, cost = j['id'].split('/')[0], job_units(j)
        if (group_spent.get(group, Decimal(0)) + cost > Decimal(str(budget['budget_units_per_group']))
                or spent + cost > Decimal(str(budget['budget_units_per_batch']))):
            result['over_budget'].append(j['id'])
            log['over_budget'] = list(dict.fromkeys(log.get('over_budget', []) + [j['id']]))
            write_json(log_path, log)
            continue
        attempts = log.setdefault(j['id'], [])
        n = len(attempts) + 1
        attempts.append(dict(attempt=n, state='started', units=float(job_units(j))))
        spent += cost
        group_spent[group] = group_spent.get(group, Decimal(0)) + cost
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
    result['spent_units'] = float(spending(log)[0])
    return dict(result, needs_confirm=False, produced=produced, errors=errors + blocked_errors,
                message=f'原始图已保存 {len(produced)} 张；请跑 images-finish，再逐字校对并审阅。')
