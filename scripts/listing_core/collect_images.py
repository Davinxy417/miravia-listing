"""Collect a hero gallery (01..08) and one variante.jpg per registered variant."""
import argparse
import csv
import sys
from pathlib import Path

from .image_layout import SLOTS, VARIANT_SLOT, hero_variant, output_dir, variant_folders
from .overlay import ensure_variant_image

ROOT = Path(__file__).resolve().parents[2]


def collect(images_dir, out, variantes, readonly=False, warnings=None):
    warnings = [] if warnings is None else warnings
    images_dir, out = Path(images_dir), Path(out)
    groups = variant_folders(variantes)
    expected = {(g, v) for g, vs in groups.items() for v in vs}
    files = {}
    # Iterate only the registry. Ignore obsolete directories, GPSR and legacy names.
    for group, variants in groups.items():
        hero = hero_variant(group, variants, images_dir)
        for variante in variants:
            directory = output_dir(images_dir, group, variante)
            # New principals may arrive between image-production tasks and the
            # four-command upload pipeline. Keep every available variant usable.
            if not readonly:
                ensure_variant_image(directory)
            names = {VARIANT_SLOT: "variante.jpg"}
            if variante == hero:
                names.update(SLOTS)
            for slot, name in names.items():
                path = directory / name
                if path.is_file():
                    files[(group, variante, slot)] = path.relative_to(images_dir).as_posix()
    rows = [dict(group=g, variante=v, slot=s, local_path=path)
            for (g, v, s), path in sorted(files.items())]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("group", "variante", "slot", "local_path"))
        writer.writeheader()
        writer.writerows(rows)
    for group, variante in sorted(expected):
        if not (output_dir(images_dir, group, variante) / SLOTS["01"]).is_file():
            warnings.append(f"{group}/{variante} 缺主图 01；请补齐后重新收集图片。")
        if (group, variante, VARIANT_SLOT) not in files:
            warnings.append(f"{group}/{variante} 缺 variante.jpg；请补齐变体图。")
    return rows

