"""安全读取旧脚本中的字面常量，不 import 或执行旧代码。"""
import ast
import copy
import html
import os
import re
import shutil
import subprocess
from pathlib import Path

from .common import Problem, inside, read_csv, read_json, require, write_json
from .workspace import batch_path, init, load_shop, new_batch, template_path


def constants(path):
    source = path.read_text('utf-8-sig')
    tree = ast.parse(source, filename=str(path))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try: values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError): pass
    return values, tree


def import_content(source):
    content = read_json(source / 'data/content.json')
    fill, fill_tree = constants(source / 'scripts/fill_template.py')
    gpsr, gpsr_tree = constants(source / 'scripts/gpsr_labels.py')
    jobs_path = source / 'scripts/seedream_jobs.py'
    jobs = constants(jobs_path)[0] if jobs_path.is_file() else {}
    for key, values in (('CATEGORIES', fill), ('NAMES', gpsr), ('GENERAL', gpsr)):
        require(key in values, f'旧脚本缺少 {key} 字面常量；请检查是否选错旧项目。')
    colour_groups = set()
    for fn in fill_tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name == 'seller_sku':
            for node in ast.walk(fn):
                if isinstance(node, ast.Set):
                    try: colour_groups.update(ast.literal_eval(node))
                    except (ValueError, TypeError): pass
    shortened = {}
    for fn in gpsr_tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name == 'warning_items':
            for node in ast.walk(fn):
                if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare): continue
                test = node.test
                if not isinstance(test.left, ast.Name) or test.left.id != 'base': continue
                if not test.comparators or not isinstance(test.comparators[0], ast.Constant): continue
                for child in node.body:
                    if isinstance(child, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'texts' for t in child.targets):
                        try: shortened[test.comparators[0].value] = ast.literal_eval(child.value)
                        except (ValueError, TypeError): pass
    # Extract the old dimension suffix exception as data as well.
    suffixes = {}
    for fn in gpsr_tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name == 'medidas':
            for node in ast.walk(fn):
                if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
                    test = node.test
                    if test.comparators and isinstance(test.comparators[0], ast.Constant):
                        for child in node.body:
                            if isinstance(child, ast.AugAssign) and isinstance(child.target, ast.Name) and child.target.id == 'result' and isinstance(child.value, ast.Constant):
                                suffixes[test.comparators[0].value] = child.value.value
    for group, category in fill['CATEGORIES'].items():
        if group not in content: continue
        item = content[group]
        item['category'] = category
        item['gpsr_name'] = gpsr['NAMES'].get(group, '')
        source_warnings = [html.unescape(re.sub(r'<[^>]+>', '', s)).strip() for s in re.findall(r'<li>(.*?)</li>', item.get('warning_text', ''), re.S)]
        item['gpsr_safety'] = copy.deepcopy(shortened.get(group, gpsr['GENERAL'].get(group, source_warnings)))
        item['sku_include_ean'] = group in colour_groups
        if group in suffixes: item['gpsr_measure_suffix'] = suffixes[group]
    for group, item in content.items():
        if group in jobs.get('PRODUCTS', {}):
            item['image_description'] = jobs['PRODUCTS'][group]
        if group in jobs.get('SCENES07', {}):
            item['image_scenes07'] = copy.deepcopy(jobs['SCENES07'][group])
    return content


def run(ws, source, name):
    source = Path(source).resolve()
    require(source.is_dir() and (source / 'data').is_dir(), f'{source} 不是旧项目；请选择含 data/ 和 scripts/ 的目录。')
    require(not Path(ws).resolve().is_relative_to(source), '工作区不能放在旧项目里面；请用 --ws 指定其他位置。')
    require(not batch_path(ws, name, False).exists(), f'批次 {name} 已存在；为防止覆盖，请换一个批次名。')
    content = import_content(source)
    image_source = source / 'images'
    require(image_source.is_dir(), f'旧项目图片目录不存在：{image_source}；请检查路径。')
    init(ws)
    shop = load_shop(ws)
    template = template_path(ws, shop, False)
    warnings = []
    for group, item in content.items():
        if not group.endswith('B') and not item.get('gpsr_safety'):
            warnings.append(f'{group} 在旧资料中没有 GPSR 通用安全提示；已保留为空，生成标签前请补齐 gpsr_safety。')
    if not template.exists():
        old_template = source / 'template' / shop['template']
        require(old_template.is_file(), f'旧项目也没有配置模板 {old_template}；请在工作区放入模板并修改 shop.json。')
        template.parent.mkdir(parents=True, exist_ok=True)
        with template.open('xb') as f: f.write(old_template.read_bytes())
    batch = new_batch(ws, name)
    for file in sorted((source / 'data').iterdir()):
        if file.is_file() and file.suffix.lower() in ('.csv', '.json', '.txt') and file.name not in ('content.json', 'fabricantes.json'):
            shutil.copy2(file, inside(batch, batch / file.name))
    write_json(batch / 'content.json', content)
    makers_path = source / 'data/fabricantes.json'
    if makers_path.exists():
        for supplier, maker in read_json(makers_path).items():
            if supplier not in shop['suppliers'] or any(shop['suppliers'][supplier].get(k) != v for k, v in maker.items()):
                warnings.append(f'旧商家 {supplier} 的下拉资料与 shop.json 不同；已保留现有配置，请核对。')
    images = batch / 'images'
    images.rmdir()  # Only the just-created empty directory, never recursive.
    if os.name == 'nt':
        # Passing a literal through -LiteralPath avoids cmd.exe path interpolation.
        quote = lambda s: "'" + str(s).replace("'", "''") + "'"
        command = f"$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path {quote(images)} -Target {quote(image_source)} | Out-Null"
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], check=True, capture_output=True)
    else:
        images.symlink_to(image_source, target_is_directory=True)
    return dict(batch=str(batch), warnings=warnings, message='旧数据已导入，图片已建立只读使用的目录联接；未复制商品图片。')
