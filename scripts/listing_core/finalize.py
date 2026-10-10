"""收尾、按链接家族分表、可重复更新的上架台账。"""
from datetime import date
from pathlib import Path

from .common import Problem, inside, read_csv, read_json, require, write_csv, write_json
from .collect_images import collect
from .content import resolve_content, seller_sku
from .fill import prepare, run as fill, write_upload
from .images import read_variantes, variant_key
from .make_images_csv import make_images_csv
from .image_host import selection
from .image_workflow import digest
from .image_readiness import group_issues

LEDGER_FIELDS = ['日期', '批次', '组', '变体', 'EAN', '卖家 SKU', '批发商 id', '友购货号', '进价', '实际成本', '售价', '每单利润']


def publication_warnings(batch, shop, groups=None):
    path = batch / 'image_publish.json'
    if not path.exists():
        return []
    report = read_json(path)
    require(isinstance(report, dict) and report.get('version') == 1 and isinstance(report.get('files'), list)
            and isinstance(report.get('host'), dict) and isinstance(report.get('checks'), list),
            'image_publish.json 格式不正确；请重新 publish-images。')
    warnings = []
    if report['host'] != shop.get('image_host'):
        warnings.append('图床配置与发布记录不同；请重新 publish-images，更新网址。')
    if not report['checks'] or any(not c.get('ok') for c in report['checks']):
        warnings.append('上次图片直链抽查未通过；请检查图床和网络后重新 publish-images。')
    # Read the current bytes, including unreviewed items, without modifying images.
    current, _ = selection(batch, include_unreviewed=True)
    current = {i['id']: i for i in current}
    urls = {(r['group'], r['variante'], r['slot']): r['url'] for r in read_csv(batch / 'images.csv')}
    for item in report['files']:
        if groups is not None and item['group'] not in groups: continue
        jid = item['id']
        row = current.get(jid)
        if row is None or row['sha256'] != item['sha256']:
            warnings.append(f'{jid} 成品已变化或缺失；请重新审阅并 publish-images。')
        key = item['group'], item['variante'], item['slot']
        expected = report['host']['base_url'].rstrip('/') + '/' + item['path']
        if urls.get(key) != expected:
            warnings.append(f'{jid} 图片网址与发布记录不同；请重新 publish-images。')
    return warnings


def update_ledger(ws, batch, shop, groups=None):
    target = inside(ws, Path(ws) / '台账.csv')
    previous = read_csv(target, LEDGER_FIELDS) if target.exists() else []
    rows = read_csv(batch / 'priced.csv')
    mappings = read_variantes(batch / 'variantes.csv')
    content, errors = resolve_content(read_json(batch / 'content.json'), [r['group'] for r in rows])
    if errors:
        raise Problem(errors)
    # Keep original date for matching entries; refresh every other business field.
    dates = {(r['批次'], r['EAN']): r['日期'] for r in previous}
    updated = []
    for row in rows:
        if groups is not None and row['group'] not in groups: continue
        key = batch.name, row['ean']
        updated.append(dict(zip(LEDGER_FIELDS, [dates.get(key, date.today().isoformat()), batch.name,
            row['group'], mappings[variant_key(row)], row['ean'], seller_sku(row, shop, content[row['group']]),
            row['shop'], row['art_id'], row['unit_cost_ex_iva'], row['real_cost'], row['price'], row['profit_with_coupon']])))
    # Replace this batch as a whole, also removing SKUs no longer present on rerun.
    write_csv(target, [r for r in previous if r['批次'] != batch.name] + updated, LEDGER_FIELDS)
    return str(target)


def split_uploads(template, batch, shop, limit, groups=None):
    values, _, columns, width = prepare(template, batch, shop, groups)
    families = {}
    for row in values:
        group = row[columns['group'] - 1]
        family = group[:-1] if group.endswith('B') else group
        families.setdefault(family, []).append(row)
    oversized = [key for key, rows in families.items() if len({r[columns['group'] - 1] for r in rows}) > limit]
    require(not oversized, f'--max-groups {limit} 装不下同一主组和 B 组（{"、".join(oversized)}）；请把上限至少设为 2，主组和 B 组不能拆开。')
    chunks, pending, count = [], [], 0
    for rows in families.values():
        size = len({r[columns['group'] - 1] for r in rows})
        if count + size > limit:
            chunks.append(pending)
            pending, count = [], 0
        pending.extend(rows)
        count += size
    if pending:
        chunks.append(pending)
    targets = [inside(batch, batch / f'output/miravia_upload_{i}.xlsm') for i in range(1, len(chunks) + 1)]
    # Validate old outputs' paths before writing or cleaning up stale split files.
    stale = [inside(batch, p) for p in (batch / 'output').glob('miravia_upload_*.xlsm')
             if p.name.removeprefix('miravia_upload_').removesuffix('.xlsm').isdigit() and p not in targets]
    for target, rows in zip(targets, chunks):
        write_upload(template, target, rows, columns, width)
    for target in stale:
        target.unlink()
    return [str(p) for p in targets]


def finalize(ws, batch, shop, template, max_groups=None, base_url=None):
    require(max_groups is None or (type(max_groups) is int and max_groups > 0), '--max-groups 必须是正整数。')
    for name in ('image_files.csv', 'images.csv', 'output'):
        inside(batch, batch / name)
    inside(ws, Path(ws) / '台账.csv')
    warnings = []
    # Read-only collection: finalization never creates/replaces a reviewed image.
    collect(batch / 'images', batch / 'image_files.csv', batch / 'variantes.csv', readonly=True, warnings=warnings)
    if base_url:
        require(not (batch / 'image_publish.json').exists(),
                '本批次已有 publish-images 记录；请直接使用已发布网址，不要用 --base-url 覆盖。')
        make_images_csv(base_url, batch / 'image_files.csv', batch / 'images.csv', batch / 'variantes.csv', batch / 'images')
    # No automatic base_url concatenation for GitHub: its path differs from local paths.
    # Missing/empty URLs are permitted as a draft and are diagnosed by fill/check.
    failures = group_issues(batch, require_complete=True)
    all_groups = {r['group'] for r in read_csv(batch / 'priced.csv')}
    eligible = all_groups - failures.keys()
    drafts = []
    if failures:
        values, draft_warnings, columns, width = prepare(template, batch, shop, set(failures))
        draft = inside(batch, batch / 'output/miravia_draft.xlsm')
        write_upload(template, draft, values, columns, width)
        drafts.append(str(draft))
    else:
        draft_warnings = []
    # Collection warnings from failed groups belong to the draft, not the
    # independent upload file. Required slots for eligible groups were checked.
    warnings = [w for w in warnings if not any(w.startswith(g + '/') for g in failures)]
    result = fill(template, batch, shop, groups=eligible)
    checked = fill(template, batch, shop, check=True, groups=eligible)
    warnings.extend(result['warnings'])
    warnings.extend(checked['warnings'])
    warnings.extend(publication_warnings(batch, shop, eligible))
    warnings = list(dict.fromkeys(warnings))
    result['warnings'] = warnings
    result['upload_ready'] = bool(eligible) and not warnings and checked['upload_ready']
    outputs = split_uploads(template, batch, shop, max_groups, eligible) if max_groups else ([result['output']] if eligible else [])
    if not max_groups:
        for path in (batch / 'output').glob('miravia_upload_*.xlsm'):
            if path.stem.removeprefix('miravia_upload_').isdigit(): inside(batch, path).unlink()
    if not eligible:
        inside(batch, Path(result['output'])).unlink(missing_ok=True)
        result['output'] = drafts[0] if drafts else ''
    if not failures:
        inside(batch, batch / 'output/miravia_draft.xlsm').unlink(missing_ok=True)
    result['outputs'] = outputs
    result['missing'] = warnings
    result.update(draft_outputs=drafts, draft_groups=failures, draft_warnings=draft_warnings,
                  eligible_groups=sorted(eligible))
    if result['upload_ready']:
        result['ledger'] = update_ledger(ws, batch, shop, eligible)
    paths = '\n'.join(outputs)
    result['message'] = ('可以上传；已更新上架台账。上传表：\n' if result['upload_ready'] else '已生成草稿表，还不能上传；请处理下面提醒后重跑 finalize。表在：\n') + paths
    if max_groups and outputs:
        result['message'] += '\n请按列出的分批表上传；output/miravia_upload.xlsm 是完整备份。'
    if failures:
        result['message'] += '\n以下组只出草稿，未放入上传表：' + '、'.join(sorted(failures)) + '\n草稿：' + '\n'.join(drafts)
    if not eligible:
        result['message'] = 'finalize 已完成，但全部组只出草稿，不能上传。草稿：\n' + '\n'.join(drafts)
        result['message'] += '\n请修复以下图片并重新审阅，然后再次 finalize：\n' + '\n'.join(
            reason for reasons in failures.values() for reason in reasons)
    write_json(inside(batch, batch / 'finalize_result.json'), dict(
        version=1, eligible_groups=sorted(eligible), draft_groups=failures, draft_outputs=drafts,
        outputs={Path(p).name: digest(p) for p in outputs}, upload_ready=result['upload_ready']))
    return result
