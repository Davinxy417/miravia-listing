"""A6 离线集成验收；不读取真实密钥、不调用网络，全部文件在 .tmp。"""
import copy
import json
import re
from pathlib import Path
from unittest.mock import patch

import openpyxl
from helpers import cli, csv_rows, json_write
from test_publish import make_ws, mark, snap, jpeg
from listing_core import image_host, image_workflow as iw, preflight, seedream
from listing_core.common import read_json, write_csv, Problem
from listing_core.content import resolve_content, scene_errors
from listing_core.fill import description_html, DESCRIPTION_MAX
from listing_core.image_layout import SLOTS
from listing_core.image_prompts import has_people, make_prompt
from listing_core.workspace import load_shop


def fixture():
    ws, batch = make_ws()
    shop = read_json(ws / 'shop.json')
    shop['image_host'] = dict(type='github', repo='offline-owner/images', branch='main',
                              base_url='https://example.invalid/images')
    shop['auto'] = dict(enabled=True, budget_units_per_group=100, budget_units_per_batch=1000, max_groups_per_file=10)
    json_write(ws / 'shop.json', shop)
    cli(ws, 'price', '--batch', batch.name)
    slots = {'01': {'title': ''}, 'variante': {'title': ''},
        '02': {'title': 'Agua más suave', 'subtitle': 'Filtra cloro y cal', 'points': [
            {'icon': 'water', 'text': 'Agua filtrada'}, {'icon': 'hand', 'text': 'Agarre cómodo'}, {'icon': 'spark', 'text': 'Uso diario'}]},
        '03': {'title': 'Filtro integrado'}, '04': {'title': 'Aclara con comodidad'},
        '05': {'title': 'Tu ducha diaria'}, '06': {'title': 'Medidas y contenido'},
        '07': {'title': 'Cuatro momentos', 'layout': '2x2', 'scenes': [{'title': t, 'icon': 'house'} for t in ('Brazos', 'Piernas', 'Bañera', 'Ducha')]},
        '08': {'title': 'Disfruta del agua'}}
    json_write(batch / 'overlays.json', {g: {'slots': slots} for g in ('T01', 'T02')})
    content = read_json(batch / 'content.json')
    content['T01'].update(image_description='圆形花洒，透明手柄，可见滤芯外壳',
        use_scene='连接软管，在淋浴区冲洗身体', hero_feature='透明手柄中可见的滤芯外壳',
        scene_briefs={
            '04': dict(location='淋浴区', action='手持花洒冲洗前臂', connections='手柄底部接软管，软管向下通往淋浴龙头', visible_result='水流落在前臂上'),
            '05': dict(location='浴缸内', action='人物肩以下入镜，冲洗小腿', connections='手柄底部接软管通往浴缸龙头', visible_result='水流沿小腿落入浴缸'),
            '08': dict(location='淋浴区', action='人物侧正脸，手持花洒冲洗肩膀', connections='手柄底部接软管通往淋浴龙头', visible_result='水流落在肩膀，人物放松')},
        image_scenes07=['淋浴区手持花洒冲洗前臂，软管接龙头，水流落在前臂',
            '淋浴区无人，花洒接支架和软管，喷出水流',
            '浴缸内手持花洒冲洗缸壁，软管接龙头，水流带走泡沫',
            '淋浴区无人，花洒接支架和软管，水流落入地漏'])
    json_write(batch / 'content.json', content)
    registry, matching, _, _, heroes = iw.context(batch)
    (batch / 'src').mkdir(exist_ok=True)
    for rows in matching.values():
        for r in rows: (batch / 'src' / f"{r['shop']}-{r['art_id']}.jpg").write_bytes(jpeg('blue'))
    stock = batch / 'internal/stock/person.jpg'
    stock.parent.mkdir(parents=True, exist_ok=True); stock.write_bytes(jpeg('gray'))
    ids = [f'T01/{heroes["T01"]}/{s}' for s in ('04', '05', '08', '07-1', '07-3')]
    write_csv(batch / 'stock_fotos.csv', [dict(archivo='internal/stock/person.jpg', fuente='Pexels',
        url='https://example.invalid/offline', autor='Offline', licencia='offline-test', usado_en=' '.join(ids))],
        ['archivo', 'fuente', 'url', 'autor', 'licencia', 'usado_en'])
    mark(batch, image_host.selection(batch, True)[0])
    return ws, batch, load_shop(ws), heroes


def test_description():
    gallery = ['https://example.invalid/' + filename for filename in SLOTS.values()]
    text = ('<p>Disfruta del agua.</p><p><b>FILTRO:</b> Agua suave.</p>'
            '<p><b>CÓMO USAR:</b> Conecta la ducha.</p><p><b>PALABRAS CLAVE:</b> ducha, filtro</p>')
    result = description_html(text, gallery)
    assert result.index('Disfruta') < result.index('08-modelo') < result.index('FILTRO:') < result.index('03-detalle') < result.index('CÓMO USAR:') < result.index('04-uso') < result.index('07-usos') < result.index('PALABRAS CLAVE:')
    assert result.endswith('<p><b>PALABRAS CLAVE:</b> ducha, filtro</p>')
    # Missing 02 must not shift slot identity.
    missing = description_html(text, [u for u in gallery if '02-puntos' not in u])
    assert '08-modelo' in missing and '03-detalle' in missing and '06-medidas' not in missing
    chosen = description_html(text, gallery, ['05', '03', '08'])
    assert chosen.index('05-uso') < chosen.index('FILTRO:') < chosen.index('03-detalle') < chosen.index('08-modelo')
    long_urls = [u.replace('example.invalid/', 'example.invalid/' + 'a'*400 + '/') for u in gallery]
    warnings = set()
    long = text.replace('Agua suave.', 'Agua suave. '*95)
    clipped = description_html(long, long_urls, warnings=warnings, group='T01')
    assert len(clipped) <= DESCRIPTION_MAX and '08-modelo' in clipped and '03-detalle' in clipped
    assert any('删除插图' in w for w in warnings), warnings
    assert clipped.endswith('<p><b>PALABRAS CLAVE:</b> ducha, filtro</p>')
    warnings.clear()
    compressed = description_html(long.replace('Agua suave.', 'Agua suave y agradable.'), long_urls, warnings=warnings)
    assert len(compressed) <= DESCRIPTION_MAX and '08-modelo' in compressed and '03-detalle' in compressed
    assert any('压缩正文' in w for w in warnings)


def main():
    test_description()
    ws, batch, shop, heroes = fixture()
    name, hero = batch.name, heroes['T01']
    cli(ws, 'images-plan', '--batch', name)
    jobs = {j['id']: j for j in read_json(batch / 'image_plan.json')['jobs']}
    for slot in ('02', '04'):
        job = jobs[f'T01/{hero}/{slot}']
        assert job['refs'] == [r['path'] for r in job['reference_images']]
        assert '参考图用途：图1' in job['prompt']
        assert all(ref not in job['prompt'] for ref in job['refs'])
        assert not any(t in job['prompt'] for t in ('bytes', 'JPG', '3145728', '重试', 'zoom=', 'subtitle', '{}'))
        assert len(re.findall(r'[\u4e00-\u9fff]', job['prompt'])) <= 330
    j04 = jobs[f'T01/{hero}/04']
    assert '图2人物身份和姿态' in j04['prompt'] and '软管向下通往淋浴龙头' in j04['prompt']
    j07 = jobs[f'T01/{hero}/07']
    people = [r for r in j07['reference_images'] if r['role'] == 'people']
    assert len(people) == 1 and '第1格' in people[0]['use'] and '第3格' in people[0]['use']
    assert '第2格' not in people[0]['use'] and '第4格' not in people[0]['use']
    assert not has_people('无人淋浴区，花洒手柄连接软管') and not has_people('毯子铺在扶手椅上')
    assert has_people('手握花洒冲洗前臂')
    corrected = make_prompt('04', '花洒', 'plata', 1, {}, 'model-text',
        scene_brief=dict(location='错误洗手台', action='错误动作'), note='在淋浴区手持冲洗手臂，接软管通往龙头，水流落在手臂')
    assert '错误洗手台' not in corrected and '错误动作' not in corrected and '淋浴区' in corrected
    macro = [dict(path='macro.jpg', role='macro', use='提供真实微距细节')]
    assert '依据图1' in make_prompt('03', '花洒', 'plata', 1, {}, 'model-text', zoom=True, references=macro)
    assert '放大圈' not in make_prompt('02', '花洒', 'plata', 1, {}, 'model-text', zoom=True, references=macro)
    content = read_json(batch / 'content.json')
    inherited, errors = resolve_content(content, ['T01', 'T01B'])
    assert not errors and inherited['T01B']['scene_briefs'] == content['T01']['scene_briefs']
    assert inherited['T01B']['description_images'] == content['T01']['description_images']
    # Read-only real preflight with a boolean-only key boundary.
    with patch.object(preflight, 'key_is_set', return_value=True):
        before = snap(ws)
        ready = preflight.run(ws, batch, shop)
        assert not ready['errors'] and ready['ready_groups'] and before == snap(ws), ready
        from test_publish import captured
        code, check = captured(ws, 'preflight', '--batch', name)
        assert code == 0 and check['key_present'] and before == snap(ws)
        broken = copy.deepcopy(shop); broken['suppliers'] = {}
        result = preflight.run(ws, batch, broken)
        assert not result['account_blockers'] and all(result['group_blockers'].values())
        broken = copy.deepcopy(shop)
        for maker in broken['suppliers'].values(): maker['responsable'] = '不存在'
        assert 'responsable' in str(preflight.run(ws, batch, broken)['group_blockers'])
        broken = copy.deepcopy(shop); broken['template'] = 'missing.xlsm'; broken['image_host'] = None
        assert len(preflight.run(ws, batch, broken)['account_blockers']) == 2
        assert preflight.run(ws, batch, shop, key_check=lambda: False)['account_blockers']
        tight = copy.deepcopy(shop); tight['auto']['budget_units_per_group'] = 1
        limited = preflight.run(ws, batch, tight)
        assert limited['group_remaining']['T01'] == 1 and not limited['account_blockers'] and limited['group_blockers']['T01']
        tight['auto']['budget_units_per_batch'] = 1
        assert preflight.run(ws, batch, tight)['account_blockers']
        bad = copy.deepcopy(content); del bad['T01']['scene_briefs']
        json_write(batch / 'content.json', bad)
        assert 'scene_briefs.04' in str(cli(ws, 'check', '--batch', name, ok=False)['errors'])
        cli(ws, 'images-plan', '--batch', name)
        calls = []
        result = seedream.run(batch, only=[f'T01/{hero}/01', f'T02/{heroes["T02"]}/01'], yes=True,
            client=lambda *args: calls.append(args) or jpeg('green'), key_reader=lambda: 'offline-only', shop=shop)
        assert len(calls) == 1 and result['produced'] == [f'T02/{heroes["T02"]}/01'], result
        assert result['blocked'][0]['id'] == f'T01/{hero}/01' and 'scene_briefs' in str(result['blocked'])
        assert f'T01/{hero}/01' not in read_json(batch / 'seedream_log.json')
        # Per-job blocker (missing person) must also leave another job callable.
        json_write(batch / 'content.json', content)
        (batch / 'stock_fotos.csv').rename(batch / 'stock.saved.csv')
        cli(ws, 'images-plan', '--batch', name)
        calls.clear()
        result = seedream.run(batch, only=[f'T01/{hero}/04', f'T01/{hero}/02'], yes=True,
            client=lambda *args: calls.append(args) or jpeg('green'), key_reader=lambda: 'offline-only', shop=shop)
        assert result['produced'] == [f'T01/{hero}/02'] and len(calls) == 1 and result['blocked'][0]['id'].endswith('/04'), result
        (batch / 'stock.saved.csv').rename(batch / 'stock_fotos.csv')
        # Account blockers stop before reading the actual key or calling API.
        cli(ws, 'images-plan', '--batch', name)
        with patch.object(preflight, 'key_is_set', return_value=False):
            result = seedream.run(batch, only=[f'T01/{hero}/04'], yes=True, shop=shop,
                key_reader=lambda: (_ for _ in ()).throw(AssertionError('不能读Key')), client=lambda *a: (_ for _ in ()).throw(AssertionError('不能付费')))
        assert 'ARK_API_KEY' in str(result['errors'])
    # Two failed reviews never auto-pass and cannot be forced into publication.
    jid = f'T01/{hero}/03'
    log = read_json(batch / 'seedream_log.json'); log[jid] = [dict(state='saved', units=1.36)]*2
    json_write(batch / 'seedream_log.json', log)
    for _ in range(2):
        cli(ws, 'images-review', '--batch', name, '--redo', jid, '--note', '滤芯结构错误',
            '--checks', '原尺寸', '320px缩略图', '--evidence', '特写遮住滤芯', '--severity', 'major')
    record = read_json(batch / 'image_review.json')['reviews'][jid]
    assert record['result'] == 'redo' and record['checks'] == ['原尺寸', '320px缩略图'] and record['evidence']
    cli(ws, 'images-review', '--batch', name, '--ok', jid, '--severity', 'major', ok=False)
    selected, skipped = image_host.selection(batch, True)
    assert {x['group'] for x in selected} == {'T02'} and any('共用来源失败' in x['reason'] for x in skipped)
    cli(ws, 'images-plan', '--batch', name)
    with patch.object(preflight, 'key_is_set', return_value=True):
        result = seedream.run(batch, only=[jid], yes=True, shop=shop,
            key_reader=lambda: (_ for _ in ()).throw(AssertionError('两次后不读Key')))
    assert not result['produced'] and '两次' in str(result['blocked'])
    cli(ws, 'price', '--batch', name)
    result = cli(ws, 'finalize', '--batch', name, '--base-url', 'https://example.invalid/images')
    assert result['upload_ready'] and result['eligible_groups'] == ['T02'] and set(result['draft_groups']) == {'T01', 'T01B'}, result
    for path, expected in [(result['outputs'][0], {'T02'}), (result['draft_outputs'][0], {'T01', 'T01B'})]:
        wb = openpyxl.load_workbook(path, keep_vba=True)
        try: assert {r[0] for r in wb['Pantilla'].iter_rows(min_row=5, values_only=True)} == expected
        finally: wb.close()
    assert {r['组'] for r in csv_rows(ws / '台账.csv')} == {'T02'}
    report = cli(ws, 'report', '--batch', name)
    assert report['upload_ready'] and set(report['draft_groups']) == {'T01','T01B'} and report['outputs'] == result['outputs'], report
    assert '仅草稿的组' in (batch / '早上看这里.md').read_text('utf-8')
    # All failed: no old upload file survives and no rows enter a new ledger.
    t02 = next(i for i in selected if i['slot'] == '01')
    mark(batch, [t02], 'redo')
    result = cli(ws, 'finalize', '--batch', name)
    assert not result['upload_ready'] and not result['outputs'] and not (batch / 'output/miravia_upload.xlsm').exists(), result
    assert not cli(ws, 'report', '--batch', name)['upload_ready']
    # Save the actual images-plan prompt sample for the final response.
    sample = batch.parents[2] / 'a6_prompt_example.txt'
    sample.write_text('\n\n'.join(slot + '\n' + jobs[f'T01/{hero}/{slot}']['prompt'] for slot in ('04','02')), 'utf-8')
    print('A6 OK：附件角色/去重/07人物、场景继承和校验、单job隔离、预检只读、两次失败不发布、草稿分组和报告、插图顺序与裁剪')
    print('提示词示例：' + str(sample))


if __name__ == '__main__': main()
