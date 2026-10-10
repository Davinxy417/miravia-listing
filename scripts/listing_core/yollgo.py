"""条码查询、报价选店、公开商家资料和原图总览；浏览器可替换为离线假对象。"""
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from .common import Problem, atomic_bytes, component, inside, read_csv, require, write_json


def read_barcodes(path):
    result, seen = [], set()
    for line_no, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        parts = line.lstrip().split(maxsplit=1)
        barcode = parts[0]
        require(barcode.isascii() and barcode.isdigit(),
                f'barcodes.txt 第 {line_no} 行条码 {barcode!r} 不是数字；请把备注放在条码后的空格后。')
        require(barcode not in seen, f'barcodes.txt 第 {line_no} 行条码 {barcode} 重复；请合并为一行。')
        seen.add(barcode)
        result.append(dict(barcode=barcode, note=parts[1] if len(parts) > 1 else ''))
    require(result, 'barcodes.txt 没有条码；请一行写一个条码后重新运行 fetch。')
    return result


def number(value, label, positive=False):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise Problem(f'{label} 不是有效数值；请核对友购资料。') from None
    require(not isinstance(value, bool) and math.isfinite(result) and (result > 0 if positive else result >= 0),
            f'{label} 必须是{"大于 0" if positive else "非负"}的有限数值；请核对友购资料。')
    return result


def other_candidates(ws, batch):
    """保留来源，提醒时同时显示批次、组及 EAN/unit_ean。"""
    result = []
    for directory in sorted((Path(ws) / 'batches').iterdir()):
        if not directory.is_dir() or directory.resolve() == Path(batch).resolve():
            continue
        path = directory / 'candidates.csv'
        if path.is_file():
            for row in read_csv(path, ['group', 'ean']):
                result.append((directory.name, row))
    return result


def public_shops(shops):
    fields = ('shopId', 'name', 'namees', 'des', 'tel', 'baseurl', 'imgurl')
    result = {}
    for shop in shops:
        require(isinstance(shop, dict) and str(shop.get('shopId', '')).strip(), '友购批发商资料缺少 shopId；请检查网页后重试。')
        sid = str(shop['shopId'])
        result[sid] = {key: shop[key] for key in fields if key in shop}
        result[sid]['shopId'] = sid
    return result


def image_url(shop, product):
    base = shop.get('baseurl', '').rstrip('/')
    parsed = urlsplit(base)
    require(parsed.scheme == 'https' and parsed.netloc and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
            f'批发商 {shop.get("shopId")} 缺少可用原图地址；请先在友购关注该商家后重新 fetch。')
    return base + '/img/' + '/'.join(quote(str(value), safe='') for value in
                                  (shop['shopId'], product['artId'], '600x600', product['imageHash']))


def contact_sheet(batch, items, directory='src'):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    selected = [item for item in items if item['selected']]
    if not selected:
        # A previous sheet must not falsely represent an empty new fetch.
        inside(batch, batch / directory / '_sheet.jpg').unlink(missing_ok=True)
        return None
    font = None
    for name in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf', 'DejaVuSans.ttf'):
        try:
            font = ImageFont.truetype(name, 17)
            break
        except OSError:
            pass
    font = font or ImageFont.load_default()
    columns, cell_w, cell_h = min(4, len(selected)), 330, 410
    sheet = Image.new('RGB', (columns * cell_w, math.ceil(len(selected) / columns) * cell_h), 'white')
    draw = ImageDraw.Draw(sheet)
    for index, item in enumerate(selected):
        offer = selected_offer(item)
        product = offer['product']
        x, y = index % columns * cell_w, index // columns * cell_h
        path = Path(item['image_path']) if item.get('image_path') else batch / 'src' / f'{offer["shop_id"]}-{product["artId"]}.jpg'
        if path.is_file():
            with Image.open(path) as source:
                thumb = ImageOps.contain(ImageOps.exif_transpose(source).convert('RGB'), (310, 290))
                sheet.paste(thumb, (x + (cell_w - thumb.width) // 2, y + 5))
        else:
            draw.text((x + 10, y + 120), '原图未下载', fill='red', font=font)
        draw.text((x + 10, y + 299), item['barcode'], fill='black', font=font)
        # Reserve the footer for the price even when the product name is long.
        lines, line = [], ''
        for char in str(product.get('namecn') or product.get('namees') or ''):
            if draw.textlength(line + char, font=font) > cell_w - 20:
                lines.append(line)
                line = ''
            line += char
        if line:
            lines.append(line)
        for offset, line in enumerate(lines[:3]):
            draw.text((x + 10, y + 320 + offset * 21), line, fill='black', font=font)
        footer = f'€{product.get("precio", "")}  {offer["shop_name"]}'
        while draw.textlength(footer, font=font) > cell_w - 20:
            footer = footer[:-2] + '…'
        draw.text((x + 10, y + 387), footer, fill='black', font=font)
    import io
    stream = io.BytesIO()
    sheet.save(stream, format='JPEG', quality=90)
    path = inside(batch, batch / directory / '_sheet.jpg')
    atomic_bytes(path, stream.getvalue())
    return str(path)


def selected_offer(item):
    selected = item.get('selected')
    require(isinstance(selected, dict), f'yollgo.json 条码 {item.get("barcode")} 没有选中的报价；请重新 fetch。')
    require(isinstance(item.get('offers'), list) and all(isinstance(o, dict) and isinstance(o.get('product'), dict) for o in item['offers']),
            f'yollgo.json 条码 {item.get("barcode")} 的 offers 格式不对；请重新 fetch。')
    matches = [offer for offer in item.get('offers', []) if selected and
               offer.get('shop_id') == selected.get('shop_id') and
               str(offer.get('product', {}).get('artId', '')) == selected.get('art_id')]
    require(len(matches) == 1, f'yollgo.json 条码 {item.get("barcode")} 的 selected 没有唯一对应报价；请重新 fetch。')
    return matches[0]


def fetch(ws, batch, shop, client):
    requested = read_barcodes(batch / 'barcodes.txt')
    shops = public_shops(client.shops())
    # Retain public entries fetched earlier, never save App authentication data.
    shop_file = inside(ws, ws / 'yollgo_shops.json')
    from .common import read_json
    previous = read_json(shop_file) if shop_file.exists() else {}
    require(isinstance(previous, dict), 'yollgo_shops.json 应为商家 id 对象；请修正后重试。')
    previous.update(shops)
    write_json(shop_file, previous)
    configured = list(shop['suppliers'])
    order = configured + [sid for sid in shops if sid not in configured]
    history = other_candidates(ws, batch)
    items, warnings = [], []
    issues = dict(not_found=[], unregistered=[], zero_price=[], already_listed=[], bulk_minimum=[])
    for request in requested:
        barcode = request['barcode']
        offers, seen = [], set()
        for sid in order:
            for product in client.search(sid, barcode):
                if barcode not in (str(product.get('bianhao', '')), str(product.get('usercode', ''))):
                    continue
                art_id = str(product.get('artId', ''))
                component(sid, '友购商家 id')
                component(art_id, '友购货号')
                if (sid, art_id) in seen:
                    continue
                seen.add((sid, art_id))
                number(product.get('precio'), f'条码 {barcode} / 商家 {sid} 的 precio')
                public = shops.get(sid, {})
                offers.append(dict(shop_id=sid, shop_name=public.get('name') or shop['suppliers'].get(sid, {}).get('company', sid),
                                   shop_name_es=public.get('namees', ''), product=dict(product)))
        item = dict(**request, offers=offers, selected=None)
        items.append(item)
        for batch_name, row in history:
            if barcode in (row.get('ean'), row.get('unit_ean')):
                issue = dict(barcode=barcode, batch=batch_name, group=row['group'])
                if issue not in issues['already_listed']:
                    issues['already_listed'].append(issue)
                    warnings.append(f'已经上过：条码 {barcode} 出现在批次 {batch_name} / 组 {row["group"]}。')
        if not offers:
            issues['not_found'].append(barcode)
            warnings.append(f'找不到：条码 {barcode}；请核对条码或在友购关注对应批发商。')
            continue
        registered = [offer for offer in offers if offer['shop_id'] in configured]
        chosen = min(registered, key=lambda o: (configured.index(o['shop_id']), float(o['product']['precio']))) if registered else min(offers, key=lambda o: float(o['product']['precio']))
        product, sid = chosen['product'], chosen['shop_id']
        item['selected'] = dict(shop_id=sid, art_id=str(product['artId']))
        if not registered:
            issues['unregistered'].append(dict(barcode=barcode, shop_id=sid, shop_name=chosen['shop_name']))
            warnings.append(f'未登记：条码 {barcode} 选择最便宜的 {chosen["shop_name"]}（{sid}），shop.json.suppliers 没有该商家，制造商会空；请先登记并补配置。')
        if float(product['precio']) == 0:
            issues['zero_price'].append(barcode)
            warnings.append(f'价格为 0：条码 {barcode} / 商家 {sid}；请向批发商核实后再定价。')
        minimum = number(product.get('baozhuangshu', 1), f'条码 {barcode} 的 baozhuangshu', positive=True)
        if minimum > 1:
            issues['bulk_minimum'].append(dict(barcode=barcode, quantity=minimum))
            warnings.append(f'起订量大：条码 {barcode} 要按 {minimum:g} 个整包拿货，有单再拿货时会压货。')
    data = dict(version=1, fetched_at=datetime.now(timezone.utc).isoformat(), items=items)
    write_json(inside(batch, batch / 'yollgo.json'), data)
    inside(batch, batch / 'src').mkdir(exist_ok=True)
    # Download every quote's original, since another shop may carry a different
    # image for the same barcode. The overview uses only the selected quote.
    for item in items:
        if not item['selected']:
            continue
        for offer in item['offers']:
            product, sid = offer['product'], offer['shop_id']
            target = inside(batch, batch / 'src' / f'{sid}-{product["artId"]}.jpg')
            if target.exists():
                continue
            try:
                require(product.get('imageHash'), f'条码 {item["barcode"]} 没有 imageHash；请核对友购原图。')
                data = client.image(image_url(shops.get(sid, {'shopId': sid}), product))
                from PIL import Image
                import io
                # Verify the image and retain original JPEG bytes unchanged.
                with Image.open(io.BytesIO(data)) as source:
                    source.load()
                    if source.format != 'JPEG':
                        stream = io.BytesIO()
                        source.convert('RGB').save(stream, format='JPEG', quality=95)
                        data = stream.getvalue()
                atomic_bytes(target, data)
            except (Problem, OSError, ValueError) as exc:
                warnings.append(f'条码 {item["barcode"]} / 店 {sid} 原图未下载：{exc}；可重新运行 fetch 补下。')
    sheet = contact_sheet(batch, items)
    return dict(count=len(items), found=sum(item['selected'] is not None for item in items),
                output=str(batch / 'yollgo.json'), sheet=sheet, issues=issues, warnings=warnings,
                message='友购查询完成，所有报价已保存；请看原图总览，再填写 groups.json。')


def search(client, shop_id, keyword, root=None):
    component(shop_id, '友购商家 id')
    rows = client.search(shop_id, keyword)
    shops = public_shops(client.shops()) if root is not None else {}
    public = shops.get(shop_id, {'shopId': shop_id})
    products, items, warnings = [], [], []
    directory = Path('search') / shop_id
    for row in rows:
        art_id = component(str(row.get('artId', '')), '友购货号')
        product = dict(barcode=str(row.get('bianhao') or row.get('usercode', '')),
                       art_id=art_id, usercode=str(row.get('usercode', '')),
                       name=row.get('namecn') or row.get('namees', ''),
                       namecn=row.get('namecn', ''), namees=row.get('namees', ''),
                       price=row.get('precio'), image_url=None, image_path=None)
        if root is not None:
            target = inside(root, Path(root) / directory / f'{art_id}.jpg')
            try:
                require(row.get('imageHash'), f'货号 {art_id} 缺 imageHash')
                product['image_url'] = image_url(public, row)
                if not target.is_file():
                    import io
                    from PIL import Image
                    data = client.image(product['image_url'])
                    with Image.open(io.BytesIO(data)) as source:
                        source.load()
                        if source.format != 'JPEG':
                            stream = io.BytesIO()
                            source.convert('RGB').save(stream, 'JPEG', quality=95)
                            data = stream.getvalue()
                    atomic_bytes(target, data)
            except (Problem, OSError, ValueError) as exc:
                warnings.append(f'货号 {art_id} 原图未下载：{exc}；请重跑 yollgo-search 补下。')
            if target.is_file(): product['image_path'] = str(target)
            items.append(dict(barcode=product['barcode'], image_path=product['image_path'],
                selected=dict(shop_id=shop_id, art_id=art_id), offers=[dict(shop_id=shop_id,
                shop_name=public.get('name', shop_id), product=dict(row,
                namecn=f"{row.get('usercode', '')}  {row.get('namecn', '')}  {row.get('namees', '')}"))]))
        products.append(product)
    sheet = contact_sheet(Path(root), items, directory) if root is not None else None
    return dict(count=len(products), products=products, sheet=sheet, warnings=warnings,
                message='友购搜索完成；请看两种原名、货号和候选原图总览再选品。')
