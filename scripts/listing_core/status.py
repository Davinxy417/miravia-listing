"""仅由磁盘文件推导进度，不写状态文件。"""
from pathlib import Path
from .common import read_csv, read_json


def run(ws, batch, template):
    def file_info(path):
        path = Path(path)
        present = path.is_file()
        return dict(exists=present, bytes=path.stat().st_size if present else 0)
    steps = {}
    for stage, name in (('barcodes', 'barcodes.txt'), ('candidates', 'candidates.csv'), ('pricing', 'priced.csv'),
                        ('content', 'content.json'), ('image_files', 'image_files.csv'), ('images', 'images.csv')):
        path = batch / name
        info = file_info(path)
        if info['exists']:
            try:
                data = read_csv(path) if path.suffix == '.csv' else read_json(path) if path.suffix == '.json' else [s for s in path.read_text('utf-8-sig').splitlines() if s.strip()]
                info['count'] = len(data)
                if stage == 'images': info['count'] = sum(bool(r['url'].strip()) for r in data)
                info['ready'] = bool(info['count'])
            except (ValueError, KeyError, OSError) as exc:
                info.update(ready=False, error=f'{name} 无法读取：{exc}；请修正文件。')
        else: info['ready'] = False
        steps[stage] = info
    pricing_inputs = [batch / 'candidates.csv', Path(ws) / 'shop.json']
    if (batch / 'build.json').is_file(): pricing_inputs.append(batch / 'build.json')
    steps['pricing']['fresh'] = steps['pricing']['ready'] and all(p.is_file() and p.stat().st_mtime_ns <= (batch/'priced.csv').stat().st_mtime_ns for p in pricing_inputs)
    output = batch / 'output/miravia_upload.xlsm'
    inputs = [Path(ws) / 'shop.json', template, *[batch / n for n in ('candidates.csv', 'priced.csv', 'content.json', 'variantes.csv')]]
    optional = [batch / n for n in ('images.csv', 'image_files.csv')]
    images_dir = batch / 'images'
    # Local bytes do not alter Excel URLs, but hero.txt does change gallery selection.
    heroes = list(images_dir.glob('*/hero.txt')) if images_dir.is_dir() else []
    newer = [str(p) for p in inputs + [p for p in optional if p.exists()] + heroes
             if not p.is_file() or not output.exists() or p.stat().st_mtime_ns > output.stat().st_mtime_ns]
    steps['output'] = dict(**file_info(output), ready=output.is_file(), fresh=output.is_file() and not newer and steps['pricing']['fresh'], newer_inputs=newer)
    steps['image_directory'] = dict(exists=images_dir.is_dir(), linked=images_dir.resolve() != images_dir.absolute())
    return dict(steps=steps, message='进度由当前文件推算；fresh=false 表示需要重做。')
