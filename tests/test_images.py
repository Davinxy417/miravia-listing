"""A3 一条命令离线验收；纯色假接口，不读取真实密钥、不联网。"""
import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
from unittest.mock import patch

from PIL import Image, ImageDraw
from helpers import FIXTURES, ROOT, cli, json_write, workspace
import mlist
from listing_core import image_workflow as iw, seedream
from listing_core.common import Problem, read_json
from listing_core.content import resolve_content
from listing_core.image_layout import SLOTS, output_dir
from listing_core.legacy import constants, import_content


def fake_image(colour='navy', size=(740, 990)):
    im = Image.new('RGB', size, 'white')
    ImageDraw.Draw(im).rectangle((180,280,540,800), fill=colour)
    stream = io.BytesIO(); im.save(stream, 'PNG'); return stream.getvalue()


def captured(ws, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = mlist.main([*args, '--ws', str(ws), '--batch', 'sample', '--json'])
    return code, json.loads(out.getvalue())


def test_auto_budget():
    ws = workspace('auto-budget-')
    cli(ws, 'init'); cli(ws, 'new-batch', 'sample')
    batch = ws / 'batches/sample'
    (batch / 'ref.jpg').write_bytes(fake_image())
    def job(jid, refs=1):
        return dict(id=jid, group=jid.split('/')[0], variant='crema', slot=jid.split('/')[-1],
                    method='model', status='missing', raw=None, refs=['ref.jpg'] * refs,
                    raw_dir='images/' + jid.rsplit('/', 1)[0] + '/internal/raw', output='unused.jpg',
                    prompt='离线图', blockers=[])
    jobs = [job('G01/crema/01', 3), job('G01/crema/02'), job('G01B/crema/01'), job('G03/crema/01')]
    json_write(batch / 'image_plan.json', dict(jobs=jobs))
    json_write(batch / 'seedream_log.json', {'G01/old/01': [dict(state='failed')],
                                           'G00/old/01': [dict(state='started', units=0.5)]})
    shop = dict(auto=dict(enabled=True, budget_units_per_group=2.8, budget_units_per_batch=4.58))
    config = read_json(ws / 'shop.json')
    config['auto'] = dict(shop['auto'], max_groups_per_file=10)
    json_write(ws / 'shop.json', config)
    with patch.object(seedream, 'make_plan', return_value=dict(jobs=jobs)), patch.object(seedream, 'preflight', return_value=dict(account_blockers=[], group_blockers={})):
        result = seedream.run(batch, all_missing=True, auto=True, shop=shop, client=lambda *a: fake_image(), key_reader=lambda: 'fake')
        assert result['produced'] == ['G01/crema/02', 'G01B/crema/01'], result
        assert result['over_budget'] == ['G01/crema/01', 'G03/crema/01'] and result['spent_units'] == 4.58
        log = read_json(batch / 'seedream_log.json')
        assert log['G01/crema/02'][0]['units'] == 1.36
        assert seedream.spending(log)[1]['G01'] == seedream.Decimal('2.72')
        result = seedream.run(batch, all_missing=True, auto=True, shop=shop,
                              key_reader=lambda: (_ for _ in ()).throw(AssertionError('超预算不读 Key')))
        assert len(result['over_budget']) == 4 and not result['errors'] and result['spent_units'] == 4.58
        with patch.object(seedream, 'api_key', side_effect=AssertionError('不能读密钥')):
            code, result = captured(ws, 'seedream', '--only', jobs[0]['id'], '--auto')
        assert code == 0 and result['over_budget'] == [jobs[0]['id']]
    code, result = captured(ws, 'seedream', '--only', jobs[0]['id'], '--auto', '--yes')
    assert code == 1 and '--auto' in str(result) and '--yes' in str(result)
    config = read_json(ws / 'shop.json'); config['auto']['enabled'] = False
    json_write(ws / 'shop.json', config)
    code, result = captured(ws, 'seedream', '--only', jobs[0]['id'], '--auto')
    assert code == 1 and '店铺未开启全自动' in str(result)
    # An uncertain API failure is charged once and stops all later calls.
    (batch / 'seedream_log.json').unlink()
    jobs = [job('G01/crema/01', 2), job('G02/crema/01')]
    json_write(batch / 'image_plan.json', dict(jobs=jobs))
    with patch.object(seedream, 'make_plan', return_value=dict(jobs=jobs)), patch.object(seedream, 'preflight', return_value=dict(account_blockers=[], group_blockers={})):
        calls = []
        def failure(*args):
            calls.append(1); raise TimeoutError('offline')
        tight = dict(auto=dict(enabled=True, budget_units_per_group=10, budget_units_per_batch=1.5))
        result = seedream.run(batch, all_missing=True, auto=True, shop=tight, client=failure, key_reader=lambda: 'fake')
        assert len(calls) == 1 and result['errors'] and result['spent_units'] == 1.45
        assert result['over_budget'] == [], '失败立即停，不处理或记录后面的预算跳过'
        assert read_json(batch / 'seedream_log.json')['G01/crema/01'][0]['state'] == 'failed'
    print('全自动预算：旧日志/失败/started 累计、边界放行、超预算继续、B 组独立、重跑累计、互斥和关闭开关通过')


def main():
    test_auto_budget()
    from test_a6 import main as test_a6
    test_a6()
    ws = workspace('images-')
    cli(ws, 'init'); cli(ws, 'new-batch', 'sample')
    batch = ws / 'batches/sample'
    shutil.copytree(FIXTURES / 'batch', batch, dirs_exist_ok=True)
    slots = {'01': {'title': ''}, 'variante': {'title': ''},
             '02': {'title': 'Una manta suave', 'points': [{'icon':'bed','text':'Tejido suave'}, {'icon':'house','text':'Uso diario'}, {'icon':'hand','text':'Cuidado fácil'}]},
             '03': {'title': 'Detalle del tejido'}, '04': {'title': 'Uso en casa'},
             '05': {'title': 'Otra escena'}, '06': {'title': 'Medidas y contenido'},
             '07': {'title': 'Cuatro usos', 'layout': '2x2', 'scenes': [{'title': v, 'icon':'house'} for v in ('Sofá','Cama','Lectura','Descanso')]},
             '08': {'title': 'Vida diaria'}}
    json_write(batch / 'overlays.json', {g:{'slots':slots} for g in ('T01','T02')})
    content = read_json(batch / 'content.json')
    for g in ('T01', 'T02'):
        content[g].update(image_description='测试蓝色方毯', image_scenes07=['沙发','床','扶手椅','收纳'])
    json_write(batch / 'content.json', content)
    registry, matching, _, _, heroes = iw.context(batch)
    (batch / 'src').mkdir()
    for rows in matching.values():
        for r in rows: (batch / 'src' / f"{r['shop']}-{r['art_id']}.jpg").write_bytes(fake_image())
    resolved, errors = resolve_content(content, registry)
    assert not errors and resolved['T01B']['image_description'] == content['T01']['image_description']
    assert resolved['T01B']['image_scenes07'] == content['T01']['image_scenes07']
    original_plan = cli(ws, 'images-plan', '--batch', 'sample')
    data = read_json(batch / 'image_plan.json')
    assert all(j['status'] == 'missing' for j in data['jobs'])
    assert next(j for j in data['jobs'] if j['group']=='T01B' and j['slot']=='03')['method'] == 'copy'
    assert next(j for j in data['jobs'] if j['slot']=='variante')['method'] == 'derive'
    assert '逐字' in (batch / 'image_plan.md').read_text('utf-8')
    jid = next(j['id'] for j in data['jobs'] if j['group']=='T01' and j['slot']=='01')
    # No --yes: exit 2, needs_confirm and cost; must not read a key or contact an API.
    with patch.object(seedream, 'api_key', side_effect=AssertionError('不能读 Key')), patch.object(seedream, 'generate', side_effect=AssertionError('不能联网')):
        code, result = captured(ws, 'seedream', '--only', jid)
        assert code == 2 and result['needs_confirm'] and result['count']==1 and result['estimated_units']==1.36
        code, result = captured(ws, 'seedream', '--all-missing')
        assert code==2 and result['count']==sum(j['method'] not in ('copy','derive') for j in data['jobs'])
        copied=next(j['id'] for j in data['jobs'] if j['method']=='copy')
        code, result=captured(ws,'seedream','--only',copied)
        assert code==2 and result['count']==0 and result['estimated_units']==0
    assert not (batch / 'seedream_log.json').exists()
    with patch.object(seedream, 'preflight', return_value=dict(account_blockers=[], group_blockers={})), patch.object(seedream, 'api_key', side_effect=Problem('ARK_API_KEY 没设置；请在 Windows 用户环境变量中新增。')):
        code, result = captured(ws, 'seedream', '--only', jid, '--yes')
        assert code==1 and 'ARK_API_KEY' in result['errors'][0] and '环境变量' in result['errors'][0]
    with patch.dict(os.environ, {'ARK_API_KEY': ''}), patch('sys.platform', 'linux'):
        try: seedream.api_key(); raise AssertionError('缺 Key 应报错')
        except Problem as exc: assert 'ARK_API_KEY' in str(exc)
    calls = []
    def fake(prompt, refs, key):
        calls.append((prompt, refs)); return fake_image()
    with patch.object(seedream, 'preflight', return_value=dict(account_blockers=[], group_blockers={})), patch.object(seedream, 'api_key', return_value='仅用于测试'), patch.object(seedream, 'generate', side_effect=fake):
        code, result = captured(ws, 'seedream', '--only', jid, '--yes')
        assert code==0 and result['produced']==[jid] and len(calls)==1
    assert '仅用于测试' not in (batch / 'seedream_log.json').read_text('utf-8')
    print('Seedream：假接口保存、预计单位、无 --yes 退出码 2、不读 Key、不联网、缺 Key 提示通过')
    # All required raw pictures, including non-hero principals; copied/derived items get no raw.
    for job in data['jobs']:
        if job['method'] in ('copy','derive'): continue
        directory = batch / job['raw_dir']; directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{job['slot']}-v01.png").write_bytes(fake_image())
    result = cli(ws, 'images-finish', '--batch', 'sample')
    assert result['count'] and not result['warnings'], result
    for job in data['jobs']:
        path = batch / job['output']
        with Image.open(path) as im:
            assert im.size == (1200,1200) and im.format=='JPEG' and im.mode=='RGB' and im.info['icc_profile']
        assert path.stat().st_size < 3145728
    for v in registry['T01B']:
        for s in iw.SHARED_SLOTS:
            assert (output_dir(batch/'images','T01B',v)/SLOTS[s]).read_bytes() == (output_dir(batch/'images','T01',heroes['T01'])/SLOTS[s]).read_bytes()
    assert cli(ws, 'images-finish', '--batch', 'sample')['count']==0
    # Restoring an omitted non-hero B shared image must work even when its source is unchanged.
    shared=output_dir(batch/'images','T01B',registry['T01B'][0])/SLOTS['03']
    shared.unlink()
    cli(ws,'images-finish','--batch','sample')
    assert shared.read_bytes()==(output_dir(batch/'images','T01',heroes['T01'])/SLOTS['03']).read_bytes()
    cli(ws, 'images-plan', '--batch','sample')
    assert all(j['status']=='existing' for j in read_json(batch/'image_plan.json')['jobs'])
    cli(ws,'images-review','--batch','sample','--ok',jid)
    assert cli(ws,'status','--batch','sample')['image_review']['reviewed']==1
    cli(ws,'images-review','--batch','sample','--redo',jid,'--note','颜色偏了')
    cli(ws,'images-plan','--batch','sample')
    jobs = {j['id']:j for j in read_json(batch/'image_plan.json')['jobs']}
    assert jobs[jid]['status']=='redo' and jobs[jid]['reason']=='颜色偏了' and '颜色偏了' in jobs[jid]['prompt']
    derived = jid.rsplit('/',1)[0]+'/variante'
    assert jobs[derived]['status']=='redo'
    target = batch / jobs[jid]['output']; before = target.read_bytes()
    (batch / jobs[jid]['raw_dir'] / '01-v02.png').write_bytes(fake_image('brown'))
    cli(ws,'images-finish','--batch','sample')
    old = target.parents[3]/'internal/old'
    assert any(p.read_bytes()==before for p in old.glob('01-*'))
    cli(ws,'images-review','--batch','sample','--ok',jid)
    target.write_bytes(fake_image('red'))
    assert not next(j for j in iw.make_plan(batch)['jobs'] if j['id']==jid)['reviewed']
    cli(ws,'images-finish','--batch','sample')  # Repair physical specs after changed content.
    sheet = cli(ws,'images-sheet','--batch','sample','--pending','--name','pending','--group','T01')
    with Image.open(sheet['output']) as im: assert im.width==960 and im.height>0
    cli(ws,'images-review','--batch','sample','--ok','../../bad',ok=False)
    cli(ws,'images-sheet','--batch','sample','--name','../bad',ok=False)
    print('图片：缺/已有/重做、B 组复用和继承、变体派生、规格、备份、断点重跑、审阅失效与拼图通过')
    # Base-overlay path uses script typography; 06 always uses measures_overlay.
    cli(ws,'images-plan','--batch','sample','--mode','base-overlay')
    assert cli(ws,'images-finish','--batch','sample','--only',f'T01/{heroes["T01"]}/02')['count']==1
    assert next(j for j in iw.make_plan(batch,'base-overlay')['jobs'] if j['slot']=='06')['method']=='script'
    hero=heroes['T01']
    raw=batch/f'images/T01/{hero}/internal/raw'
    for p in raw.glob('07*.png'): p.unlink()
    base=batch/f'images/T01/{hero}/internal/base';base.mkdir(parents=True,exist_ok=True)
    for n,c in enumerate('abcd'): (base/f'07-{c}.jpg').write_bytes(fake_image(('navy','brown','green','purple')[n]))
    result=cli(ws,'images-finish','--batch','sample','--only',f'T01/{hero}/07')
    assert result['count']==1 and not result['warnings']
    assert cli(ws,'images-finish','--batch','sample','--only',f'T01/{hero}/07')['count']==0
    # Paid retry budget and redaction of malformed provider failures.
    cli(ws,'images-review','--batch','sample','--redo',jid,'--note','测试重做')
    cli(ws,'images-plan','--batch','sample')
    secret = 'fake-sensitive-value'
    with patch.object(seedream, 'preflight', return_value=dict(account_blockers=[], group_blockers={})), patch.object(seedream,'api_key',return_value=secret), patch.object(seedream,'generate',side_effect=RuntimeError(secret)):
        code, result = captured(ws,'seedream','--only',jid,'--yes')
        assert code==1 and secret not in json.dumps(result)
    with patch.object(seedream, 'preflight', return_value=dict(account_blockers=[], group_blockers={})), patch.object(seedream,'api_key',side_effect=AssertionError('预算耗尽不读 Key')):
        code, result = captured(ws,'seedream','--only',jid,'--yes')
        assert code==1 and '两次' in str(result)
    # Imported junction allows plans/sheets/reviews in root, denies all image writers.
    cli(ws,'new-batch','linked'); linked=ws/'batches/linked'
    for name in ('candidates.csv','variantes.csv','content.json','overlays.json'): shutil.copyfile(batch/name, linked/name)
    (linked/'images').rmdir()
    if os.name=='nt':
        quote=lambda p:"'"+str(p).replace("'","''")+"'"
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',f"New-Item -ItemType Junction -Path {quote(linked/'images')} -Target {quote(batch/'images')} | Out-Null"],check=True,capture_output=True)
    else: (linked/'images').symlink_to(batch/'images', target_is_directory=True)
    before={str(p):p.stat().st_mtime_ns for p in (batch/'images').rglob('*') if p.is_file()}
    cli(ws,'images-plan','--batch','linked')
    cli(ws,'images-sheet','--batch','linked','--only',jid)
    cli(ws,'images-review','--batch','linked','--ok',jid)
    cli(ws,'images-finish','--batch','linked',ok=False)
    result=cli(ws,'seedream','--batch','linked','--only',jid,'--yes',ok=False)
    assert '工作区外' in str(result) or '联接' in str(result)
    assert before=={str(p):p.stat().st_mtime_ns for p in (batch/'images').rglob('*') if p.is_file()}
    legacy=ROOT.parent/'Miravia'
    if (legacy/'scripts/seedream_jobs.py').is_file():
        values,_=constants(legacy/'scripts/seedream_jobs.py'); migrated=import_content(legacy)
        for g, desc in values['PRODUCTS'].items(): assert migrated[g]['image_description']==desc
        for g, scenes in values['SCENES07'].items(): assert migrated[g]['image_scenes07']==scenes
    print('保护：联接图片只读、清单/审阅写批次根、密钥诊断不泄露、两次预算、旧出图常量迁移通过')
    print('IMAGES OK')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try: main()
    except Exception:
        import traceback
        traceback.print_exc()
        print('IMAGES FAILED')
        raise SystemExit(1)
