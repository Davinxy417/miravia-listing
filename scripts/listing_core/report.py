"""离线早晨报告；不填表、不改台账、不联网。"""
from pathlib import Path
from .common import Problem, atomic_bytes, inside, read_csv, read_json
from .status import run as status
from .fill import run as check
from .finalize import publication_warnings
from .seedream import spending
from .content import resolve_content, seller_sku
from .image_readiness import group_issues
from .image_workflow import digest


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def run(ws, batch, shop, template):
    todos = []
    def optional(name, reader, default):
        path = batch / name
        if not path.is_file(): return default
        try: return reader(path)
        except (ValueError, OSError) as exc:
            todos.append(f'{name} 暂时无法读取：{exc}')
            return default

    try:
        state = status(ws, batch, template)
    except (ValueError, OSError) as exc:
        state = dict(steps={}, image_review=dict(reviewed=0, pending=0, redo=0))
        todos.append(f'进度暂时无法判断：{exc}')
    priced = optional('priced.csv', read_csv, [])
    candidates = optional('candidates.csv', read_csv, [])
    rows = priced or candidates
    content = optional('content.json', read_json, {})
    resolved, content_errors = resolve_content(content, [r['group'] for r in rows])
    prices = []
    for row in priced:
        sku = seller_sku(row, shop, resolved[row['group']]) if not content_errors else row['ean']
        prices.append(dict(group=row['group'], sku=sku, ean=row['ean'], price=row['price'], profit=row['profit_with_coupon']))
    full = batch / 'output/miravia_upload.xlsm'
    splits = sorted((batch / 'output').glob('miravia_upload_*.xlsm'),
                    key=lambda p: int(p.stem.rsplit('_', 1)[1]) if p.stem.rsplit('_', 1)[1].isdigit() else 0)
    splits = [p for p in splits if p.stem.rsplit('_', 1)[1].isdigit()]
    # Numbered files from an older finalize are not this run's upload files.
    outputs = [str(p) for p in splits if full.is_file() and p.stat().st_mtime_ns >= full.stat().st_mtime_ns]
    if outputs and len(outputs) != len(splits):
        todos.append('部分分表比完整表旧；请重跑 finalize --max-groups。')
        outputs = [str(p) for p in splits]
    if not outputs and full.is_file(): outputs = [str(full)]
    finalized = optional('finalize_result.json', read_json, {})
    draft_groups, draft_outputs, eligible = {}, [], None
    if (batch / 'variantes.csv').is_file():
        try: draft_groups = group_issues(batch, require_complete=True)
        except (ValueError, OSError) as exc: todos.append(str(exc))
    if finalized:
        eligible = set(finalized.get('eligible_groups', []))
        draft_outputs = finalized.get('draft_outputs', [])
        outputs = [str(inside(batch, batch / 'output' / name)) for name in finalized.get('outputs', {})]
        if any(digest(p) != finalized['outputs'][Path(p).name] for p in outputs):
            todos.append('上传表与收尾记录不一致；请重新 finalize。')
        current = {r['group'] for r in rows} - draft_groups.keys()
        if eligible != current: todos.append('可上传组发生变化；请重新 finalize 隔离失败组。')
    elif draft_groups:
        todos.append('存在失败或缺图的组；请重新 finalize，隔离草稿与上传表。')
    ready = False
    if not outputs:
        todos.append('上传表没做到这一步；请先 finalize。')
    elif not state['steps'].get('output', {}).get('fresh'):
        todos.append('定价需要更新；请先 price，再 finalize。' if not state['steps'].get('pricing', {}).get('fresh')
                     else '上传表需要更新；请重跑 finalize。')
    else:
        try:
            checked = check(template, batch, shop, check=True, groups=eligible)
            todos.extend(checked['warnings'])
            todos.extend(publication_warnings(batch, shop, eligible))
            ready = checked['upload_ready'] and not todos
        except (ValueError, OSError) as exc:
            todos.extend(exc.errors + exc.warnings if isinstance(exc, Problem) else [str(exc)])
    log = optional('seedream_log.json', read_json, {})
    try: spent, groups = spending(log)
    except ValueError as exc:
        spent, groups = 0, {}
        todos.append(str(exc))
    over_budget = log.get('over_budget', [])
    reviews = optional('image_review.json', read_json, {}).get('reviews', {})
    problems = [dict(id=jid, note=record.get('note', '')) for jid, record in reviews.items() if record.get('result') == 'redo']
    for jid, attempts in log.items():
        if jid != 'over_budget' and attempts and attempts[-1].get('state') in ('failed', 'started'):
            problems.append(dict(id=jid, note='出图失败，请核对控制台。' if attempts[-1]['state'] == 'failed' else '调用结果未确认，请先核对是否扣费。'))
    notes = optional('notes.md', lambda p: p.read_text('utf-8-sig'), None)
    ready = ready and not todos
    review = state['image_review']
    lines = ['# 早上看这里', '', '可以上传。' if ready else '还不能上传，请先处理下面的待办。', '', '## 上传表', '']
    lines += [f'共 {len(outputs)} 份，只上传下面列出的表。', *[f'- {p}' for p in outputs]] if outputs else ['没做到这一步。']
    if draft_groups:
        lines += ['', '## 仅草稿的组（不能上传）', '']
        lines += [f'- {g}：' + '；'.join(reasons) for g, reasons in draft_groups.items()]
        lines += [f'- 草稿：{p}' for p in draft_outputs]
    lines += ['', f'链接 {len({r["group"] for r in rows})} 个，SKU {len(rows)} 个。', '', '## 售价和每单利润', '']
    if prices:
        lines += ['| 链接 | SKU | 售价（€） | 每单利润（€） |', '|---|---|---:|---:|']
        lines += ['| ' + ' | '.join(cell(r[k]) for k in ('group', 'sku', 'price', 'profit')) + ' |' for r in prices]
        lines += ['', '利润已预留优惠券扣款。']
    else: lines += ['没做到这一步。']
    lines += ['', '## Seedream', '']
    if (batch / 'seedream_log.json').is_file():
        lines += [f'本批累计 {spent:.2f} 套餐单位（失败和结果未确认的请求也计入）。']
        lines += [f'- {g}：{amount:.2f} 单位' for g, amount in groups.items()]
        lines += ['超预算跳过：' + ('、'.join(over_budget) if over_budget else '没有。')]
    else: lines += ['没做到这一步。']
    lines += ['', '## 图片审阅', '']
    if review.get('error'):
        lines += ['没做到这一步；图片审阅统计暂时无法推算。', review['error']]
    else:
        if not (batch / 'image_review.json').is_file(): lines += ['审阅记录没做到这一步。']
        lines += [f'通过 {review["reviewed"]}，没审 {review["pending"]}，要重做 {review["redo"]}。']
    lines += [f'- {r["id"]}：{r["note"]}' for r in problems]
    lines += ['', '## 跳过和待办', '']
    lines += [f'- {t}' for t in dict.fromkeys(todos)] or ['没有额外待办。']
    lines += ['', '### 批次 notes.md 原文', '']
    text = '\n'.join(lines) + '\n' + (notes if notes is not None else '没做到这一步。\n')
    target = inside(batch, batch / '早上看这里.md')
    atomic_bytes(target, text.encode('utf-8'))
    return dict(upload_ready=ready, outputs=outputs, draft_groups=draft_groups, draft_outputs=draft_outputs,
                groups=len({r['group'] for r in rows}), count=len(rows),
                prices=prices, spent_units=float(spent), group_units={g: float(v) for g, v in groups.items()},
                over_budget=over_budget, image_review=review, image_problems=problems, todos=list(dict.fromkeys(todos)),
                notes=notes, output=str(target), message='早晨报告已生成。' + ('可以上传。' if ready else '还不能上传，请查看报告里的待办。'))
