"""Script-only shop overlays. No generation API, network calls or invented measurements.

python scripts/mlist.py overlay --batch 批次 --all --demo
python scripts/mlist.py overlay --batch 批次 --group 组名
Bases: images/GROUP/variante/internal/base/ (group-level bases apply to hero only).
Existing numbered outputs are NEVER treated as clean bases outside --demo.
"""
import argparse
import copy
import csv
import io
import json
import math
import os
import re
import shutil
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageCms, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

from .image_layout import ROOT, SHARED_SLOTS, SLOTS, hero_variant, output_dir, variant_folders
from .line_icons import icon

SIZE = 1200
MAX_BYTES = 3145728
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
PROFILE = SRGB.tobytes()
BASE_NAMES = {**SLOTS, "06": "06-medidas.jpg"}


def merge(base, override):
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def resolve_config(config, group, variant=None, seen=()):
    if group in seen:
        raise ValueError(f"叠字配置循环继承：{seen + (group,)}；请修改 overlays.json 的 inherits。")
    item = config[group]
    base = resolve_config(config, item["inherits"], seen=seen + (group,)) if "inherits" in item else {}
    result = merge(base, item)
    if variant:
        result = merge(result, result.get("variants", {}).get(variant, {}))
    return result


def validate_config(config):
    for group in config:
        for variant in [None, *resolve_config(config, group).get("variants", {})]:
            item = resolve_config(config, group, variant)
            if set(item["slots"]) != {*SLOTS, "variante"}:
                raise ValueError(f"{group} 缺图片槽位配置；请在 overlays.json 补齐 01～08 和 variante。")
            titles = [item["slots"][s]["title"].casefold() for s in ("04", "05", "08")]
            if len(set(titles)) != 3:
                raise ValueError(f"{group} 的 04/05/08 标题重复；请分别填写不同场景标题。")
            for slot, text in item["slots"].items():
                if len(text.get("title", "").split()) > 6:
                    raise ValueError(f"{group}/{slot} 标题超过六个词；请缩短标题。")
                if slot in ("01", "variante") and text.get("title"):
                    raise ValueError(f"{group}/{slot} 应是无字图片；请清空该槽位 title。")
                for point in text.get("points", []):
                    if not 2 <= len(point["text"].split()) <= 3:
                        raise ValueError(f"{group}/{slot} 卖点应为 2～3 个词；请调整 points 文案。")
                if slot == "02" and not 3 <= len(text.get("points", [])) <= 4:
                    raise ValueError(f"{group} 的 02 需要 3～4 个图标卖点；请补齐 points。")
                if slot == "07" and (len(text.get("scenes", [])) != 4 or text.get("layout") not in ("2x2", "1+3")):
                    raise ValueError(f"{group} 的 07 需要四个场景，布局为 2x2 或 1+3；请修改配置。")
                if slot not in ("01", "variante"):
                    heading_layout(text.get("title", ""), text.get("subtitle", ""), 1104)
                if text.get("anchor", "auto") not in ("auto", "top", "left", "center"):
                    raise ValueError(f"{group}/{slot} 标题位置不支持；anchor 请用 auto/top/left/center。")


@lru_cache(maxsize=96)
def font(size, weight=800):
    if size < 30:
        raise ValueError("叠字字体不能小于 30 像素；请缩短文案或调整排版。")
    path = ROOT / "assets/fonts/Montserrat-Variable.ttf"
    if not path.is_file():
        raise ValueError("缺少 Montserrat 字体；请恢复 assets/fonts/Montserrat-Variable.ttf。")
    face = ImageFont.truetype(str(path), size)
    face.set_variation_by_axes([weight])
    return face


def load_image(path, contain=False):
    with Image.open(path) as source:
        im = ImageOps.exif_transpose(source)
        alpha = im.getchannel("A") if "A" in im.getbands() else None
        if source.info.get("icc_profile"):
            im = ImageCms.profileToProfile(im.convert("RGB"),
                  ImageCms.ImageCmsProfile(io.BytesIO(source.info["icc_profile"])), SRGB, outputMode="RGB")
        else:
            im = im.convert("RGB")
        if alpha is not None:
            background = Image.new("RGB", im.size, "white")
            background.paste(im, (0, 0), alpha)
            im = background
        if contain:
            fitted = ImageOps.contain(im, (SIZE, SIZE), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (SIZE, SIZE), "white")
            canvas.paste(fitted, ((SIZE-fitted.width)//2, (SIZE-fitted.height)//2))
            return canvas
        return ImageOps.fit(im, (SIZE, SIZE), Image.Resampling.LANCZOS)


def save_jpg(im, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for quality in (94, 90, 85, 80, 75, 65, 50):
        blob = io.BytesIO()
        im.convert("RGB").save(blob, "JPEG", quality=quality, optimize=True, icc_profile=PROFILE)
        if blob.tell() < MAX_BYTES:
            path.write_bytes(blob.getvalue())
            return
    raise ValueError(f"图片压缩后仍超过 {MAX_BYTES} 字节：{path}；请简化底图后重试。")


def ensure_variant_image(directory):
    """Synchronize the variant copy when a new/updated principal arrives."""
    directory = Path(directory)
    principal, target = directory / SLOTS["01"], directory / "variante.jpg"
    if not principal.is_file():
        return None
    # The collection pipeline can read groups being produced by another task
    # without refreshing files inside those directories.
    protected = os.environ.get("OVERLAY_READ_ONLY_GROUPS", "").split(",")
    if len(directory.parents) > 3 and directory.parents[3].name in protected:
        return target if target.is_file() else None
    if not target.exists() or target.stat().st_mtime_ns < principal.stat().st_mtime_ns:
        save_jpg(load_image(principal, contain=True), target)
    return target


def palette(im):
    small = im.crop((120,120,1080,1080)).resize((80,80))
    colours = [p for p in small.getdata() if 35 < sum(p)/3 < 205]
    if not colours:
        colours = list(small.getdata())
    # Dominant product colour, darkened until text/background has ample contrast.
    sample = Image.new("RGB", (len(colours), 1))
    sample.putdata(colours)
    q = sample.quantize(colors=6)
    index = max(q.getcolors(), key=lambda item:item[0])[1]
    rgb = q.getpalette()[index*3:index*3+3]
    dark = tuple(round(v * .32) for v in rgb)
    light = tuple(round(v*.13 + 255*.87) for v in rgb)
    return dark, light


def wrap(text, face, width):
    lines, current = [], ""
    for word in text.split():
        trial = (current + " " + word).strip()
        if face.getlength(trial) > width and current:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def heading_layout(title, subtitle, width):
    for size in range(88, 71, -2):
        face = font(size, 800)
        lines = wrap(title, face, width)
        if len(lines) <= 2 and all(face.getlength(line) <= width for line in lines):
            break
    else:
        raise ValueError(f"标题放不进两行：{title}；请缩短标题。")
    for subsize in (40, 38, 36, 34):
        subface = font(subsize, 600)
        if subface.getlength(subtitle) <= width:
            break
    else:
        raise ValueError(f"副标题放不进一行：{subtitle}；请缩短副标题。")
    height = len(lines) * (size + 10) + (subsize + 30 if subtitle else 0)
    return face, lines, subface, height


def top_gradient(im, force=False):
    region = im.crop((0, 0, SIZE, 360)).convert("L")
    stats = ImageStat.Stat(region)
    if not force and stats.mean[0] > 242 and stats.stddev[0] < 14:
        return im.copy()
    layer = Image.new("RGBA", im.size)
    draw = ImageDraw.Draw(layer)
    end = 468  # 39% of the canvas; no rectangular title panel.
    for y in range(end):
        draw.line((0, y, SIZE, y), fill=(255, 255, 255, round(217 * (1-y/end))))
    return Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")


def text_colour(colours, im):
    rgb = colours[0]
    def luminance(values):
        linear = [v/255/12.92 if v/255 <= .04045 else ((v/255+.055)/1.055)**2.4 for v in values]
        return sum(a*b for a,b in zip(linear, (.2126, .7152, .0722)))
    # Sample the lightened title area, choosing the shop's dark fallback if
    # the product colour would not provide readable contrast.
    background = ImageStat.Stat(im.crop((48, 48, 1152, 330))).mean
    if (luminance(background)+.05)/(luminance(rgb)+.05) < 4.5:
        return (43, 36, 32)
    return rgb


def heading_anchor(im):
    left = ImageStat.Stat(im.crop((48, 48, 548, 320)).convert("L"))
    right = ImageStat.Stat(im.crop((652, 48, 1152, 320)).convert("L"))
    return "left" if left.stddev[0] + 16 < right.stddev[0] else "center"


def text_block(im, title, colours, subtitle="", anchor="auto", x=48, width=1104):
    face, lines, subface, _ = heading_layout(title, subtitle, width)
    if anchor == "auto":
        anchor = heading_anchor(im)
    im = top_gradient(im)
    draw = ImageDraw.Draw(im)
    colour = text_colour(colours, im)
    y = 54
    for line in lines:
        xx = x+(width-face.getlength(line))/2 if anchor == "center" else x
        draw.text((xx, y), line, font=face, fill=colour, anchor="lt")
        y += face.size+10
    if subtitle:
        y += 16
        xx = x+(width-subface.getlength(subtitle))/2 if anchor == "center" else x
        draw.text((xx, y), subtitle, font=subface, fill=colour, anchor="lt")
    return im


def capsule(im, label, colours, at=None, size=50):
    face = font(size, 800)
    width = math.ceil(face.getlength(label)) + 56
    if width > SIZE-96:
        raise ValueError(f"标签文字过宽：{label}；请缩短文字。")
    height = size+40
    x, y = at or ((SIZE-width)//2, SIZE-height-42)
    if x < 0 or y < 0 or x+width > SIZE or y+height > SIZE:
        raise ValueError("文字标签超出画布；请调整位置。")
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle((x, y, x+width, y+height), radius=height//2, fill=colours[0])
    draw.text((x+width/2, y+height/2), label, font=face, fill="white", anchor="mm")
    return im


def spec_badge(rows):
    dims, caps = verified_specs(rows)
    if dims:
        return " x ".join(d.replace(".", ",") for d in dims[:2])+" cm"
    # A shared folder may include several capacities: list all verified
    # options rather than making a single-capacity claim about the photograph.
    if len(caps) > 1 and len({c.split()[-1] for c in caps}) == 1:
        return " / ".join(c.split()[0] for c in caps)+" "+caps[0].split()[-1]
    return " / ".join(caps)


def points_overlay(im, entry, colours, rows=()):
    side = entry.get("side", "right")
    layout = entry.get("points_layout", "2x2")
    im = text_block(im, entry["title"], colours, entry.get("subtitle", ""), entry.get("anchor", "auto"))
    panel = Image.new("RGBA", im.size)
    draw = ImageDraw.Draw(panel)
    # A gentle side wash gives icons breathing room on scene photographs.
    for xx in range(520):
        x = SIZE-520+xx if side == "right" else 519-xx
        draw.line((x, 350, x, SIZE), fill=(255, 255, 255, round(190*xx/519)))
    face = font(32, 800)
    for index, point in enumerate(entry["points"]):
        if layout == "vertical":
            cx = 1020 if side == "right" else 180
            y = 350+index*205
            label_width = 256
        else:
            cx = (828 if side == "right" else 156)+(index%2)*216
            y = 390+(index//2)*345
            label_width = 210
        draw.ellipse((cx-75, y, cx+75, y+150), fill=(*colours[1], 255))
        panel.alpha_composite(icon(point["icon"], 70, colours[0], stroke_width=5), (cx-35, y+40))
        lines = wrap(point["text"], face, label_width)
        if len(lines) > 2 or any(face.getlength(line) > label_width for line in lines):
            raise ValueError(f"图标文字放不进两行：{point['text']}；请缩短卖点。")
        yy = y+168
        for line in lines:
            draw.text((cx, yy), line, font=face, fill=(*colours[0], 255), anchor="mt")
            yy += 40
    im = Image.alpha_composite(im.convert("RGBA"), panel).convert("RGB")
    badge = spec_badge(rows)
    if badge:
        # Opposite the icon grid and below the heading, above the product.
        width = math.ceil(font(50).getlength(badge))+56
        x = 48 if side == "right" else SIZE-48-width
        _, _, _, height = heading_layout(entry["title"], entry.get("subtitle", ""), 1104)
        im = capsule(im, badge, colours, (x, 54+height+26))
    return im


def zoom_circle(im, macro, colours, entry):
    diameter = 400
    if "zoom_at" in entry:
        x,y = entry["zoom_at"]
    else:
        # Compare both lower corners against the background to choose the
        # quieter side; reviewed zoom_at can override the automatic position.
        boxes = [(48, 748), (752, 748)]
        background = im.getpixel((0, SIZE-1))
        def occupancy(position):
            xx, yy = position
            crop = im.crop((xx, yy, xx+diameter, yy+diameter))
            return sum(ImageStat.Stat(ImageChops.difference(crop, Image.new("RGB", crop.size, background))).mean)
        x,y = min(boxes, key=occupancy)
    if x < 0 or y < 0 or x+diameter > SIZE or y+diameter > SIZE:
        raise ValueError("放大圈超出画布；请调整 zoom_at。")
    source = load_image(macro)
    crop = entry.get("macro_crop", [0.2,0.2,0.8,0.8])
    source = source.crop(tuple(round(v*SIZE) for v in crop)).resize((diameter,diameter),Image.Resampling.LANCZOS)
    mask = Image.new("L",(diameter,diameter))
    ImageDraw.Draw(mask).ellipse((0,0,diameter-1,diameter-1),fill=255)
    shadow = Image.new("RGBA", im.size)
    ImageDraw.Draw(shadow).ellipse((x+3, y+12, x+diameter+3, y+diameter+12), fill=(0, 0, 0, 70))
    im = Image.alpha_composite(im.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(16))).convert("RGB")
    im.paste(source,(x,y),mask)
    ImageDraw.Draw(im).ellipse((x,y,x+diameter-1,y+diameter-1),outline="white",width=8)
    return im


def verified_specs(rows):
    """Only source product names, never estimated shipping dimensions."""
    measures, capacities = set(), set()
    for row in rows:
        name = row["src_name"].upper().replace(",", ".")
        match = re.search(r"(\d+(?:\.\d+)?(?:\s*X\s*\d+(?:\.\d+)?){0,2})\s*CM\b",name)
        if match and not name.startswith("JERSEY"):
            measures.add(tuple(match[1].replace(" ","").split("X")))
        match = re.search(r"(\d+(?:\.\d+)?)\s*(ML|L)\b",name)
        if match:
            capacities.add(match[1].replace(".",",")+" "+match[2])
    # A shared folder with several physical sizes cannot have one set of arrows.
    return next(iter(measures)) if len(measures) == 1 else (), sorted(capacities)


def arrow(im, start, end, label, colours):
    if start == end or (start[0] != end[0] and start[1] != end[1]):
        raise ValueError("尺寸箭头必须水平或垂直且长度不为零；请检查商品边框位置。")
    overlay = Image.new("RGBA",im.size)
    draw = ImageDraw.Draw(overlay)
    dx,dy = end[0]-start[0],end[1]-start[1]
    length = math.hypot(dx,dy)
    ux,uy = dx/length,dy/length
    draw.line((start,end),fill=(*colours[0],255),width=5)
    for tip,sign in ((start,1),(end,-1)):
        a=(tip[0]+sign*ux*22-uy*12,tip[1]+sign*uy*22+ux*12)
        b=(tip[0]+sign*ux*22+uy*12,tip[1]+sign*uy*22-ux*12)
        draw.polygon([tip,a,b],fill=(*colours[0],255))
    face=font(48, 800)
    w=round(face.getlength(label))+36
    cx,cy=(start[0]+end[0])/2,(start[1]+end[1])/2
    cx = max(w/2+10, min(SIZE-w/2-10, cx))
    draw.rounded_rectangle((cx-w/2,cy-38,cx+w/2,cy+38),radius=14,fill="white")
    draw.text((cx,cy),label,font=face,fill=(*colours[0],255),anchor="mm")
    return Image.alpha_composite(im.convert("RGBA"),overlay).convert("RGB")


def measures_overlay(im, entry, colours, rows, bundle=False, demo=False):
    counts={int(row["pack_qty"]) for row in rows}
    if len(counts) != 1:
        raise ValueError("同一变体目录混用了不同件数；请拆分图片目录并修改 variantes.csv。")
    count=next(iter(counts))
    dims,caps=verified_specs(rows)
    subtitle = entry.get("subtitle", "")
    facts = []
    if not bundle and caps:
        facts.append(("Capacidad: " if len(caps) == 1 else "Capacidades: ")+" / ".join(caps))
    if not bundle and len(dims)>2:
        facts.append("Grosor: "+dims[2].replace(".", ",")+" cm")
    subtitle = " · ".join(facts) or subtitle
    base_photo = im
    im = text_block(im,entry["title"],colours,subtitle,entry.get("anchor", "auto"))
    if not bundle and dims:
        # Pure-colour measurement base: detect silhouette, or use reviewed
        # normalized product_box [left,top,right,bottom] in slot 06 config.
        if "product_box" in entry:
            box=tuple(round(v*SIZE) for v in entry["product_box"])
        else:
            background=Image.new("RGB",base_photo.size,base_photo.getpixel((0,0)))
            diff=ImageChops.difference(base_photo,background).convert("L").point(lambda p:255 if p>38 else 0)
            box=diff.getbbox() or (240,200,960,900)
        left,top,right,bottom=box
        _, _, _, title_height = heading_layout(entry["title"], subtitle, 1104)
        # A long strip has just one horizontal arrow above the product.
        long_strip = len(dims) == 1 or right-left > 2.5*(bottom-top)
        y = max(54+title_height+75, top-60) if long_strip else min(980, bottom+54)
        im=arrow(im,(max(60,left),y),(min(1140,right),y),dims[0].replace(".",",")+" cm",colours)
        if len(dims)>1:
            x=max(160,min(1000,left-50))
            im=arrow(im,(x,max(54+title_height+70,top)),(x,min(980,bottom)),dims[1].replace(".",",")+" cm",colours)
    return capsule(im, f"Contenido: {count} {'ud.' if count == 1 else 'uds.'}", colours)


def collage(paths, entry, colours):
    im=Image.new("RGB",(SIZE,SIZE),"white")
    if entry["layout"]=="1+3":
        boxes=[(0,0,794,1200),(806,0,1200,392),(806,404,1200,796),(806,808,1200,1200)]
    else:
        boxes=[(0,0,594,594),(606,0,1200,594),(0,606,594,1200),(606,606,1200,1200)]
    for path,scene,(x,y,r,b) in zip(paths,entry["scenes"],boxes):
        tile=ImageOps.fit(load_image(path),(r-x,b-y),Image.Resampling.LANCZOS)
        layer=Image.new("RGBA",tile.size)
        draw=ImageDraw.Draw(layer)
        fs=34
        lines=wrap(scene["title"],font(fs),r-x-116)
        height=max(84,len(lines)*(fs+10)+28)
        yy=b-y-height-18
        draw.rounded_rectangle((18,yy,r-x-18,b-y-18),radius=16,fill=(255,255,255,222))
        graphic=icon(scene["icon"],48,colours[0],stroke_width=3);layer.alpha_composite(graphic,(32,yy+(height-48)//2))
        for line in lines:
            draw.text((96,yy+14),line,font=font(fs),fill=(*colours[0],255));yy+=fs+10
        im.paste(Image.alpha_composite(tile.convert("RGBA"),layer).convert("RGB"),(x,y))
    return im


def render(path, slot, cfg, colours, rows, macro=None, demo=False):
    im=load_image(path)
    entry=cfg["slots"][slot]
    if slot=="02":
        return points_overlay(im,entry,colours,rows)
    if slot=="06":
        return measures_overlay(im,entry,colours,rows,bool(cfg.get("reuse_from")),demo)
    im = text_block(im,entry["title"],colours,entry.get("subtitle",""),entry.get("anchor","auto"))
    if slot=="03" and cfg.get("zoom"):
        im=zoom_circle(im,macro or path,colours,entry)
    if slot=="04" and spec_badge(rows):
        _, _, _, height = heading_layout(entry["title"], entry.get("subtitle", ""), 1104)
        im=capsule(im,spec_badge(rows),colours,(48,54+height+26))
    return im


def demo_product(path, side=None):
    """Reframe a white principal in a review copy, without altering outputs."""
    im=load_image(path, contain=True)
    background=Image.new("RGB",im.size,"white")
    diff=ImageChops.difference(im,background).convert("L").point(lambda p:255 if p>38 else 0)
    box=diff.getbbox() or (0,0,SIZE,SIZE)
    product=im.crop(box)
    if side:
        product=ImageOps.contain(product,(640,660),Image.Resampling.LANCZOS)
        left=48 if side=="right" else 512
        background.paste(product,(left+(640-product.width)//2,440+(660-product.height)//2))
    else:
        product=ImageOps.contain(product,(900,570),Image.Resampling.LANCZOS)
        background.paste(product,((SIZE-product.width)//2,420+(570-product.height)//2))
    return background


def make_demo(config, registry, rows, images_dir, mappings):
    # Read existing files for demonstration only; never write them back.
    sheet=Image.new("RGB",(1200,1200),"#f3f3f3")
    points_sheet=Image.new("RGB",(3600,1260),"#f3f3f3")
    for row_index,group in enumerate(list(registry)[:3]):
        hero=hero_variant(group,registry[group],images_dir)
        directory=output_dir(images_dir,group,hero)
        palette_source=directory/SLOTS["01"]
        colours=palette(load_image(palette_source))
        cfg=resolve_config(config,group,hero)
        keys={(m['art_id'],m.get('ean')) for m in mappings if m['group']==group and m['variante']==hero}
        matching=[r for r in rows if r['group']==group and any(r['art_id']==a and (not e or r['ean']==e) for a,e in keys)]
        base=Path(images_dir)/group/hero/"internal/base"
        if not base.exists():
            base=Path(images_dir)/group/"internal/base"
        for col_index,slot in enumerate(("03","04","05","06")):
            path=base/BASE_NAMES[slot]
            clean=path.is_file()
            if not clean:
                path=directory/SLOTS[slot]
            if not path.exists():
                continue
            if slot=="06" and not clean:
                # Old 06 includes baked-in diagonal arrows and captions.
                # Demonstrate the new axes on the principal's product pixels.
                tile=measures_overlay(demo_product(palette_source),cfg['slots']['06'],colours,matching)
            else:
                tile=render(path,slot,cfg,colours,matching,base/"macro.jpg" if (base/"macro.jpg").is_file() else None,demo=True)
            tile=tile.resize((294,294),Image.Resampling.LANCZOS)
            x,y=col_index*300+3,row_index*400+48
            sheet.paste(tile,(x,y))
            draw=ImageDraw.Draw(sheet)
            draw.text((x+8,row_index*400+10),f"{group} / {slot}",font=font(30),fill=colours[0])
        path=base/BASE_NAMES['02']
        if path.is_file():
            point_image=render(path,'02',cfg,colours,matching)
        else:
            point_image=points_overlay(demo_product(palette_source,cfg['slots']['02'].get('side','right')),cfg['slots']['02'],colours,matching)
        points_sheet.paste(point_image,(row_index*SIZE,60))
        ImageDraw.Draw(points_sheet).text((row_index*SIZE+48,12),f"{group} / 02",font=font(34),fill=colours[0])
    dest=Path(images_dir)/"_review/overlay_demo.jpg"
    save_jpg(sheet,dest)
    print(f"审阅拼图：{dest}")
    dest=Path(images_dir)/"_review/overlay_demo_02.jpg"
    save_jpg(points_sheet,dest)
    print(f"审阅拼图：{dest}")


def run(groups,config_path,images_dir,variantes,candidates,demo=False):
    config=json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    validate_config(config)
    registry=variant_folders(variantes)
    with Path(candidates).open(encoding="utf-8-sig",newline="") as handle:
        rows=list(csv.DictReader(handle))
    with Path(variantes).open(encoding="utf-8-sig",newline="") as handle:
        mappings=list(csv.DictReader(handle))
    missing=[]
    selected=list(dict.fromkeys(groups)) if groups else list(config)
    # A requested bundle refreshes its dependency first, then copies the exact
    # finished single-group hero files. No rerender with a bundle caption.
    expanded=[]
    scheduling=set()
    def schedule(group):
        if group in scheduling:
            raise ValueError(f"{group} 的 reuse_from 循环引用；请修改 overlays.json 的复用来源。")
        if group not in config:
            raise ValueError(f"叠字配置缺少 {group}；请补齐 overlays.json。")
        scheduling.add(group)
        source=resolve_config(config,group).get("reuse_from")
        if source and source not in expanded:
            schedule(source)
        if group not in expanded:
            expanded.append(group)
        scheduling.remove(group)
    for group in selected:
        schedule(group)
    for group in expanded:
        if group not in registry:
            missing.append(f"{group} 未登记变体：{variantes}")
            continue
        hero=hero_variant(group,registry[group],images_dir)
        principal=output_dir(images_dir,group,hero)/SLOTS["01"]
        colours=palette(load_image(principal)) if principal.exists() else None
        for variant in registry[group]:
            directory=output_dir(images_dir,group,variant)
            principal=directory/SLOTS["01"]
            if principal.exists():
                ensure_variant_image(directory)
                print(f"变体图：{group}/{variant}")
            else:
                missing.append(f"{group}/{variant}/variante 缺主图：{principal}")
            cfg=resolve_config(config,group,variant)
            root=Path(images_dir)/group/variant/"internal/base"
            if variant==hero and not root.exists():
                root=Path(images_dir)/group/"internal/base"
            keys={(m['art_id'],m.get('ean')) for m in mappings if m['group']==group and m['variante']==variant}
            matching=[r for r in rows if r['group']==group and any(r['art_id']==a and (not e or r['ean']==e) for a,e in keys)]
            if not matching:
                missing.append(f"{group}/{variant} 缺商品事实数据，已跳过叠字")
                continue
            for slot in list(SLOTS)[1:]:
                dest=directory/SLOTS[slot]
                if cfg.get("reuse_from") and slot in SHARED_SLOTS:
                    source=cfg["reuse_from"]
                    source_hero=hero_variant(source,registry[source],images_dir)
                    src=output_dir(images_dir,source,source_hero)/SLOTS[slot]
                    if src.exists():
                        dest.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copyfile(src,dest)
                        print(f"复用：{group}/{variant}/{slot} ← {source}/{source_hero}")
                    else:
                        missing.append(f"{group}/{variant}/{slot} 缺共用成品图：{src}")
                    continue
                paths=[root/f"07-{letter}.jpg" for letter in "abcd"] if slot=="07" else [root/BASE_NAMES[slot]]
                absent=[str(p) for p in paths if not p.is_file()]
                if absent:
                    missing.append(f"{group}/{variant}/{slot}: "+", ".join(absent))
                    continue
                # Each physical variant has its own product palette.
                colour=palette(load_image(principal)) if principal.is_file() else (colours or palette(load_image(paths[0])))
                macro=root/"macro.jpg"
                im=collage(paths,cfg["slots"][slot],colour) if slot=="07" else render(paths[0],slot,cfg,colour,matching,macro if macro.is_file() else None)
                save_jpg(im,dest)
                print(f"叠字：{group}/{variant}/{slot}")
    if demo:
        make_demo(config,registry,rows,images_dir,mappings)
    print(f"已跳过或缺少素材（{len(missing)} 项）：")
    for message in missing:
        print(f"  - {message}")
    return missing

