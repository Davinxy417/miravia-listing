"""每链接数据及 B 组继承，不内置任何商品组。"""
import copy
import re
from decimal import Decimal, InvalidOperation
from .common import Problem, require

INHERITED = ('category', 'gpsr_name', 'gpsr_safety', 'sku_include_ean', 'gpsr_measure_suffix',
             'image_description', 'image_scenes07', 'use_scene', 'hero_feature', 'scene_briefs', 'description_images')


def resolve_content(raw, groups):
    require(isinstance(raw, dict), 'content.json 应是以 group 为键的 JSON 对象；请按数据格式填写。')
    result, errors = {}, []
    for group in set(groups):
        base = group[:-1] if group.endswith('B') else group
        item = raw.get(group)
        if not isinstance(item, dict):
            errors.append(f'content.json 缺少 {group} 文案对象；请补齐标题、描述等字段。')
            continue
        item = copy.deepcopy(item)
        if base != group and isinstance(raw.get(base), dict):
            for key in INHERITED:
                if key not in item and key in raw[base]: item[key] = copy.deepcopy(raw[base][key])
        result[group] = item
    return result, errors


def number(raw, field, integer=False, money=False):
    try: value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise Problem(f'{field} 的数值 {raw!r} 不正确；请填写数字。') from exc
    require(value.is_finite() and value > 0, f'{field} 必须是有限正数；请核对原始资料。')
    if integer:
        require(value == value.to_integral_value(), f'{field} 必须是整数；请去掉小数。')
        return int(value)
    if money:
        require(value == value.quantize(Decimal('0.01')), f'{field} 金额最多两位小数；请重新定价。')
    return value


def seller_sku(row, shop, item):
    qty = number(row['pack_qty'], 'pack_qty', integer=True)
    colour = f"-{row['ean']}" if item.get('sku_include_ean', False) else ''
    return f"{shop['sku']['prefix']}{row['shop']}-{row['art_id']}" + colour + (f'-P{qty}' if qty > 1 else '')


def scene_errors(group, item):
    """检查出图事实；规划时作为组级 blocker，check 时作为文案错误。"""
    errors = []
    for key in ('use_scene', 'hero_feature'):
        if not isinstance(item.get(key), str) or not item[key].strip():
            errors.append(f'{group} 缺非空 {key}；请在 content.json 补齐中文出图事实。')
    briefs = item.get('scene_briefs')
    for slot in ('04', '05', '08'):
        brief = briefs.get(slot) if isinstance(briefs, dict) else None
        for key in ('location', 'action', 'connections', 'visible_result'):
            if not isinstance(brief, dict) or not isinstance(brief.get(key), str) or not brief[key].strip():
                errors.append(f'{group} 缺 scene_briefs.{slot}.{key}；请写清位置、动作、连接和可见结果，无管线时写接触关系。')
    return errors


def content_errors(group, item):
    errors = scene_errors(group, item)
    def bad(message): errors.append(f'content.json 的 {group}：{message}；请修改该组文案。')
    for key in ('title', 'description', 'attributes', 'warning', 'warning_text', 'category'):
        if not isinstance(item.get(key), str): bad(f'缺少字符串字段 {key}')
    for key, low, high in (('title', 55, 128), ('description', 400, 2200), ('attributes', 0, 200), ('warning_text', 0, 2000)):
        if isinstance(item.get(key), str) and not low <= len(item[key]) <= high:
            bad(f'{key} 长度应为 {low}～{high} 字符，当前 {len(item[key])}')
    if item.get('warning') not in ('Sí', 'No'): bad('warning 只能为 Sí 或 No')
    text = item.get('warning_text')
    if isinstance(text, str):
        if re.search(r'https?://|www\.|href\s*=', text, re.I): bad('安全提示不能带链接')
        if item.get('warning') == 'Sí' and not re.fullmatch(r'(?:\s*<li>[^<>]+</li>)+\s*', text):
            bad('安全提示须使用非空 <li>文字</li> 条目')
        if item.get('warning') == 'No' and text: bad('warning 为 No 时 warning_text 应留空')
    if 'sku_include_ean' in item and not isinstance(item['sku_include_ean'], bool): bad('sku_include_ean 须为 true/false')
    if 'image_description' in item and (not isinstance(item['image_description'], str) or not item['image_description'].strip()):
        bad('image_description 应是非空中文外观摘要')
    if 'image_scenes07' in item:
        scenes = item['image_scenes07']
        if not isinstance(scenes, list) or len(scenes) not in (0, 4) or not all(isinstance(s, str) and s.strip() for s in scenes):
            bad('image_scenes07 应为空数组或四个非空场景说明')
    if 'description_images' in item:
        order = item['description_images']
        if (not isinstance(order, list) or not order or
                any(not isinstance(s, str) or s not in tuple(f'{n:02d}' for n in range(1, 9)) for s in order) or
                len(set(order)) != len(order) or '03' not in order or order[0] == '03'):
            bad('description_images 应为不重复的 01～08 槽位数组，第一项是结果图，另含 03 细节图')
    for key, value in item.items():
        if isinstance(value, str) and re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', value):
            bad(f'{key} 含 Excel 不支持的控制字符')
    return errors
