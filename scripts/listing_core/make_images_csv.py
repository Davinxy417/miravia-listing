"""Build hosted image URLs from image_files.csv; this does not upload files."""
import argparse
import csv
import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

from .image_layout import SLOTS, VARIANT_SLOT, hero_variant, variant_folders

ROOT = Path(__file__).resolve().parents[2]


def make_images_csv(base_url, source, out, variantes, images_dir):
    base = urlsplit(base_url)
    if (base.scheme not in ("http", "https") or not base.netloc or base.query or base.fragment
            or re.search(r"\s", base_url)):
        raise ValueError("--base-url 必须是 HTTP(S) 网址前缀，不能含空格、查询参数或 # 片段；请复制图床根网址。")
    prefix = base_url.rstrip("/") + "/"
    rows, seen = [], {}
    groups = variant_folders(variantes)
    heroes = {g: hero_variant(g, vs, images_dir) for g, vs in groups.items()}
    with Path(source).open(encoding="utf-8-sig", newline="") as handle:
        for item in csv.DictReader(handle):
            group, variante, slot = item["group"], item["variante"], item["slot"]
            if group not in groups or variante not in groups[group]:
                continue
            if slot != VARIANT_SLOT:
                if not re.fullmatch(r"0?[1-8]", slot):
                    continue
                slot = f"{int(slot):02d}"
                if variante != heroes[group]:
                    continue
            local_path = item["local_path"].replace("\\", "/")
            path = PurePosixPath(local_path)
            if (not local_path or path.is_absolute() or ".." in path.parts or ":" in local_path
                    or not local_path.lower().endswith(".jpg")):
                raise ValueError(f"图片路径应是 images/ 下的相对 JPG 路径：{local_path!r}；请重新收集图片。")
            name = "variante.jpg" if slot == VARIANT_SLOT else SLOTS[slot]
            if path.as_posix() != f"{group}/{variante}/output/miravia-es/v01/{name}":
                continue  # GPSR, obsolete names and misplaced files never enter the manifest.
            key = (group, variante, slot)
            url = prefix + quote(path.as_posix(), safe="/")
            if key in seen:
                if seen[key] != url:
                    raise ValueError(f"图片清单 {key} 有冲突；请检查并保留正确的一条。")
                continue
            seen[key] = url
            rows.append(dict(group=group, variante=variante, slot=slot, url=url))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("group", "variante", "slot", "url"))
        writer.writeheader()
        writer.writerows(rows)
    return rows

