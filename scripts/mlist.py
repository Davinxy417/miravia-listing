"""把批次数据整理成 Miravia 上传文件；所有步骤共用此入口。"""
import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

# Running check/help must not create __pycache__ files.
sys.dont_write_bytecode = True

from listing_core.common import Problem, guard_images, inside
from listing_core.workspace import batch_path, init, load_shop, new_batch, resolve_workspace, template_path


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Problem(f'命令参数不正确：{message}；请运行对应子命令 --help 查看用法。')


def parser():
    common = Parser(add_help=False)
    common.add_argument('--ws', default=argparse.SUPPRESS, metavar='工作区', help='工作区路径；优先于 MIRAVIA_WS 和用户配置')
    common.add_argument('--batch', default=argparse.SUPPRESS, metavar='批次名', help='批次相关步骤必填')
    common.add_argument('--json', action='store_true', default=argparse.SUPPRESS, help='仅输出一个 JSON 对象，供网页或脚本读取')
    p = Parser(description=__doc__, parents=[common])
    p._positionals.title = '步骤'
    p._optionals.title = '选项'
    sub = p.add_subparsers(dest='command', required=True, metavar='步骤')
    descriptions = {
        'init': '建立工作区和示例配置，绝不覆盖已有 shop.json',
        'new-batch': '建立一个空批次，已有同名批次会报错',
        'import-legacy': '导入旧数据并联接图片目录，不复制图片、不写旧项目',
        'price': '按 shop.json 对 candidates.csv 定价，生成 priced.csv',
        'fill': '检查后填入官方模板，生成 output/miravia_upload.xlsm',
        'check': '只检查不写文件，汇总文案、条码、下拉、图片和制造商问题',
        'status': '查看批次文件是否齐全，以及价格和输出是否需要更新',
        'categories': '搜索模板类目下拉，返回完整类目原文',
        'gpsr': '读取店铺与商品资料，生成 GPSR 标签 PNG 和 A4 PDF',
        'overlay': '用 Pillow 在现有底图上叠字，不联网、不生成 AI 图片',
        'images-collect': '收集主推款展示图和每个变体的图片到 image_files.csv',
        'images-urls': '根据图床前缀生成 images.csv；只生成网址，不上传图片',
    }
    commands = {}
    for name, description in descriptions.items():
        child = sub.add_parser(name, description=description, help=description, parents=[common])
        child._positionals.title = '参数'
        child._optionals.title = '选项'
        commands[name] = child
    commands['new-batch'].add_argument('name', metavar='名字', help='新批次文件夹名称，如 冬季第一批')
    commands['import-legacy'].add_argument('--from', dest='source', required=True, metavar='旧项目路径', help='含 data、scripts、images、template 的旧目录，只读')
    commands['categories'].add_argument('--search', default='', metavar='关键词', help='按完整类目文字包含匹配，留空列出全部')
    commands['images-urls'].add_argument('--base-url', required=True, metavar='网址前缀', help='图床 images 根地址，HTTP(S)，不含查询参数')
    selection = commands['overlay'].add_mutually_exclusive_group(required=True)
    selection.add_argument('--all', action='store_true', help='处理全部商品组')
    selection.add_argument('--group', action='append', metavar='组名', help='指定组，可重复传入')
    commands['overlay'].add_argument('--demo', action='store_true', help='额外生成前三组的审阅拼图')
    return p


def dispatch(args):
    ws = resolve_workspace(getattr(args, 'ws', None))
    cmd = args.command
    if cmd == 'init':
        init(ws)
        return dict(workspace=str(ws), message='工作区已就绪；已有店铺配置保持不变。请填写 shop.json 并放入官方模板。')
    if cmd == 'new-batch':
        return dict(batch=str(new_batch(ws, args.name)), message='空批次已建立，请导入或填写商品数据。')
    if cmd == 'import-legacy':
        from listing_core.legacy import run
        return run(ws, args.source, getattr(args, 'batch', None))
    shop = load_shop(ws)
    if cmd == 'categories':
        import openpyxl
        from listing_core.headers import dropdown
        wb = openpyxl.load_workbook(template_path(ws, shop), keep_vba=True)
        try: values = sorted(v for v in dropdown(wb, 'category') if args.search.casefold() in v.casefold())
        finally: wb.close()
        return dict(categories=values, count=len(values))
    batch = batch_path(ws, getattr(args, 'batch', None))
    # No batch file may write through a pre-existing link outside its workspace.
    if cmd not in ('check', 'status'):
        for name in ('priced.csv', 'image_files.csv', 'images.csv', 'output'):
            inside(batch, batch / name)
    if cmd == 'price':
        from listing_core.pricing import run
        return run(batch, shop)
    if cmd in ('fill', 'check'):
        from listing_core.fill import run
        return run(template_path(ws, shop), batch, shop, check=cmd == 'check')
    if cmd == 'status':
        from listing_core.status import run
        return run(ws, batch, template_path(ws, shop, False))
    if cmd == 'gpsr':
        from listing_core.gpsr_labels import run
        return run(batch, shop)
    if cmd == 'overlay':
        from listing_core.overlay import run
        guard_images(batch)
        missing = run(args.group, batch / 'overlays.json', batch / 'images', batch / 'variantes.csv', batch / 'candidates.csv', args.demo)
        return dict(warnings=[f'图片尚未处理：{m}；请补齐底图或商品数据后重试。' for m in missing], message='叠字处理完成。')
    if cmd == 'images-collect':
        from listing_core.collect_images import collect
        readonly = (batch / 'images').resolve() != (batch / 'images').absolute()
        if not readonly: guard_images(batch)
        warnings = ['图片目录是联接，只读取已有图片，不补写或修改旧图片。'] if readonly else []
        rows = collect(batch / 'images', batch / 'image_files.csv', batch / 'variantes.csv', readonly=readonly, warnings=warnings)
        return dict(count=len(rows), output=str(batch / 'image_files.csv'), warnings=warnings)
    if cmd == 'images-urls':
        from listing_core.make_images_csv import make_images_csv
        rows = make_images_csv(args.base_url, batch / 'image_files.csv', batch / 'images.csv', batch / 'variantes.csv', batch / 'images')
        return dict(count=len(rows), output=str(batch / 'images.csv'))
    raise Problem('未知步骤；请运行 --help 查看可用命令。')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = '--json' in argv
    output, errors, warnings = {}, [], []
    logs = io.StringIO()
    try:
        with contextlib.redirect_stdout(logs), contextlib.redirect_stderr(logs):
            args = parser().parse_args(argv)
            output = dispatch(args)
        warnings = output.pop('warnings', [])
    except SystemExit as exc:
        if exc.code not in (None, 0): errors = ['命令参数不正确；请运行 --help 查看用法。']
        else:
            if not json_mode:
                print(logs.getvalue(), end='')
                return 0
            output = {'help': logs.getvalue()}
    except Problem as exc:
        errors, warnings = exc.errors, exc.warnings
    except FileNotFoundError as exc:
        errors = [f'找不到文件 {exc.filename or exc}；请检查工作区路径，并先完成上一步骤。']
    except PermissionError as exc:
        errors = [f'无法读写 {exc.filename or exc}；请关闭占用文件的 Excel，确认目录权限后重试。']
    except Exception as exc:
        errors = [f'这一步未完成（{type(exc).__name__}）：{exc}；请核对对应批次文件和配置后重试。']
    result = dict(ok=not errors, warnings=warnings, errors=errors, **output)
    if json_mode:
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    else:
        if not errors:
            print(output.get('message', '处理完成。'))
            if 'count' in output: print(f"共 {output['count']} 条。")
            for key in ('workspace', 'batch', 'output'):
                if key in output: print(output[key])
            for category in output.get('categories', []): print(category)
            if 'steps' in output:
                labels = dict(barcodes='条码清单', candidates='候选商品', pricing='定价', content='文案', image_files='本地图片清单', images='图片网址', output='上传表', image_directory='图片目录')
                for stage, state in output['steps'].items():
                    status = '已有' if state.get('ready', state.get('exists', False)) else '未完成'
                    if 'fresh' in state: status += '，已更新' if state['fresh'] else '，需更新'
                    print(f'{labels[stage]}：{status}')
                    if 'error' in state: print(state['error'])
        for warning in warnings: print(f'提醒：{warning}')
        for error in errors: print(f'错误：{error}')
    return 1 if errors else 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
