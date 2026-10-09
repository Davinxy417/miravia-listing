"""批次图片规划、安装和审阅；复用现有叠字/尺寸/色彩导出逻辑。"""
import hashlib
import io
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .common import Problem, atomic_bytes, component, guard_images, inside, read_csv, read_json, require, write_json
from .content import number, resolve_content
from .image_layout import SHARED_SLOTS, SLOTS, hero_variant, output_dir
from .image_prompts import make_prompt
from .images import read_variantes, variant_key
from . import overlay

MODES = ('model-text', 'base-overlay')
STATUS_LABELS = dict(missing='缺', existing='已有', redo='要重做')
METHOD_LABELS = {'model-text': '模型出带字图', 'base-overlay': '无字底图 + 脚本叠字',
                 'model': '模型出无字图', 'script': '无字底图 + 脚本画尺寸/内容',
                 'derive': '由本变体 01 派生', 'copy': '复制主组主推成品'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None


def review_data(batch):
    path = batch / 'image_review.json'
    data = read_json(path) if path.exists() else {'version': 1, 'reviews': {}}
    require(isinstance(data, dict) and isinstance(data.get('reviews'), dict),
            'image_review.json 格式不对；需要 reviews 对象，请修正后重试。')
    for jid, item in data['reviews'].items():
        require(isinstance(item, dict) and item.get('result') in ('ok', 'redo'),
                f'image_review.json 的 {jid} 无效；result 应为 ok 或 redo。')
    return data


def context(batch):
    rows = read_csv(batch / 'candidates.csv')
    require(rows, 'candidates.csv 没有商品；请先 build 或导入批次。')
    mappings = read_variantes(batch / 'variantes.csv')
    registry, matching = {}, {}
    for row in rows:
        key = variant_key(row)
        require(key in mappings, f'{key} 没有变体映射；请补齐 variantes.csv。')
        group, variant = row['group'], mappings[key]
        if variant not in registry.setdefault(group, []): registry[group].append(variant)
        matching.setdefault((group, variant), []).append(row)
    contents, errors = resolve_content(read_json(batch / 'content.json'), registry)
    if errors: raise Problem(errors)
    config = read_json(batch / 'overlays.json')
    require(isinstance(config, dict), 'overlays.json 应是按组填写的对象。')
    heroes = {g: hero_variant(g, vs, batch / 'images') for g, vs in registry.items()}
    return registry, matching, contents, config, heroes


def cfg_for(config, group, variant):
    # New B groups may omit an entire overlay entry; quantities remain data-driven.
    if group not in config and group.endswith('B') and group[:-1] in config:
        config = dict(config, **{group: {'inherits': group[:-1]}})
    require(group in config, f'overlays.json 缺少 {group}；请补齐各位置文字。')
    try: return overlay.resolve_config(config, group, variant)
    except (KeyError, ValueError) as exc: raise Problem(f'overlays.json 的 {group}：{exc}；请修正继承。') from exc


def raw_latest(batch, group, variant, slot):
    directory = batch / 'images' / group / variant / 'internal/raw'
    files = [p for p in directory.glob(f'{slot}*') if p.is_file()
             and p.suffix.lower() in ('.png', '.jpg', '.jpeg')
             and re.match(rf'^{re.escape(slot)}(?:[._-]|$)', p.stem)]
    return max(files, key=lambda p: (p.stat().st_mtime_ns, p.name)) if files else None


def rel(batch, path):
    # Preserve logical junction paths so the same plan works after moving a workspace.
    return str(Path(path).absolute().relative_to(batch.absolute())).replace('\\', '/')


def read_path(batch, value):
    require(isinstance(value, str) and value and not Path(value).is_absolute()
            and '\\' not in value and '..' not in Path(value).parts and ':' not in value,
            f'图片资料路径 {value!r} 不正确；请用相对批次路径，不能有 .. 或绝对路径。')
    path = batch / value
    # Imported images may be read through a root junction, but not arbitrary links.
    root = (batch / 'images').resolve() if Path(value).parts[0] == 'images' else batch.resolve()
    require(path.resolve().is_relative_to(root), f'图片资料路径 {value} 越过了目录范围；请修正。')
    return path


def stock_refs(batch, jid):
    path = batch / 'stock_fotos.csv'
    refs = []
    if path.is_file():
        for row in read_csv(path, ['archivo', 'fuente', 'url', 'autor', 'licencia', 'usado_en']):
            if jid not in row['usado_en'].replace(';', ' ').replace(',', ' ').split(): continue
            require(row['fuente'].lower() in ('pexels', 'unsplash') and row['url'] and row['autor'] and row['licencia'],
                    f'stock_fotos.csv 的 {jid} 缺少 Pexels/Unsplash 来源资料。')
            read_path(batch, row['archivo'])
            refs.append(row['archivo'])
    return refs


def make_plan(batch, mode='model-text'):
    require(mode in MODES, '出图模式请用 model-text 或 base-overlay。')
    registry, matching, contents, config, heroes = context(batch)
    review = review_data(batch)['reviews']
    jobs, warnings = [], []
    for group in sorted(registry, key=lambda g: (g.removesuffix('B'), g.endswith('B'))):
        base = group[:-1] if group.endswith('B') else group
        for variant in registry[group]:
            rows = matching[group, variant]
            quantities = {number(r['pack_qty'], f'{group}/{variant} 件数', integer=True) for r in rows}
            require(len(quantities) == 1, f'{group}/{variant} 混用不同件数；请拆分变体目录。')
            qty = next(iter(quantities))
            cfg = cfg_for(config, group, variant)
            item = contents[group]
            description = item.get('image_description') or '；'.join(dict.fromkeys(r['src_name'] for r in rows))
            scenes = item.get('image_scenes07', [])
            require(isinstance(description, str) and description.strip(), f'{group} 请补齐 image_description 或商品原名。')
            require(isinstance(scenes, list) and (not scenes or len(scenes) == 4) and all(isinstance(s, str) and s.strip() for s in scenes),
                    f'{group} 的 image_scenes07 应为空或四个场景描述。')
            slots = [*SLOTS, 'variante'] if variant == heroes[group] else ['01', 'variante']
            for slot in slots:
                jid = f'{group}/{variant}/{slot}'
                output = output_dir(batch / 'images', group, variant) / ('variante.jpg' if slot == 'variante' else SLOTS[slot])
                source_id, refs, blockers = None, [], []
                entry = cfg.get('slots', {}).get(slot, {})
                if slot == 'variante':
                    method, source_id = 'derive', f'{group}/{variant}/01'
                elif base != group and slot in SHARED_SLOTS:
                    require(base in heroes, f'{group} 缺少对应主组 {base}；不能复用其他商品。')
                    method, source_id = 'copy', f'{base}/{heroes[base]}/{slot}'
                else:
                    method = 'model' if slot == '01' else 'script' if slot == '06' else mode
                    if slot not in ('01',) and not entry:
                        blockers.append(f'overlays.json 缺 {group}/{slot} 文案')
                    principal = output_dir(batch / 'images', group, variant) / SLOTS['01']
                    refs = [rel(batch, principal)] if slot != '01' else []
                    # Actual source for this variant, not another colour's hero.
                    for row in rows:
                        src = batch / 'src' / f"{row['shop']}-{row['art_id']}.jpg"
                        if src.is_file(): refs.append(rel(batch, src))
                    if slot == '01' and not refs and principal.exists(): refs.append(rel(batch, principal))
                    root = batch / 'images' / group / variant / 'internal/base'
                    if variant == heroes[group] and not root.is_dir(): root = batch / 'images' / group / 'internal/base'
                    if slot == '07':
                        bases = [root / f'07-{c}.jpg' for c in 'abcd']
                        if all(p.is_file() for p in bases): refs += [rel(batch, p) for p in bases]
                        elif not scenes: blockers.append('07 缺四格场景描述或四张已核实无字场景底图')
                    else:
                        clean = root / overlay.BASE_NAMES.get(slot, SLOTS[slot])
                        if clean.is_file(): refs.append(rel(batch, clean))
                    if slot == '03' and cfg.get('zoom') and (root / 'macro.jpg').is_file(): refs.append(rel(batch, root / 'macro.jpg'))
                    if slot in ('04', '05', '08'):
                        people = stock_refs(batch, jid)
                        refs += people
                        if not people: blockers.append('请先选 Pexels/Unsplash 真人素材并按此 id 记录 stock_fotos.csv；旧底图来源须人工核对')
                refs = list(dict.fromkeys(refs))
                missing_refs = [r for r in refs if not read_path(batch, r).is_file()]
                if not refs and method not in ('copy', 'derive'): blockers.append('缺实际参考图；先补本变体 src 原图/主图')
                if missing_refs: blockers.append('参考图尚缺：' + '、'.join(missing_refs))
                record = review.get(jid, {})
                sha = digest(output)
                reviewed = record.get('result') == 'ok' and sha is not None and record.get('sha256') == sha
                state = 'redo' if record.get('result') == 'redo' else 'existing' if sha else 'missing'
                reason = record.get('note', '') if state == 'redo' else ''
                raw = raw_latest(batch, group, variant, slot) if method not in ('copy', 'derive') else None
                prompt = '' if method in ('copy', 'derive') else make_prompt(slot, description, variant, qty, entry,
                              'base-overlay' if method in ('model', 'script', 'base-overlay') else mode,
                              scenes=scenes, zoom=cfg.get('zoom', False), note=reason)
                if slot == '06':
                    dims, capacities = overlay.verified_specs(rows)
                    prompt += ' 脚本事实（禁止模型画字/数字）：' + str({'dims_cm': [] if base != group else dims,
                                                                       'capacities': [] if base != group else capacities, 'pack_qty': qty})
                jobs.append(dict(id=jid, group=group, variant=variant, slot=slot, output=rel(batch, output),
                                 raw_dir=f'images/{group}/{variant}/internal/raw', raw=rel(batch, raw) if raw else None,
                                 refs=refs, method=method, mode=mode, source_id=source_id, prompt=prompt,
                                 status=state, reason=reason, reviewed=reviewed, blockers=blockers, pack_qty=qty))
    by_id = {j['id']: j for j in jobs}
    for job in jobs:
        if job['source_id']:
            source = by_id[job['source_id']]
            job['refs'] = [source['output']]
            if source['status'] == 'redo' or (Path(batch / source['output']).is_file() and
                    Path(batch / job['output']).is_file() and (batch / source['output']).stat().st_mtime_ns > (batch / job['output']).stat().st_mtime_ns):
                job.update(status='redo', reason='来源图已重做或需重做：' + source['id'], reviewed=False)
    summary = {}
    for j in jobs:
        counts = summary.setdefault(j['group'], dict(missing=0, existing=0, redo=0, reviewed=0, pending=0))
        counts[j['status']] += 1
        counts['reviewed' if j['reviewed'] else 'pending'] += 1
    return dict(version=1, mode=mode, jobs=jobs, summary=summary, warnings=warnings)


def plan(batch, mode='model-text'):
    data = make_plan(batch, mode)
    lines = ['# 出图清单', '', f'模式：{mode}。所有路径相对本批次：{batch}。', '',
             '实际附上所列参考文件；先完成各变体 01，核对结构/原图颜色/数量，再扩展主推款。',
             '每张最多初次生成＋一次修正；两次仍失败记问题。不要凭空补材质、规格、认证或配件。',
             '带字图只用 prompt 中逐字文字，出完逐字校对；06 只生成无字底图，数字由脚本画。',
             '原始生成图存到本项 raw_dir/<槽位>-v01.png（修正用 v02）；不要直接覆盖成品。',
             '运行 images-finish 后检查 1200×1200 sRGB JPG <3145728 bytes，使用 images-sheet / images-review 审阅。',
             '真人素材只用 Pexels/Unsplash，人物身份保持，来源记 stock_fotos.csv：archivo,fuente,url,autor,licencia,usado_en；usado_en 用本清单完整 id。',
             'GPSR 平面标签由 gpsr 命令画，打印贴货；贴标效果图单独存，不伪称真实拍照，不进入展示图。非电器不加 WEEE/CE。', '',
             '|组|缺|已有|要重做|审过|未审|', '|---|---:|---:|---:|---:|---:|']
    for g, c in data['summary'].items(): lines.append(f"|{g}|{c['missing']}|{c['existing']}|{c['redo']}|{c['reviewed']}|{c['pending']}|")
    for j in data['jobs']:
        lines += ['', f"## {j['id']} — {STATUS_LABELS[j['status']]}",
                  f"做法：{METHOD_LABELS[j['method']]}；{'审过' if j['reviewed'] else '未审'}；原因：{j['reason'] or '无'}。",
                  f"成品：`{j['output']}`", f"原始图目录：`{j['raw_dir']}`",
                  '参考图：' + ('、'.join(f'`{r}`' for r in j['refs']) or '缺，请补齐'),
                  '已有原始图：' + (j['raw'] or '无'), '待补/核对：' + ('；'.join(j['blockers']) or '无')]
        if j['source_id']: lines.append('依赖：' + j['source_id'] + '，由 images-finish 派生/复制，不调用模型。')
        else: lines += ['', '```text', j['prompt'], '```']
    for name in ('image_plan.json', 'image_plan.md'): inside(batch, batch / name)
    write_json(batch / 'image_plan.json', data)
    atomic_bytes(batch / 'image_plan.md', ('\n'.join(lines) + '\n').encode('utf-8'))
    return dict(count=len(data['jobs']), summary=data['summary'], output=str(batch / 'image_plan.md'),
                message='图片清单已生成；已有不代表人工审阅通过。', warnings=data['warnings'])


def select(jobs, groups=None, only=None, pending=False):
    known = {j['id'] for j in jobs}
    require(not only or set(only) <= known, '所选 id 不在当前批次清单：' + '、'.join(sorted(set(only or []) - known)))
    require(not groups or set(groups) <= {j['group'] for j in jobs}, '所选组不在当前批次；请检查 --group。')
    return [j for j in jobs if (not groups or j['group'] in groups) and (not only or j['id'] in only)
            and (not pending or not j['reviewed'])]


def plan_mode(batch):
    path = batch / 'image_plan.json'
    return read_json(path).get('mode', 'model-text') if path.exists() else 'model-text'


def backup(batch, target):
    if not target.exists(): return
    directory = target.parents[3] / 'internal/old'
    inside(batch, directory)
    directory.mkdir(parents=True, exist_ok=True)
    n = 1
    while (directory / f'{target.stem}-v{n:03d}{target.suffix}').exists(): n += 1
    shutil.copy2(target, directory / f'{target.stem}-v{n:03d}{target.suffix}')


def install_bytes(batch, target, blob):
    inside(batch, target)
    if target.is_file() and target.read_bytes() == blob: return False
    backup(batch, target)
    atomic_bytes(target, blob)
    return True


def finish(batch, groups=None, only=None):
    guard_images(batch)  # Reject before any mkdir/write, including nested junctions.
    data = make_plan(batch, plan_mode(batch))
    chosen = select(data['jobs'], groups, only)
    registry, matching, _, config, heroes = context(batch)
    by_id = {j['id']: j for j in data['jobs']}
    wanted = {j['id'] for j in chosen}
    def depend(j):
        if j['source_id'] and j['source_id'] not in wanted:
            wanted.add(j['source_id']); depend(by_id[j['source_id']])
    for j in chosen: depend(j)
    manifest_path = batch / 'images/internal/finish.json'
    inside(batch, manifest_path)
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    installed, skipped, warnings = [], [], []
    def sync_shared(job, blob):
        group, slot = job['group'], job['slot']
        dest_group = group if group.endswith('B') else group + 'B'
        if slot in SHARED_SLOTS and dest_group in registry:
            for v in registry[dest_group]:
                dst = output_dir(batch / 'images', dest_group, v) / SLOTS[slot]
                install_bytes(batch, dst, blob)
    for job in data['jobs']:
        if job['id'] not in wanted: continue
        jid, slot = job['id'], job['slot']
        group, variant = job['group'], job['variant']
        target = batch / job['output']
        cfg = cfg_for(config, group, variant)
        rows = matching[group, variant]
        source = batch / by_id[job['source_id']]['output'] if job['source_id'] else raw_latest(batch, group, variant, slot)
        base_tiles = None
        if source is None:
            root = batch / 'images' / group / variant / 'internal/base'
            if variant == heroes[group] and not root.exists(): root = batch / 'images' / group / 'internal/base'
            candidate = root / overlay.BASE_NAMES.get(slot, SLOTS.get(slot, 'variante.jpg'))
            if slot == '06' or job['method'] == 'base-overlay': source = candidate if candidate.is_file() else None
            if slot == '07' and job['method'] == 'base-overlay':
                tiles = [root / f'07-{c}.jpg' for c in 'abcd']
                if all(p.is_file() for p in tiles): base_tiles, source = tiles, tiles[0]
        if source is None or not source.is_file():
            if not target.is_file(): warnings.append(f'{jid} 缺原始图或来源成品；请按清单补齐后重跑 images-finish。')
            else: sync_shared(job, target.read_bytes())
            skipped.append(jid); continue
        signature = hashlib.sha256((str([digest(p) for p in base_tiles] if base_tiles else digest(source)) + job['prompt'] + str(cfg) + str(rows)).encode()).hexdigest()
        if manifest.get(jid) == {'input': signature, 'output': digest(target)}:
            sync_shared(job, target.read_bytes())
            skipped.append(jid); continue
        if job['method'] == 'copy': blob = source.read_bytes()
        else:
            im = overlay.load_image(source, contain=True)
            if slot == '06':
                im = overlay.measures_overlay(im, cfg['slots']['06'], overlay.palette(im), rows, group.endswith('B'))
            elif job['method'] == 'base-overlay':
                if slot == '07':
                    # A raw 07 is already a four-cell *unlettered* image; label its four cells.
                    boxes = [(0,0,794,1200),(806,0,1200,392),(806,404,1200,796),(806,808,1200,1200)] if cfg['slots']['07'].get('layout') == '1+3' else [(0,0,594,594),(606,0,1200,594),(0,606,594,1200),(606,606,1200,1200)]
                    # collage() accepts file paths; keep extracted tiles internal, never as final photos.
                    paths = base_tiles or []
                    if not base_tiles:
                        for i, box in enumerate(boxes):
                            p = batch / 'images' / group / variant / 'internal/work' / f'07-tile-{i}.png'
                            inside(batch, p); p.parent.mkdir(parents=True, exist_ok=True)
                            im.crop(box).save(p); paths.append(p)
                    im = overlay.collage(paths, cfg['slots']['07'], overlay.palette(im))
                else:
                    im = overlay.render(source, slot, cfg, overlay.palette(im), rows)
            # Reuse compression and ICC implementation but install atomically with backup.
            stream = io.BytesIO()
            for quality in (94, 90, 85, 80, 75, 65, 50):
                stream.seek(0); stream.truncate()
                im.convert('RGB').save(stream, 'JPEG', quality=quality, optimize=True, icc_profile=overlay.PROFILE)
                if stream.tell() < overlay.MAX_BYTES: break
            require(stream.tell() < overlay.MAX_BYTES, f'{jid} 压缩后仍超过 3 MiB；请简化底图。')
            blob = stream.getvalue()
        changed = install_bytes(batch, target, blob)
        manifest[jid] = dict(input=signature, output=digest(target))
        (installed if changed else skipped).append(jid)
        # Legacy contract: shared finished slots identical in every registered B variant.
        sync_shared(job, blob)
    write_json(manifest_path, manifest)
    return dict(count=len(installed), installed=installed, skipped=skipped, warnings=warnings,
                message='图片整理完成；新成品仍须看图并逐字校对，旧成品备份在 internal/old/。')


def sheet(batch, name='review', groups=None, only=None, pending=False):
    component(name, '审阅拼图名')
    name = name[:-4] if name.lower().endswith('.jpg') else name
    component(name, '审阅拼图名')
    jobs = select(make_plan(batch, plan_mode(batch))['jobs'], groups, only, pending)
    require(jobs, '没有符合筛选条件的图片；请调整 --group/--only/--pending。')
    # Group begins on a fresh row, labels never rely on image filenames alone.
    rows = []
    for group in dict.fromkeys(j['group'] for j in jobs):
        group_jobs = [j for j in jobs if j['group'] == group]
        rows.extend(group_jobs[i:i+3] for i in range(0, len(group_jobs), 3))
    cell = 320
    pages = [rows[i:i+18] for i in range(0, len(rows), 18)]
    outputs = []
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    face = ImageFont.truetype(str(font_path), 14) if font_path.is_file() else overlay.font(30)
    def caption_lines(value):
        lines, current = [], ''
        for char in value:
            if face.getlength(current+char) > cell-12: lines.append(current); current = ''
            current += char
        return lines + [current]
    line_height = 36 if not font_path.is_file() else 18
    label = max(68, max(len(caption_lines(j['id'])) for j in jobs)*line_height + line_height+10)
    for page, grid in enumerate(pages, 1):
        im = Image.new('RGB', (3*cell, len(grid)*(cell+label)), 'white')
        draw = ImageDraw.Draw(im)
        for row, entries in enumerate(grid):
            for col, j in enumerate(entries):
                x, y = col*cell, row*(cell+label)
                path = batch / j['output']
                if not path.is_file() and j['raw']: path = batch / j['raw']
                if path.is_file():
                    with Image.open(path) as source: tile = ImageOps.contain(ImageOps.exif_transpose(source).convert('RGB'), (cell,cell))
                    im.paste(tile, (x+(cell-tile.width)//2, y+(cell-tile.height)//2))
                else: draw.text((x+10, y+145), '缺图', fill='red', font=face)
                for n, line in enumerate(caption_lines(j['id'])):
                    draw.text((x+6,y+cell+2+n*line_height), line, fill='black', font=face)
                draw.text((x+6,y+cell+label-line_height-3), STATUS_LABELS[j['status']] + (' / 审过' if j['reviewed'] else ' / 未审'), fill='black', font=face)
        target = batch / 'review' / f"{name}{'-'+str(page) if len(pages)>1 else ''}.jpg"
        inside(batch, target)
        stream = io.BytesIO(); im.save(stream, 'JPEG', quality=88, icc_profile=overlay.PROFILE)
        atomic_bytes(target, stream.getvalue()); outputs.append(str(target))
    return dict(count=len(jobs), output=outputs[0], outputs=outputs, message='审阅拼图已生成；缺图保留空格和状态。')


def review(batch, ok=None, redo=None, note=''):
    ok, redo = ok or [], redo or []
    require(ok or redo, '请用 --ok 或 --redo 指定完整 id。')
    require(not set(ok) & set(redo), '同一张图片不能同时通过和重做；请拆成两次决定。')
    require(not redo or note.strip(), '标记重做需要 --note 写明原因，例如“颜色偏了”。')
    jobs = make_plan(batch, plan_mode(batch))['jobs']
    selected = select(jobs, only=ok + redo)
    records = review_data(batch)
    for j in selected:
        path = batch / j['output']
        require(j['id'] not in ok or path.is_file(), f"{j['id']} 缺成品；请先 images-finish，再记录通过。")
    inside(batch, batch / 'image_review.json')
    for j in selected:
        records['reviews'][j['id']] = dict(result='ok' if j['id'] in ok else 'redo',
                                          note='' if j['id'] in ok else note.strip(),
                                          sha256=digest(batch / j['output']), at=datetime.now(timezone.utc).isoformat())
    write_json(batch / 'image_review.json', records)
    return dict(count=len(selected), output=str(batch / 'image_review.json'), message='审阅结果已记录；成品变化后原通过记录自动失效。')


def progress(batch):
    if not (batch / 'candidates.csv').is_file() or not read_csv(batch / 'candidates.csv'):
        return dict(reviewed=0, pending=0, redo=0)
    jobs = make_plan(batch, plan_mode(batch))['jobs']
    return dict(reviewed=sum(j['reviewed'] for j in jobs),
                pending=sum(not j['reviewed'] and j['status'] != 'redo' for j in jobs),
                redo=sum(j['status'] == 'redo' for j in jobs))
