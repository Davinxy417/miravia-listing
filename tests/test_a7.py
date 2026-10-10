"""A7 夜跑修复离线验收；只用 .tmp 的假商品、假图片和模板副本。"""
import copy
import io
import json
from contextlib import contextmanager, redirect_stdout
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
from helpers import ROOT, cli, csv_rows, json_write, workspace
import mlist
from listing_core import gpsr_labels as gpsr, image_host, image_workflow as iw, overlay, report
from listing_core.common import CANDIDATE_FIELDS, SOURCE_NAME_FIELDS, Problem, read_json, write_csv
from listing_core.content import content_errors, resolve_content
from listing_core.image_background import normalize_white_background
from listing_core.image_layout import SLOTS, output_dir
from listing_core.image_prompts import points_layout, product_aspect
from listing_core.seedream import job_units
from test_yollgo import FakeClient, code, fetch, group_data, product, search, setup
from test_a6 import fixture
from smoke_test import independent_zip


def test_search_and_names():
    ws, batch, shop = setup('a7-yollgo-')
    barcode = code('765432100010')
    original = product(barcode, art='tray')
    original.update(namecn='餐具收纳盒', namees='CUBERTERO BAMBU 35X25CM', usercode='REF-TRAY')
    client = FakeClient({('3321', '收纳'): [original], ('3321', barcode): [original]})
    result = search(client, '3321', '收纳', root=batch)
    row = result['products'][0]
    assert row['namecn'] == original['namecn'] and row['namees'] == original['namees']
    assert row['usercode'] == 'REF-TRAY' and row['art_id'] == 'tray' and row['barcode'] == barcode
    assert Path(row['image_path']) == batch / 'search/3321/tray.jpg'
    assert Path(row['image_path']).read_bytes() == client.image_bytes and '/tray/600x600/' in row['image_url']
    with Image.open(result['sheet']) as im: assert im.width > 0 and im.height > 0
    downloads = len(client.downloads)
    search(client, '3321', '收纳', root=batch)
    assert len(client.downloads) == downloads
    with patch.object(client, 'image', side_effect=OSError('离线下载失败')):
        client.quotes[('3321', '坏图')] = [dict(original, artId='broken')]
        failed = search(client, '3321', '坏图', root=batch)
    assert failed['warnings'] and failed['products'][0]['image_path'] is None and Path(failed['sheet']).is_file()
    assert search(client, '3321', '空结果', root=batch)['sheet'] is None
    assert not (batch / 'search/3321/_sheet.jpg').exists()
    @contextmanager
    def fake_session(*args, **kwargs): yield client
    with patch('listing_core.yollgo_browser.session', fake_session):
        for args, expected in [([], ws), (['--batch', 'sample'], batch)]:
            stream = io.StringIO()
            with redirect_stdout(stream):
                status = mlist.main(['yollgo-search', '--ws', str(ws), '--shop', '3321', '收纳', '--auto', '--json', *args])
            data = json.loads(stream.getvalue())
            assert status == 0, data
            assert Path(data['products'][0]['image_path']) == expected / 'search/3321/tray.jpg'
    (batch / 'barcodes.txt').write_text(barcode, 'utf-8')
    fetch(ws, batch, shop, client)
    source_bytes = (batch / 'yollgo.json').read_bytes()
    json_write(batch / 'groups.json', group_data(barcode))
    cli(ws, 'build', '--batch', 'sample')
    candidates = csv_rows(batch / 'candidates.csv')
    assert list(candidates[0]) == CANDIDATE_FIELDS + SOURCE_NAME_FIELDS
    for candidate in candidates:
        assert candidate['src_name'] == candidate['src_name_cn'] == original['namecn']
        assert candidate['src_name_es'] == original['namees']
    assert (batch / 'yollgo.json').read_bytes() == source_bytes
    cli(ws, 'price', '--batch', 'sample')
    assert all(r['src_name_es'] == original['namees'] for r in csv_rows(batch / 'priced.csv'))
    single = candidates[0]
    assert overlay.verified_specs([single]) == (('35', '25'), [])
    assert gpsr.medidas(single) == '35x25 cm'
    both = dict(single, src_name_cn='容量 500ML', src_name='容量 500ML')
    assert overlay.verified_specs([both]) == (('35', '25'), ['500 ML'])
    legacy = {k: v for k, v in single.items() if k not in SOURCE_NAME_FIELDS}
    legacy['src_name'] = 'TRAY 35X25CM'
    assert gpsr.medidas(legacy) == '35x25 cm' and overlay.verified_specs([legacy])[0] == ('35', '25')
    item = dict(gpsr_name='Cubertero', attributes='Material: bambú', warning_text='',
                gpsr_safety=['Manipular con cuidado.', 'Mantener fuera del alcance de los niños.', 'No sumergir en agua.'],
                sku_include_ean=True)
    json_write(batch / 'content.json', {'G01': item, 'G01B': copy.deepcopy(item)})
    result = gpsr.run(batch, shop)
    assert not result['warnings'], result
    assert all(r['medidas'] == '35x25 cm' and r['material'] == 'bambú' for r in csv_rows(batch / 'output/gpsr/labels/index.csv'))
    # The warning names exactly the missing field, even when the other is present.
    priced = csv_rows(batch / 'priced.csv')
    for r in priced:
        r.update(src_name='餐具盒', src_name_cn='餐具盒', src_name_es='', var1_value='', var2_value='')
    write_csv(batch / 'priced.csv', priced)
    result = gpsr.run(batch, shop)
    assert result['warnings'] and all('尺寸' in w and '材质' not in w for w in result['warnings'])
    for r in priced: r['src_name_es'] = 'TRAY 35X25CM'
    write_csv(batch / 'priced.csv', priced)
    for value in ('G01', 'G01B'): item2 = read_json(batch / 'content.json'); item2[value]['attributes'] = ''; json_write(batch / 'content.json', item2)
    result = gpsr.run(batch, shop)
    assert all('材质' in w and '尺寸' not in w for w in result['warnings'])
    print('A7 1/2/5：搜索原名/货号/下载/总览/复用/失败/双路径，双语规格、旧表兼容和精确GPSR诊断通过')


def test_layout_structure_and_report():
    ws, batch, shop, heroes = fixture()
    hero = heroes['T01']
    for aspect in (0.2, 0.7, 1, 1.4, 4, 10):
        layout = points_layout(aspect)
        x, y, width, height = layout['box']
        assert layout['width'] <= width and layout['height'] <= height + 1e-12
        assert abs(layout['width']/layout['height'] - aspect) < 1e-10
        assert x >= .05 and y >= .05 and x+width <= .95+1e-12 and y+height <= .95+1e-12
    principal = output_dir(batch / 'images', 'T01', hero) / SLOTS['01']
    wide = Image.new('RGB', (1200, 1200), 'white')
    ImageDraw.Draw(wide).rectangle((150, 450, 1050, 750), fill='brown')
    wide.save(principal)
    assert product_aspect(principal) > 2.9
    content = read_json(batch / 'content.json')
    lock = '长方形托盘，左侧1个纵向长格＋右侧4个横向格，共5格，隔板固定'
    content['T01']['structure_lock'] = lock
    json_write(batch / 'content.json', content)
    resolved, errors = resolve_content(content, ['T01', 'T01B'])
    assert not errors and resolved['T01B']['structure_lock'] == lock
    for bad in ('', None, 5, []):
        assert any('structure_lock' in e for e in content_errors('T01', dict(content['T01'], structure_lock=bad)))
    variant_base = batch / 'images/T01' / hero / 'internal/base'
    variant_base.mkdir(parents=True)
    group_base = batch / 'images/T01/internal/base'
    group_base.mkdir(parents=True)
    wide.save(group_base / 'structure.jpg')
    # A pre-existing variant base folder must not suppress the group-level fallback.
    jobs = {j['id']: j for j in iw.make_plan(batch)['jobs']}
    for slot in ('04', '05', '07', '08'):
        job = jobs[f'T01/{hero}/{slot}']
        assert job['reference_images'][1]['path'] == 'images/T01/internal/base/structure.jpg'
        assert '图2锁定结构和隔板数量' in job['prompt']
    wide.save(variant_base / 'structure.jpg')
    jobs = {j['id']: j for j in iw.make_plan(batch)['jobs']}
    for job in jobs.values():
        if job['group'] in ('T01', 'T01B') and job['method'] not in ('copy', 'derive'):
            assert lock in job['prompt']
    for slot in ('04', '05', '07', '08'):
        job = jobs[f'T01/{hero}/{slot}']
        assert job['refs'] == [r['path'] for r in job['reference_images']]
        assert job['reference_images'][1]['path'].endswith(f'{hero}/internal/base/structure.jpg')
    prompt = jobs[f'T01/{hero}/02']['prompt']
    assert '上方横排图标，下方整宽商品区' in prompt and '完整' in prompt
    assert '右侧55%' not in prompt and '最长边约75%' not in prompt
    # Re-review the replaced main image, then preserve two concrete structural failures.
    iw.review(batch, ok=[f'T01/{hero}/01'])
    failed_ids = [f'T01/{hero}/{s}' for s in ('04', '08')]
    iw.review(batch, redo=failed_ids, note='原图5格，成品6格/4格', severity='major', evidence='逐项数格数')
    t02 = f'T02/{heroes["T02"]}/01'
    iw.review(batch, redo=[t02], note='件数错误', severity='major')
    log = {jid: [dict(state='saved', units=1.36)] for jid in failed_ids}
    log[t02] = [dict(state='saved', units=1.36)]*2
    json_write(batch / 'seedream_log.json', log)
    shop['auto'].update(budget_units_per_group=3, budget_units_per_batch=6)
    json_write(ws / 'shop.json', shop)
    actions = report.image_actions(batch, shop, log)
    assert {j['id'] for j in actions['generate']} == set(failed_ids)
    assert [j['id'] for j in actions['manual']] == [t02]
    current_jobs = {j['id']: j for j in iw.make_plan(batch)['jobs']}
    expected = sum((job_units(current_jobs[jid]) for jid in failed_ids), Decimal(0))
    assert actions['estimated_units'] == float(expected)
    assert actions['group_shortfalls']['T01'] > 0 and actions['budget_shortfall'] > 0
    # No gh, git, or network boundary is reachable when all groups fail.
    with patch.object(image_host, 'gh', side_effect=AssertionError('不能调图床')), patch.object(image_host, 'git', side_effect=AssertionError('不能调git')):
        for include in (False, True):
            try: image_host.publish(ws, batch, shop, yes=True, include_unreviewed=include)
            except Problem as exc:
                assert all(jid in str(exc) for jid in failed_ids) and '原图5格' in str(exc)
                assert '--include-unreviewed' not in str(exc)
            else: raise AssertionError('失败组必须拦截')
    not_run = cli(ws, 'report', '--batch', batch.name)
    assert not_run['finalize_state'] == 'not_run'
    assert any('先 finalize' in text for text in not_run['todos'])
    result = cli(ws, 'finalize', '--batch', batch.name, '--max-groups', '10')
    assert not result['outputs'] and not result['upload_ready'] and not (batch / 'output/miravia_upload.xlsm').exists()
    assert '全部组只出草稿' in result['message'] and '完整备份' not in result['message'] and '按列出的分批表上传' not in result['message']
    independent_zip(ws / 'template' / shop['template'], Path(result['draft_outputs'][0]))
    result = cli(ws, 'report', '--batch', batch.name)
    assert result['finalize_state'] == 'draft_only' and not result['outputs'] and not result['upload_ready']
    assert not any('先 finalize' in text or '没做到这一步' in text for text in result['todos'])
    text = (batch / '早上看这里.md').read_text('utf-8')
    assert all(jid in text for jid in failed_ids) and f'{float(expected):.2f} 套餐单位' in text and '两次尝试已用尽' in text
    assert '预算还差' in text and 'finalize 已执行' in text
    print('A7 3/4/7：宽高兼容、安全边距、全槽结构锁/继承、结构附件优先级、失败诊断、全草稿与重做预算报告通过')


def test_white_and_docs():
    im = Image.new('RGB', (20, 20), (250, 248, 246))
    draw = ImageDraw.Draw(im)
    draw.rectangle((5, 5, 14, 14), fill=(80, 100, 120))
    im.putpixel((10, 10), (250, 248, 246))  # Enclosed product highlight.
    im.putpixel((3, 16), (235, 238, 240))  # Gentle darker shadow.
    im.putpixel((2, 2), (255, 244, 255))  # A channel below threshold is preserved.
    before = im.tobytes()
    result = normalize_white_background(im)
    assert im.tobytes() == before and result.getpixel((0, 0)) == (255, 255, 255)
    for point in ((10, 10), (3, 16), (2, 2), (5, 5)):
        assert result.getpixel(point) == im.getpixel(point)
    assert normalize_white_background(result).tobytes() == result.tobytes()
    # Two near-white areas touching only diagonally must stay separate.
    diagonal = Image.new('RGB', (3, 3), 'black')
    diagonal.putpixel((0, 0), (250, 250, 250)); diagonal.putpixel((1, 1), (250, 250, 250))
    fixed = normalize_white_background(diagonal)
    assert fixed.getpixel((0, 0)) == (255, 255, 255) and fixed.getpixel((1, 1)) == (250, 250, 250)
    ws, batch, _, heroes = fixture()
    hero = heroes['T01']
    source = Image.new('RGB', (1200, 1200), (250, 249, 248))
    ImageDraw.Draw(source).rectangle((300, 300, 900, 850), fill=(40, 70, 100))
    ImageDraw.Draw(source).rectangle((310, 870, 890, 910), fill=(238, 238, 238))
    ImageDraw.Draw(source).rectangle((450, 450, 550, 550), fill=(250, 249, 248))
    raw = batch / f'images/T01/{hero}/internal/raw/01-v01.png'
    raw.parent.mkdir(parents=True); source.save(raw)
    ids = [f'T01/{hero}/{s}' for s in ('01', 'variante')]
    iw.finish(batch, only=ids)
    for name in (SLOTS['01'], 'variante.jpg'):
        target = output_dir(batch / 'images', 'T01', hero) / name
        with Image.open(target) as exported:
            assert exported.mode == 'RGB' and exported.size == (1200, 1200) and exported.info.get('icc_profile')
            assert exported.getpixel((20, 20)) == (255, 255, 255)
            assert max(exported.getpixel((500, 890))) < 245
            assert exported.getpixel((500, 500)) != (255, 255, 255)
        assert target.stat().st_size < overlay.MAX_BYTES
    old = iw.digest(output_dir(batch / 'images', 'T01', hero) / SLOTS['01'])
    assert not iw.finish(batch, only=ids)['installed']
    assert old == iw.digest(output_dir(batch / 'images', 'T01', hero) / SLOTS['01'])
    # The older direct export/collection path also normalizes variante.
    directory = ws / 'direct'; directory.mkdir()
    source.save(directory / SLOTS['01'])
    overlay.ensure_variant_image(directory)
    with Image.open(directory / 'variante.jpg') as exported: assert exported.getpixel((20, 20)) == (255, 255, 255)
    data = (ROOT / 'references/数据格式.md').read_text('utf-8-sig')
    exp = (ROOT / 'references/电商经验.md').read_text('utf-8-sig')
    rules = (ROOT / 'references/出图规则.md').read_text('utf-8-sig')
    skill = (ROOT / 'SKILL.md').read_text('utf-8-sig')
    assert '无界面' not in data and '三个友购命令都打开可见' in data
    assert '不要直接改 `candidates.csv`' in exp and 'groups.json' in exp and 'build --force' in exp
    assert '缺资料时 agent 按商品用途写 3～5 条' in data and '3～5条通用西语安全提示' in skill
    assert '逐项计数' in rules and '数量不符即redo' in rules and '看不全' in rules
    print('A7 6/8：文档一致，边缘连通白底、商品/阴影/高光/彩色像素保留、幂等、两条导出路径通过')


def main():
    with patch('socket.create_connection', side_effect=AssertionError('A7 禁止联网')), \
         patch('listing_core.seedream.api_key', side_effect=AssertionError('A7 不读取密钥')):
        test_search_and_names()
        test_layout_structure_and_report()
        test_white_and_docs()
    print('A7 OK')


if __name__ == '__main__': main()
