"""Shared image names and hero selection; GPSR never belongs to this layout."""
import csv
from pathlib import Path
from .common import component

ROOT = Path(__file__).resolve().parents[2]
SLOTS = {
    "01": "01-principal.jpg", "02": "02-puntos.jpg",
    "03": "03-detalle.jpg", "04": "04-uso.jpg",
    "05": "05-uso-alternativo.jpg", "06": "06-medidas-contenido.jpg",
    "07": "07-usos.jpg", "08": "08-modelo.jpg",
}
VARIANT_SLOT = "variante"
SHARED_SLOTS = ("03", "04", "05", "07", "08")


def variant_folders(path):
    groups = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            group, variant = row["group"], row["variante"]
            for value in (group, variant):
                component(value, '图片目录名')
            folders = groups.setdefault(group, [])
            if variant not in folders:
                folders.append(variant)
    return groups


def hero_variant(group, variants, images_dir):
    if not variants:
        raise ValueError(f"{group} 没有登记变体；请补齐 variantes.csv。")
    path = Path(images_dir) / group / "hero.txt"
    if not path.exists():
        return variants[0]
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if len(lines) != 1 or lines[0].strip() not in variants:
        raise ValueError(f"{path} 应只写一行已登记的变体名，可选 {variants}；请修改 hero.txt。")
    return lines[0].strip()


def output_dir(images_dir, group, variant):
    return Path(images_dir) / group / variant / "output/miravia-es/v01"


def display_image_path(path, slot):
    return Path(path).name == SLOTS.get(slot)
