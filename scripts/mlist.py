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
        'yollgo-login': '打开系统 Edge，先尝试已保存密码的自动填充；失败请手动登录',
        'fetch': '读取 barcodes.txt，搜友购报价、选批发商、保存原图和总览',
        'yollgo-search': '在一家友购批发商中搜索关键词或条码，寻找同系列商品',
        'keywords': '查亚马逊西班牙/Google 西班牙搜索联想(真实买家搜索词),写标题前用',
        'build': '校验 groups.json，生成候选 SKU、颜色/组合装条码和变体目录',
        'images-plan': '按批次、现有图片和审阅结果生成出图清单',
        'images-finish': '整理原始图、脚本画尺寸、派生变体图并备份旧图',
        'seedream': '按清单调用 Seedream；--yes 确认付费，--auto 按店铺预算放行',
        'images-sheet': '按组生成带 id 和状态的审阅拼图',
        'images-review': '记录图片通过或重做及原因',
        'image-host-setup': '建立或使用公开 GitHub 图床；先预览，加 --yes 才操作',
        'publish-images': '发布本批次审过的成品；先预览，加 --yes 才推送',
        'finalize': '收集图片、使用已发布网址、填表检查；可分批并更新上架台账',
        'report': '写早上看这里.md：能否上传、表路径、售价利润、出图费用和待办',
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
    commands['yollgo-search'].add_argument('--shop', required=True, metavar='商家id', help='友购批发商 id，保留前导零，例如 027')
    commands['yollgo-search'].add_argument('keyword', metavar='关键词或条码', help='含空格时用引号括起来，如 "MANTA BORREGO"')
    commands['keywords'].add_argument('seeds', nargs='+', metavar='种子词', help='品类+功能词,每个含空格的词用引号,如 "alcachofa ducha" "ducha filtro"')
    commands['build'].add_argument('--force', action='store_true', help='明确覆盖已有候选商品和变体映射，随后必须重新 price')
    for name in ('fetch', 'yollgo-search', 'yollgo-login'):
        commands[name].add_argument('--auto', action='store_true', help='无人值守：自动登录失败后最多等 10 分钟，再提示手动登录重跑')
    selection = commands['overlay'].add_mutually_exclusive_group(required=True)
    selection.add_argument('--all', action='store_true', help='处理全部商品组')
    selection.add_argument('--group', action='append', metavar='组名', help='指定组，可重复传入')
    commands['overlay'].add_argument('--demo', action='store_true', help='额外生成前三组的审阅拼图')
    commands['images-plan'].add_argument('--mode', choices=('model-text', 'base-overlay'), default='model-text', help='默认模型设计带字；base-overlay 为无字底图加脚本叠字')
    for name in ('images-finish', 'images-sheet'):
        commands[name].add_argument('--group', action='append', help='指定组，可重复')
        commands[name].add_argument('--only', nargs='+', help='完整 id，如 G01/crema/02')
    commands['images-sheet'].add_argument('--pending', action='store_true', help='只看未通过审阅的')
    commands['images-sheet'].add_argument('--name', default='review', help='拼图名字，批次 review/ 下；大量图片自动分页')
    chosen = commands['seedream'].add_mutually_exclusive_group(required=True)
    chosen.add_argument('--only', nargs='+', help='选择完整 id')
    chosen.add_argument('--all-missing', action='store_true', help='只生成缺图，不包含重做；派生/共用图不扣费')
    approval = commands['seedream'].add_mutually_exclusive_group()
    approval.add_argument('--yes', action='store_true', help='确认预计张数及单位，允许调用付费接口')
    approval.add_argument('--auto', action='store_true', help='按 shop.json 的组/批次预算自动放行；超预算跳过，失败即停')
    commands['images-review'].add_argument('--ok', nargs='+', help='通过的完整 id，可多张')
    commands['images-review'].add_argument('--redo', nargs='+', help='需重做的完整 id')
    commands['images-review'].add_argument('--note', default='', help='重做原因，标记重做时必填')
    commands['image-host-setup'].add_argument('--repo', required=True, metavar='账号/仓库名', help='填仓库名或账号/仓库名；已有公开仓库直接用，不覆盖旧内容')
    commands['image-host-setup'].add_argument('--branch', default='main', help='图床分支，默认 main；已有其他分支时可指定')
    commands['image-host-setup'].add_argument('--yes', action='store_true', help='确认公开操作；不加仅说明计划并退出 2')
    commands['publish-images'].add_argument('--yes', action='store_true', help='确认推送；不加仅列张数、总大小、目标和跳过图片，退出 2')
    commands['publish-images'].add_argument('--include-unreviewed', action='store_true', help='明确允许发布没审过、图片变化或要求重做的现有成品；仍须 --yes')
    commands['finalize'].add_argument('--max-groups', type=int, metavar='N', help='每份最多 N 个链接；主组和 B 组不拆开，它们各占一个链接')
    commands['finalize'].add_argument('--base-url', metavar='网址前缀', help='可选：为手动托管图片生成网址；GitHub 发布后无需填写，不联网不推送')
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
    if cmd == 'image-host-setup':
        from listing_core.image_host import setup
        return setup(ws, shop, args.repo, args.yes, args.branch)
    if cmd == 'yollgo-login':
        from listing_core.yollgo_browser import login
        # main captures stdout; send interactive instructions before its redirect.
        return login(ws, notify=_tell, unattended=args.auto)
    if cmd == 'yollgo-search':
        from listing_core.yollgo_browser import session
        from listing_core.yollgo import search
        with session(ws, notify=_tell, unattended=args.auto) as client:
            return search(client, args.shop, args.keyword)
    if cmd == 'keywords':
        from listing_core.keywords import suggest
        return suggest(args.seeds)
    if cmd == 'categories':
        import openpyxl
        from listing_core.headers import dropdown
        wb = openpyxl.load_workbook(template_path(ws, shop), keep_vba=True)
        try: values = sorted(v for v in dropdown(wb, 'category') if args.search.casefold() in v.casefold())
        finally: wb.close()
        return dict(categories=values, count=len(values))
    batch = batch_path(ws, getattr(args, 'batch', None))
    if cmd == 'report':
        from listing_core.report import run
        return run(ws, batch, shop, template_path(ws, shop, False))
    if cmd == 'publish-images':
        from listing_core.image_host import publish
        return publish(ws, batch, shop, args.yes, args.include_unreviewed)
    if cmd == 'finalize':
        from listing_core.finalize import finalize
        return finalize(ws, batch, shop, template_path(ws, shop), args.max_groups, args.base_url)
    if cmd == 'fetch':
        from listing_core.yollgo_browser import session
        from listing_core.yollgo import fetch
        with session(ws, notify=_tell, unattended=args.auto) as client:
            return fetch(ws, batch, shop, client)
    if cmd == 'build':
        from listing_core.yollgo_build import build
        return build(ws, batch, shop, force=args.force)
    if cmd.startswith('images-') and cmd in ('images-plan', 'images-finish', 'images-sheet', 'images-review'):
        from listing_core import image_workflow as iw
        if cmd == 'images-plan': return iw.plan(batch, args.mode)
        if cmd == 'images-finish': return iw.finish(batch, args.group, args.only)
        if cmd == 'images-sheet': return iw.sheet(batch, args.name, args.group, args.only, args.pending)
        return iw.review(batch, args.ok, args.redo, args.note)
    if cmd == 'seedream':
        from listing_core.seedream import run
        return run(batch, args.only, args.all_missing, args.yes, auto=args.auto, shop=shop)
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


def _tell(message):
    # 交互提示走 stderr:stdout 可能被 --json 占用。
    print(message, file=sys.stderr, flush=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = '--json' in argv
    output, errors, warnings = {}, [], []
    args = None
    logs = io.StringIO()
    try:
        with contextlib.redirect_stdout(logs), contextlib.redirect_stderr(logs):
            args = parser().parse_args(argv)
            if args.command == 'yollgo-login':
                # JSON stdout remains one object; the prompt is timely on stderr.
                prompt = sys.__stderr__ if json_mode else sys.__stdout__
                print('请在弹出的窗口里登录友购', file=prompt, flush=True)
            output = dispatch(args)
        warnings = output.pop('warnings', [])
        errors = output.pop('errors', [])
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
    exit_code = output.pop('exit_code', 1 if errors else 0)
    result = dict(ok=not errors, warnings=warnings, errors=errors, **output)
    if args is not None and args.command in ('finalize', 'report'):
        result.setdefault('upload_ready', False)
    if json_mode:
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    else:
        if errors and output.get('needs_confirm'): print(output.get('message', ''))
        if not errors:
            print(output.get('message', '处理完成。'))
            if 'count' in output: print(f"共 {output['count']} 条。")
            for key in ('workspace', 'batch', 'output'):
                if key in output: print(output[key])
            for group, counts in output.get('summary', {}).items():
                print(f"{group}：缺 {counts['missing']} / 已有 {counts['existing']} / 要重做 {counts['redo']}")
            if 'image_review' in output:
                r = output['image_review']
                print(f"图片审阅：审过 {r['reviewed']} / 没审 {r['pending']} / 要重做 {r['redo']}")
            for category in output.get('categories', []): print(category)
            for product in output.get('products', []):
                print(f"{product['barcode']}  {product['name']}  €{product['price']}")
            if 'steps' in output:
                labels = dict(barcodes='条码清单', candidates='候选商品', pricing='定价', content='文案', image_files='本地图片清单', images='图片网址', output='上传表', image_directory='图片目录')
                for stage, state in output['steps'].items():
                    status = '已有' if state.get('ready', state.get('exists', False)) else '未完成'
                    if 'fresh' in state: status += '，已更新' if state['fresh'] else '，需更新'
                    print(f'{labels[stage]}：{status}')
                    if 'error' in state: print(state['error'])
        for item in output.get('files', []): print(f"拟发布：{item['id']} → {item['path']}")
        for item in output.get('skipped', []): print(f"跳过：{item['id']}（{item['reason']}）")
        for warning in warnings: print(f'提醒：{warning}')
        for error in errors: print(f'错误：{error}')
    return exit_code


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
