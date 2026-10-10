"""工作区查找、初始化和完整店铺配置校验。"""
import ctypes
import math
import os
import uuid
from pathlib import Path

from .common import REPO, CSV_FIELDS, Problem, component, inside, read_json, require, write_csv, write_json

AUTO_DEFAULTS = dict(enabled=True, budget_units_per_group=15, budget_units_per_batch=150, max_groups_per_file=10)


def documents_folder():
    if os.name != 'nt':
        return Path.home() / 'Documents'
    from ctypes import wintypes
    class GUID(ctypes.Structure):
        _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]
    guid = GUID.from_buffer_copy(uuid.UUID('FDD39AD0-238F-46AF-ADB4-6C85480369C7').bytes_le)
    pointer = ctypes.c_wchar_p()
    shell = ctypes.windll.shell32
    shell.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
    result = shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer))
    require(result == 0, '无法取得 Windows 文档文件夹；请用 --ws 指定工作区。')
    try:
        return Path(pointer.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(pointer)


def resolve_workspace(explicit=None):
    value = explicit or os.environ.get('MIRAVIA_WS')
    if not value:
        locator = Path.home() / '.miravia-listing.json'
        if locator.exists():
            settings = read_json(locator)
            require(isinstance(settings, dict) and isinstance(settings.get('workspace'), str) and settings['workspace'].strip(),
                    f'{locator} 缺少有效 workspace 路径；请填写或用 --ws 指定。')
            value = settings['workspace']
    return Path(value).expanduser().resolve() if value else (documents_folder() / 'Miravia工作区').resolve()


def init(ws):
    ws = Path(ws)
    for name in ('template', 'batches'):
        inside(ws, ws / name).mkdir(parents=True, exist_ok=True)
    target = inside(ws, ws / 'shop.json')
    if not target.exists():
        # Exclusive creation: even another init cannot overwrite a shop config.
        try:
            with target.open('xb') as f:
                f.write((REPO / 'config/shop.example.json').read_bytes())
        except FileExistsError:
            pass
    return ws


def batch_path(ws, name, must_exist=True):
    require(bool(name), '缺少批次名；请加 --batch 批次名。')
    path = inside(ws, Path(ws) / 'batches' / component(name, '批次名'))
    require(not must_exist or path.is_dir(), f'批次 {name} 不存在；请先运行 new-batch {name}。')
    return path


def new_batch(ws, name):
    init(ws)
    batch = batch_path(ws, name, False)
    require(not batch.exists(), f'批次 {name} 已存在；请换一个名字，已有数据不会覆盖。')
    batch.mkdir(parents=True)
    for name in ('images', 'output'):
        (batch / name).mkdir()
    (batch / 'barcodes.txt').touch()
    for name, fields in CSV_FIELDS.items():
        write_csv(batch / name, [], fields)
    for name in ('content.json', 'overlays.json'):
        write_json(batch / name, {})
    return batch


def load_shop(ws):
    path = Path(ws) / 'shop.json'
    require(path.is_file(), f'{path} 不存在；请先运行 init，再填写店铺配置。')
    shop = read_json(path)
    if isinstance(shop, dict) and 'auto' not in shop:
        shop['auto'] = dict(AUTO_DEFAULTS)
    # The example describes required structure, never supplies fallback values.
    schema = read_json(REPO / 'config/shop.example.json')
    errors = []
    def structure(value, sample, prefix):
        if not isinstance(value, dict):
            errors.append(f'{prefix} 应是 JSON 对象')
            return
        for key, expected in sample.items():
            where = f'{prefix}.{key}'
            # A2 optional supplier field: existing A1 shop.json stays valid.
            if key == 'price_includes_iva' and key not in value:
                continue
            if key not in value:
                errors.append(f'缺少 {where}')
            elif key == 'suppliers':
                if not isinstance(value[key], dict):
                    errors.append(f'{where} 应按商家 id 填写对象')
                else:
                    model = next(iter(expected.values()))
                    for supplier, entry in value[key].items():
                        structure(entry, model, f'{where}.{supplier}')
            elif isinstance(expected, dict):
                structure(value[key], expected, where)
            elif expected is None:
                if value[key] is not None and not isinstance(value[key], dict):
                    errors.append(f'{where} 应是 null 或图床配置对象')
            elif isinstance(expected, bool):
                if not isinstance(value[key], bool): errors.append(f'{where} 应是 true/false')
            elif isinstance(expected, (int, float)):
                if type(value[key]) not in (int, float) or not math.isfinite(value[key]):
                    errors.append(f'{where} 应是有限数值')
            elif not isinstance(value[key], type(expected)) or (isinstance(expected, str) and not value[key].strip()):
                errors.append(f'{where} 类型不对或为空')
    structure(shop, schema, 'shop.json')
    if isinstance(shop, dict) and isinstance(shop.get('suppliers'), dict):
        for sid, supplier in shop['suppliers'].items():
            if isinstance(supplier, dict) and 'price_includes_iva' in supplier and not isinstance(supplier['price_includes_iva'], bool):
                errors.append(f'shop.json.suppliers.{sid}.price_includes_iva 应是 true/false')
    if errors:
        raise Problem([f'{e}；请参照 references/店铺配置.md 补齐。' for e in errors])
    p = shop['pricing']
    for key in ('budget_units_per_group', 'budget_units_per_batch', 'max_groups_per_file'):
        if shop['auto'][key] <= 0: errors.append(f'auto.{key} 必须大于 0')
    if type(shop['auto']['max_groups_per_file']) is not int:
        errors.append('auto.max_groups_per_file 必须是正整数')
    for key in ('cost_factor', 'spread_warn', 'original_markup', 'volumetric_divisor'):
        if p[key] <= 0: errors.append(f'pricing.{key} 必须大于 0')
    for key in ('packaging', 'min_profit', 'profit_rate'):
        if p[key] < 0: errors.append(f'pricing.{key} 不能小于 0')
    fees = list(p['fees'].values()) + [p['coupon_rate']]
    if any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 or x >= 1 for x in fees) or sum(fees) >= 1:
        errors.append('pricing.fees 与 coupon_rate 均需在 0 到 1 之间，合计小于 1')
    tiers = p['ship_tiers']
    if not tiers or any(not isinstance(t, list) or len(t) != 2 or any(type(n) not in (int, float) or not math.isfinite(n) for n in t) or t[0] <= 0 or t[1] < 0 for t in tiers):
        errors.append('pricing.ship_tiers 应为非空的 [[重量上限kg, 运费欧元], ...]')
    elif any(a[0] >= b[0] for a, b in zip(tiers, tiers[1:])):
        errors.append('pricing.ship_tiers 重量上限必须由小到大')
    if type(shop['stock_default']) is not int or not 0 <= shop['stock_default'] <= 999999999999999:
        errors.append('stock_default 应是 0 到 999999999999999 之间的整数')
    if not isinstance(shop['sku']['prefix'], str) or not shop['sku']['prefix'].isalnum():
        errors.append('sku.prefix 只能包含字母和数字')
    if errors: raise Problem([f'shop.json：{e}；请修改后重试。' for e in errors])
    if shop.get('image_host') is not None:
        from .image_host import validate_host
        validate_host(shop['image_host'])
    template_path(ws, shop, must_exist=False)
    return shop


def template_path(ws, shop, must_exist=True):
    directory = Path(ws) / 'template'
    path = inside(directory, directory / shop['template'])
    require(path.suffix.lower() == '.xlsm', 'shop.json.template 必须指向 template/ 下的官方 .xlsm 文件。')
    require(not must_exist or path.is_file(), f'找不到模板 {path}；请放入后台下载的模板，并修改 shop.json.template。')
    return path
