"""文件格式、可操作的错误及工作区内写入保护。"""
import csv
import json
import os
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CANDIDATE_FIELDS = 'group,shop,art_id,ean,unit_ean,src_name,var1_name,var1_value,var2_name,var2_value,pack_qty,unit_cost_ex_iva,img_hash,weight_kg,len_cm,wid_cm,hei_cm,market_low,market_high,notes'.split(',')
PRICE_FIELDS = 'real_cost,ship_est,billable_kg,price,original_price,profit_no_coupon,profit_with_coupon,min_safe_price,max_discount_pct,ean_valid,vs_market'.split(',')
CSV_FIELDS = {
    'candidates.csv': CANDIDATE_FIELDS,
    'priced.csv': CANDIDATE_FIELDS + PRICE_FIELDS,
    'variantes.csv': ['group', 'art_id', 'ean', 'variante'],
    'image_files.csv': ['group', 'variante', 'slot', 'local_path'],
    'images.csv': ['group', 'variante', 'slot', 'url'],
}


class Problem(ValueError):
    def __init__(self, errors, warnings=()):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        self.warnings = list(warnings)
        super().__init__('；'.join(self.errors))


def require(condition, message):
    if not condition:
        raise Problem(message)


def read_json(path):
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except json.JSONDecodeError as exc:
        raise Problem(f'{path} 第 {exc.lineno} 行 JSON 格式不对：{exc.msg}。请修正后重试。') from exc


def read_csv(path, fields=None):
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        required = fields if fields is not None else CSV_FIELDS.get(path.name, [])
        missing = set(required) - set(reader.fieldnames or [])
        require(not missing, f'{path} 缺少表头 {", ".join(sorted(missing))}；请补齐表头。')
        rows = list(reader)
    for n, row in enumerate(rows, 2):
        require(None not in row and all(v is not None for v in row.values()),
                f'{path} 第 {n} 行列数不对；请检查逗号和引号。')
    return rows


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        pending = Path(f.name)
        f.write(data)
    try:
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def write_json(path, value):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def write_csv(path, rows, fields=None):
    import io
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_bytes(path, stream.getvalue().encode('utf-8-sig'))


def component(value, label='名称'):
    require(isinstance(value, str) and bool(value) and value.strip() == value
            and value not in ('.', '..') and not any(c in value for c in '<>:"/\\|?*')
            and not any(ord(c) < 32 for c in value) and not value.endswith('.')
            and value.split('.')[0].upper() not in {'CON', 'PRN', 'AUX', 'NUL', *[f'{p}{i}' for p in ('COM', 'LPT') for i in range(1, 10)]},
            f'{label} {value!r} 不能作为文件夹名；请用中文、字母、数字或短横线。')
    return value


def inside(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    require(path.is_relative_to(root), f'写入位置 {path} 指向工作区外；请换成工作区内的普通目录。')
    return path


def guard_images(batch):
    """Imported junctions are read-only. Also reject nested links before rendering."""
    import stat
    root = Path(batch) / 'images'
    inside(batch, root)
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            p = Path(directory) / name
            attrs = getattr(p.lstat(), 'st_file_attributes', 0)
            require(not (p.is_symlink() or attrs & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)),
                    f'图片目录含联接或符号链接 {p}；为保护原图，请先改用本批次的普通图片目录。')
