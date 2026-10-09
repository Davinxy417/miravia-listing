"""Generate 80 x 50 mm Spanish product labels and a lossless, true-size A4 PDF.

入口：python scripts/mlist.py gpsr --batch 批次名
Dependencies: Pillow (plus Python standard library). Source files are read-only.
Manufacturer / EU REP assignments are the user's supplied importer mapping.
"""
from __future__ import annotations

import csv
import html
import json
import os
from pathlib import Path
import re
import sys
import zlib
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .content import seller_sku, resolve_content
from .common import read_csv, read_json, Problem, inside

SIZE = (945, 591)
DPI = 300
MIN_FONT = 25  # 25 pixels at 300 dpi = 6 pt; never shrink below this.

# Short product names derived from each group's Spanish title. B groups share
# the product name; quantity always comes from the individual priced.csv row.


def require(ok, message):
    if not ok:
        raise ValueError(message)


@lru_cache(None)
def font(size=MIN_FONT, bold=False):
    require(size >= MIN_FONT, '标签字体不能小于 6 pt；请缩短已核实文案或调整标签布局。')
    fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for name in (('arialbd.ttf', 'segoeuib.ttf') if bold else ('arial.ttf', 'segoeui.ttf')):
        path = fonts / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise FileNotFoundError('缺少 Windows Arial 或 Segoe UI 字体；请安装其中一种字体后生成 GPSR。')


def spanish_value(value):
    return re.sub(r'(?<=\d)\.(?=\d)', ',', value.strip())


NUMBER = r'\d+(?:[.,]\d+)?'
MEASURE = re.compile(rf'(?<![\w.,])({NUMBER}(?:\s*[xX×]\s*{NUMBER}){{0,2}})\s*(CM|MM|ML|L|M)(?![A-Z])', re.I)


def medidas(row, item=None):
    """Explicit source dimensions only. Never read package estimates."""
    src = row['src_name']
    # Source can contain a third dimension omitted from the variant value.
    sources = [src, row['var1_value'], row['var2_value']]
    for source in sources:
        match = MEASURE.search(source)
        if match:
            values = re.sub(r'\s*[xX×]\s*', 'x', match[1]).replace('.', ',')
            unit = {'cm': 'cm', 'mm': 'mm', 'ml': 'ml', 'l': 'L', 'm': 'm'}[match[2].lower()]
            result = f'{values} {unit}'
            if row['var1_name'] == 'Talla':
                result = 'Talla ' + result
            result += (item or {}).get('gpsr_measure_suffix', '')
            return result
    return ''


def material(row, content):
    """Only material explicitly stated in this group's content, scoped to SKU."""
    attrs = content['attributes']
    simple = re.search(r'(?:^|;)\s*Material:\s*([^;]+)', attrs, re.I)
    if simple:
        return simple[1].strip()
    scoped = re.search(r'Material del modelo de ([\d.,]+)\s*L:\s*([^;]+)', attrs, re.I)
    if scoped:
        if medidas(row) == spanish_value(scoped[1]) + ' L':
            return scoped[2].strip()
    return ''


def warning_items(item):
    texts = item.get('gpsr_safety')
    require(isinstance(texts, list) and 3 <= len(texts) <= 5
            and all(isinstance(t, str) and t.strip() for t in texts),
            'content.json 的 gpsr_safety 必须有 3～5 条非空西语提示；请补齐，程序不会编造安全提示。')
    source = [html.unescape(re.sub(r'<[^>]*>', '', x)).strip()
              for x in re.findall(r'<li>(.*?)</li>', item['warning_text'], re.S)]
    return texts, source


def wrap(text, face, width):
    lines, current = [], ''
    for word in text.split():
        require(face.getlength(word) <= width, f'标签单词过长：{word}；请核对短名或公司合法简称。')
        trial = (current + ' ' + word).strip()
        if face.getlength(trial) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


class Painter:
    def __init__(self):
        self.image = Image.new('RGB', SIZE, 'white')
        self.draw = ImageDraw.Draw(self.image)
        self.bounds = []

    def text(self, x, y, text, face, right, bottom):
        box = self.draw.textbbox((x, y), text, font=face, anchor='lt')
        require(box[0] >= 0 and box[2] <= right and box[3] <= bottom,
                f'标签文字超出区域：{text}；请缩短已核实短名或提示，不能缩小到 6 pt 以下。')
        self.draw.text((x, y), text, fill='black', font=face, anchor='lt')
        self.bounds.append(box)

    def block(self, x, y, text, width, bottom, size=25, bold=False, leading=28):
        face = font(size, bold)
        for line in wrap(text, face, width):
            self.text(x, y, line, face, x + width, bottom)
            y += leading
        return y

    def field(self, x, y, key, value, width, bottom, leading=28, gap=2):
        face, strong = font(), font(bold=True)
        prefix = key + ': '
        offset = strong.getlength(prefix)
        # Fit the first value line after its bold field name.
        words = value.split()
        first = ''
        while words and face.getlength((first + ' ' + words[0]).strip()) <= width - offset:
            first = (first + ' ' + words.pop(0)).strip()
        self.text(x, y, prefix.rstrip(), strong, x + width, bottom)
        if first:
            self.text(x + offset, y, first, face, x + width, bottom)
        y += leading
        if words:
            y = self.block(x, y, ' '.join(words), width, bottom, leading=leading)
        return y + gap


def icons(draw):
    """Open instruction book with i, and ordinary tidyman; no WEEE or CE."""
    x, y = 842, 365
    draw.line([(x, y+13), (x+18, y+7), (x+37, y+16), (x+56, y+7), (x+76, y+13), (x+76, y+66), (x+57, y+60), (x+37, y+69), (x+18, y+60), (x, y+66), (x, y+13)], fill='black', width=3)
    draw.line([(x+37, y+16), (x+37, y+69)], fill='black', width=2)
    draw.text((x+12, y+27), 'i', font=font(28, True), fill='black', anchor='lt')
    for dy in (28, 37, 46):
        draw.line([(x+47, y+dy), (x+65, y+dy-4)], fill='black', width=2)
    x, y = 842, 478
    draw.ellipse((x+8, y, x+22, y+14), outline='black', width=3)
    draw.line([(x+16, y+17), (x+12, y+43), (x+3, y+77)], fill='black', width=4)
    draw.line([(x+12, y+43), (x+33, y+77)], fill='black', width=4)
    draw.line([(x+15, y+23), (x+34, y+35), (x+46, y+31)], fill='black', width=3)
    draw.polygon([(x+43, y+38), (x+49, y+43), (x+45, y+48), (x+39, y+43)], outline='black', width=2)
    draw.line([(x+51, y+45), (x+58, y+77), (x+74, y+77), (x+80, y+45)], fill='black', width=3)
    draw.line([(x+49, y+45), (x+82, y+45)], fill='black', width=3)


def render(record, company, address, email, warnings):
    p = Painter()
    d = p.draw
    d.rectangle((1, 1, 943, 589), outline='black', width=2)
    d.line((492, 2, 492, 190), fill='black', width=2)
    d.line((2, 190, 943, 190), fill='black', width=2)
    d.line((2, 310, 943, 310), fill='black', width=2)
    # Colour SKUs now include EANs. Seven lines fit without reducing the 6 pt font.
    y = 8
    for key, value in [('Nombre', record['nombre']), ('Modelo', record['SKU']),
                       ('Medidas', record['medidas']), ('Contenido', record['contenido']),
                       ('Material', record['material'])]:
        if value:
            y = p.field(17, y, key, value, 458, 185, leading=25, gap=0)
    y = p.field(510, 14, 'Fabricante', company, 416, 185)
    y = p.field(510, y, 'Dirección', address, 416, 185)
    p.field(510, y, 'Email', email, 416, 185)
    d.rectangle((17, 220, 148, 280), outline='black', width=2)
    d.line((68, 220, 68, 280), fill='black', width=2)
    p.text(25, 237, 'EU', font(28, True), 65, 280)
    p.text(77, 237, 'REP', font(28, True), 145, 280)
    y = p.field(165, 201, 'Nombre', company, 761, 308, leading=26, gap=1)
    y = p.field(165, y, 'Dirección', address, 761, 308, leading=26, gap=1)
    p.field(165, y, 'Email', email, 761, 308, leading=26, gap=1)
    p.text(17, 321, 'Información de seguridad', font(28, True), 820, 353)
    y = 357
    for warning in warnings:
        d.ellipse((18, y+8, 23, y+13), fill='black')
        y = p.block(33, y, warning, 787, 578, leading=27) + 2
    icons(d)
    # Ensure no independently placed text boxes overlap (icons are separate).
    for i, a in enumerate(p.bounds):
        for b in p.bounds[i+1:]:
            require(not (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]), f'标签文字重叠：{a}, {b}；请调整文字或标签排版。')
    return p.image, len(p.bounds)


def pdf_stream(data, extra=''):
    return (f'<< /Length {len(data)} {extra} >>\nstream\n'.encode('ascii') + data + b'\nendstream')


def write_pdf(images, target):
    """Small standard-library PDF writer. Lossless RGB, exact mm placements.

    2 columns x 5 rows: each label 80 x 50 mm; 3 mm between labels.
    A4 MediaBox uses exact points. /PrintScaling /None requests actual size.
    """
    objects = [b'', b'']
    def add(data):
        objects.append(data)
        return len(objects)
    pages = []
    pt = 72 / 25.4
    for start in range(0, len(images), 10):
        group = images[start:start+10]
        names, commands = [], []
        for n, im in enumerate(group):
            encoded = zlib.compress(im.tobytes(), 9)
            obj = add(pdf_stream(encoded, '/Type /XObject /Subtype /Image /Width 945 /Height 591 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Interpolate false'))
            names.append(f'/Im{n} {obj} 0 R')
            col, row = n % 2, n // 2
            x, y = (23.5 + col * 83) * pt, (297 - 17.5 - row * 53 - 50) * pt
            commands.append(f'q {80*pt:.8f} 0 0 {50*pt:.8f} {x:.8f} {y:.8f} cm /Im{n} Do Q')
        stream = add(pdf_stream(('\n'.join(commands) + '\n').encode('ascii')))
        pages.append(add((f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {210*pt:.8f} {297*pt:.8f}] /Resources << /XObject << {" ".join(names)} >> >> /Contents {stream} 0 R >>').encode('ascii')))
    objects[0] = b'<< /Type /Catalog /Pages 2 0 R /ViewerPreferences << /PrintScaling /None >> >>'
    objects[1] = (f'<< /Type /Pages /Count {len(pages)} /Kids [{" ".join(f"{n} 0 R" for n in pages)}] >>').encode('ascii')
    result = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f'{n} 0 obj\n'.encode('ascii') + obj + b'\nendobj\n')
    xref = len(result)
    result.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode('ascii'))
    for offset in offsets[1:]:
        result.extend(f'{offset:010d} 00000 n \n'.encode('ascii'))
    result.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode('ascii'))
    target.write_bytes(result)
    return len(pages)


def run(batch, shop):
    rows = read_csv(batch / 'priced.csv')
    require(bool(rows), 'priced.csv 为空；请先运行 price。')
    content, errors = resolve_content(read_json(batch / 'content.json'), [r['group'] for r in rows])
    if errors: raise Problem(errors)
    out = inside(batch, batch / 'output/gpsr')
    labels = inside(batch, out / 'labels')
    records, rendered, audit, seen = [], [], [], set()
    # Validate all layouts before creating any output files.
    for row in rows:
        item = content[row['group']]
        sku = seller_sku(row, shop, item)
        require(sku not in seen and re.fullmatch(r'[A-Za-z0-9]+-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*', sku), f'SKU 重复或含不适合文件名的字符：{sku}；请核对货号和 SKU 配置。')
        seen.add(sku)
        group = row['group']
        item = content[group]
        require(row['shop'] in shop['suppliers'], f"商家 {row['shop']} 未配置；请补齐 shop.json.suppliers。")
        company, address, email = (shop['suppliers'][row['shop']][k] for k in ('company', 'address', 'email'))
        variants = [spanish_value(row[k]) for k in ('var1_value', 'var2_value') if row[k].strip()]
        require(bool(item.get('gpsr_name')), f'{group} 缺 gpsr_name；请在 content.json 填商品短名。')
        nombre = item['gpsr_name'] + (': ' + ', '.join(variants) if variants else '')
        qty = int(row['pack_qty'])
        record = dict(SKU=sku, group=group, shop=row['shop'], nombre=nombre, medidas=medidas(row, item),
                      contenido=f'{qty} unidad' + ('es' if qty != 1 else ''), material=material(row, item), fabricante=company)
        warnings, source = warning_items(item)
        im, boxes = render(record, company, address, email, warnings)
        records.append(record)
        rendered.append(im)
        audit.append(dict(SKU=sku, warning_source=source, printed_warnings=warnings, text_boxes=boxes))
    labels.mkdir(parents=True, exist_ok=True)
    for record, im in zip(records, rendered):
        im.save(labels / (record['SKU'] + '.png'), dpi=(DPI, DPI))
        preview = Image.new('RGB', (1200, 1200), 'white')
        preview.paste(im, ((1200 - SIZE[0]) // 2, (1200 - SIZE[1]) // 2))
        preview.save(labels / (record['SKU'] + '_preview.jpg'), quality=95, subsampling=0)
    with (labels / 'index.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    pages = write_pdf(rendered, out / 'print_A4.pdf')
    report = dict(count=len(records), png_size=list(SIZE), dpi=DPI, min_font_pt=MIN_FONT*72/DPI,
                  pdf_pages=pages, label_mm=[80, 50], gap_mm=3,
                  omitted_medidas=[r['SKU'] for r in records if not r['medidas']],
                  omitted_material=[r['SKU'] for r in records if not r['material']], warning_audit=audit)
    (out / 'generation_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return dict(count=len(records), output=str(out), pdf_pages=pages,
                warnings=[f"{r['SKU']} 缺少已核实的商品尺寸或材质，标签已省略该项。"
                          for r in records if not r['medidas'] or not r['material']],
                message='GPSR 标签已生成；请按实际尺寸 100% 打印 A4 PDF。')
