"""付费前只读检查：不联网、不读取 Key 值、不改批次。"""
import os
import sys
from decimal import Decimal
from zipfile import BadZipFile

import openpyxl

from .common import Problem, read_csv, read_json
from .content import resolve_content, scene_errors
from .headers import dropdown, resolve_columns
from .workspace import AUTO_DEFAULTS, template_path


def key_is_set():
    if 'ARK_API_KEY' in os.environ:
        return True  # 只查变量名；不取值，也不把值交给诊断。
    if sys.platform != 'win32': return False
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    handle = wintypes.HKEY()
    size = wintypes.DWORD()
    api.RegOpenKeyExW.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.HKEY)]
    api.RegQueryValueExW.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    api.RegCloseKey.argtypes = [wintypes.HKEY]
    if api.RegOpenKeyExW(wintypes.HKEY(0x80000001), 'Environment', 0, 0x20019, ctypes.byref(handle)):
        return False
    try:
        # NULL 数据缓冲区：只查询存在性/长度，绝不取回密钥内容。
        return api.RegQueryValueExW(handle, 'ARK_API_KEY', None, None, None, ctypes.byref(size)) == 0 and size.value > 2
    finally: api.RegCloseKey(handle)


def run(ws, batch, shop, key_check=None):
    from .image_host import validate_host
    from .seedream import spending
    account, groups = [], {}
    rows = read_csv(batch / 'candidates.csv')
    if not rows: account.append('批次没有候选商品；请先 build。')
    for row in rows: groups.setdefault(row['group'], [])
    contents, errors = resolve_content(read_json(batch / 'content.json'), groups)
    for group in groups:
        if group not in contents: groups[group].append(f'{group} 缺 content.json 文案对象；请补齐。')
        else: groups[group].extend(scene_errors(group, contents[group]))
    try: validate_host(shop.get('image_host'))
    except Problem as exc: account.extend(exc.errors)
    present = (key_check or key_is_set)()
    if not present: account.append('ARK_API_KEY 没设置；请在 Windows 用户环境变量中设置后重开终端。预检不读取密钥值。')
    template = template_path(ws, shop, False)
    lists = None
    if not template.is_file(): account.append(f'找不到模板 {template}；请放入后台下载的官方模板。')
    else:
        try:
            wb = openpyxl.load_workbook(template, keep_vba=True)
            try:
                columns = resolve_columns(wb)
                lists = {k: dropdown(wb, k, columns) for k in ('manufacturer', 'eu', 'category')}
            finally: wb.close()
        except (ValueError, OSError, KeyError, BadZipFile) as exc:
            account.extend(exc.errors if isinstance(exc, Problem) else ['模板无法读取；请重新下载完整的官方模板。'])
    for row in rows:
        group, sid = row['group'], row['shop']
        maker = shop.get('suppliers', {}).get(sid)
        if not maker:
            groups[group].append(f'商家 {sid} 未配置；请补 shop.json.suppliers 并登记制造商/欧盟负责人。')
        elif lists:
            for key, field in (('fabricante', 'manufacturer'), ('responsable', 'eu')):
                if maker.get(key) not in lists[field]:
                    groups[group].append(f'商家 {sid} 的 {key} 不在模板下拉；请登记审核后下载新模板。')
        if lists and group in contents and contents[group].get('category') not in lists['category']:
            groups[group].append(f'{group} 类目不在模板下拉；请用 categories 核对原文。')
    config = shop.get('auto', AUTO_DEFAULTS)
    log = read_json(batch / 'seedream_log.json') if (batch / 'seedream_log.json').exists() else {}
    spent, group_spent = spending(log)
    remaining = Decimal(str(config['budget_units_per_batch'])) - spent
    balances = {g: float(Decimal(str(config['budget_units_per_group'])) - group_spent.get(g, Decimal(0))) for g in groups}
    if remaining < Decimal('1.36'): account.append('本批预算余额不足一张图；请核对预算和已扣费记录。')
    for g, amount in balances.items():
        if amount < 1.36: groups[g].append(f'{g} 预算余额不足一张图，跳过该组。')
    groups = {g: list(dict.fromkeys(v)) for g, v in groups.items()}
    account = list(dict.fromkeys(account))
    return dict(account_blockers=account, group_blockers=groups, key_present=present,
                budget_remaining=float(remaining), group_remaining=balances, spent_units=float(spent),
                ready_groups=[g for g, v in groups.items() if not v and not account],
                errors=account + [f'{g}：{e}' for g, values in groups.items() for e in values],
                message='只读预检完成：账户级问题停止付费；组级问题只跳过该组。预算为本地配置余额，未查询服务商账户。')
