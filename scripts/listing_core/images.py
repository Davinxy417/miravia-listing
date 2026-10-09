"""批次变体和图片网址解析；未托管时保留旧流程占位行为。"""
import re
from urllib.parse import urlsplit
from .common import Problem, component, read_csv, require
from .image_layout import SLOTS, VARIANT_SLOT, hero_variant


def variant_key(row):
    return row['group'], row['art_id'], row['ean']


def read_variantes(path):
    mappings, errors = {}, []
    candidates = read_csv(path.parent / 'candidates.csv')
    for n, item in enumerate(read_csv(path, ['group', 'art_id', 'variante']), 2):
        try:
            component(item['group'], '商品组'); component(item['variante'], '变体目录')
            matches = [item] if item.get('ean') else [r for r in candidates if (r['group'], r['art_id']) == (item['group'], item['art_id'])]
            require(matches, f'variantes.csv 第 {n} 行没有对应候选；请补齐候选或删除过期映射。')
            for row in matches:
                key = variant_key(row)
                require(key not in mappings, f'variantes.csv 第 {n} 行重复映射 {key}；请保留一条。')
                mappings[key] = item['variante']
        except (ValueError, KeyError) as exc: errors.append(str(exc))
    if errors: raise Problem(errors)
    return mappings


def image_url_ok(value):
    try: url = urlsplit(value)
    except ValueError: return False
    return (url.scheme in ('http', 'https') and bool(url.netloc)
            and re.search(r'\.(jpg|jpeg|png|webp)$', value, re.I) is not None and not re.search(r'\s', value))


def read_image_urls(path, mappings):
    images, errors = {}, []
    if not path.exists(): return images
    allowed = {(g, v) for (g, _, _), v in mappings.items()}
    for n, item in enumerate(read_csv(path), 2):
        if (item['group'], item['variante']) not in allowed: continue
        group, variant, slot, url = item['group'], item['variante'], item['slot'], item['url']
        label = f'images.csv 第 {n} 行 {group}/{variant}/{slot}'
        if slot != VARIANT_SLOT and not re.fullmatch(r'0?[1-8]', slot):
            errors.append(f'{label} 槽位不正确；请用 01～08 或 variante。'); continue
        slot = slot if slot == VARIANT_SLOT else int(slot)
        if not url: continue
        expected = 'variante.jpg' if slot == VARIANT_SLOT else SLOTS[f'{slot:02d}']
        if not image_url_ok(url) or not url.lower().endswith('.jpg'):
            errors.append(f'{label} 不是 .jpg 直链；请重新生成图片网址。'); continue
        if urlsplit(url).path.rsplit('/', 1)[-1] != expected or 'gpsr' in urlsplit(url).path.lower():
            errors.append(f'{label} 必须指向 {expected}，不能使用 GPSR 图片。'); continue
        key = group, variant, slot
        if key in images and images[key] != url: errors.append(f'{label} 重复且网址冲突；请保留正确的一条。')
        images[key] = url
    if errors: raise Problem(errors)
    return images


def placeholder(row):
    return f"https://img-eu-2.freex.es/img/{row['shop']}/{row['art_id']}/600x600/{row['img_hash']}"


def group_images(group, rows, mappings, images, images_dir, warnings):
    folders = {}
    for row in rows: folders.setdefault(mappings[variant_key(row)], row)
    variants = {}
    for variant, row in folders.items():
        url = images.get((group, variant, VARIANT_SLOT))
        if not url:
            warnings.add(f'{group}/{variant} 缺变体图网址；暂用友购占位链接，正式上传前请完成图床和 images-urls。')
        variants[variant] = url or placeholder(row)
    hero = hero_variant(group, list(folders), images_dir)
    principal = images.get((group, hero, 1))
    if not principal:
        warnings.add(f'{group}/{hero} 缺主图网址；暂用友购占位链接，正式上传前请补齐。')
    missing = [f'{i:02d}' for i in range(2, 9) if (group, hero, i) not in images]
    if missing: warnings.add(f'{group}/{hero} 展示图网址未齐：{", ".join(missing)}；请完成图片后重新生成网址。')
    gallery = [principal or placeholder(folders[hero])] + [images[group, hero, i] for i in range(2, 9) if (group, hero, i) in images]
    return list(dict.fromkeys(gallery)), variants
