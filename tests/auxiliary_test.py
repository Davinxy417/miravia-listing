"""用临时几何测试图验证迁移后的 Pillow/GPSR 和工作区选择。"""
import copy
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
from helpers import FIXTURES, ROOT, cli, csv_rows, json_write, workspace
from listing_core.common import write_csv
from listing_core.workspace import resolve_workspace, documents_folder


def main():
    ws=workspace('auxiliary-')
    cli(ws,'init');cli(ws,'new-batch','sample')
    batch=ws/'batches/sample'
    shutil.copytree(FIXTURES/'batch',batch,dirs_exist_ok=True)
    cli(ws,'price','--batch','sample')
    labels=cli(ws,'gpsr','--batch','sample')
    assert labels['count']==5 and labels['pdf_pages']==1
    assert len(list((batch/'output/gpsr/labels').glob('*.png')))==5
    pdf=(batch/'output/gpsr/print_A4.pdf').read_bytes()
    assert pdf.startswith(b'%PDF-') and b'/PrintScaling /None' in pdf
    for path in (batch/'output/gpsr/labels').glob('*.png'):
        with Image.open(path) as im:assert im.size==(945,591)
    # Distinct company fixture confirms labels are supplied by this workspace.
    shop=json.loads((ws/'shop.json').read_text('utf-8'))
    shop['suppliers']['3321'].update(company='Empresa de Prueba',address='Calle Prueba 1, Madrid',email='test@example.test')
    json_write(ws/'shop.json',shop)
    cli(ws,'gpsr','--batch','sample')
    assert all(r['fabricante']=='Empresa de Prueba' for r in csv_rows(batch/'output/gpsr/labels/index.csv'))
    print('GPSR：5 张标签、1 页原尺寸 A4 PDF，店铺公司资料和批次文案读取通过')
    cli(ws,'new-batch','media');media=ws/'batches/media'
    for name in ('candidates.csv','variantes.csv'):
        rows=[r for r in csv_rows(batch/name) if r['group']=='T02'];write_csv(media/name,rows)
    slots={
        '01':{'title':''}, 'variante':{'title':''},
        '02':{'title':'Una manta suave','points':[{'icon':'bed','text':'Tejido suave'},{'icon':'house','text':'Uso diario'},{'icon':'hand','text':'Cuidado fácil'}]},
        '03':{'title':'Detalle del tejido'},'04':{'title':'Uso en casa'},'05':{'title':'Otra escena'},
        '06':{'title':'Medidas y contenido'},
        '07':{'title':'Cuatro usos','layout':'2x2','scenes':[{'title':v,'icon':'house'} for v in ('Sofá','Cama','Lectura','Descanso')]},
        '08':{'title':'Vida diaria'},
    }
    json_write(media/'overlays.json',{'T02':{'slots':slots}})
    base=media/'images/T02/unico/internal/base';base.mkdir(parents=True)
    output=media/'images/T02/unico/output/miravia-es/v01';output.mkdir(parents=True)
    im=Image.new('RGB',(1200,1200),'white');ImageDraw.Draw(im).rectangle((300,450,800,900),fill='#777799')
    for name in ('02-puntos.jpg','03-detalle.jpg','04-uso.jpg','05-uso-alternativo.jpg','06-medidas.jpg','07-a.jpg','07-b.jpg','07-c.jpg','07-d.jpg','08-modelo.jpg'):
        im.save(base/name)
    im.save(output/'01-principal.jpg')
    assert not cli(ws,'overlay','--batch','media','--all')['warnings']
    assert cli(ws,'images-collect','--batch','media')['count']==9
    assert cli(ws,'images-urls','--batch','media','--base-url','https://example.test/images')['count']==9
    for path in output.glob('*.jpg'):
        with Image.open(path) as image:assert image.size==(1200,1200)
    cli(ws,'images-urls','--batch','media','--base-url','file:///tmp',ok=False)
    # A junction can be read but never written by migrated image commands.
    import subprocess
    cli(ws,'new-batch','linked');linked=ws/'batches/linked'
    for name in ('candidates.csv','variantes.csv','overlays.json'):shutil.copyfile(media/name,linked/name)
    (linked/'images').rmdir()
    if os.name=='nt':
        quote=lambda p:"'"+str(p).replace("'","''")+"'"
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',f"$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path {quote(linked/'images')} -Target {quote(media/'images')} | Out-Null"],check=True,capture_output=True)
    else:(linked/'images').symlink_to(media/'images',target_is_directory=True)
    before={str(p):p.stat().st_mtime_ns for p in (media/'images').rglob('*') if p.is_file()}
    cli(ws,'images-collect','--batch','linked');cli(ws,'overlay','--batch','linked','--all',ok=False)
    after={str(p):p.stat().st_mtime_ns for p in (media/'images').rglob('*') if p.is_file()}
    assert before==after
    print('图片辅助：叠字、9 个图片槽位、网址生成、目录联接只读保护通过')
    home=ws/'fake-home';home.mkdir()
    json_write(home/'.miravia-listing.json',{'workspace':str(ws/'from-file')})
    with patch('pathlib.Path.home',return_value=home),patch.dict(os.environ,{'MIRAVIA_WS':str(ws/'from-env')}):
        assert resolve_workspace(ws/'explicit')==(ws/'explicit').resolve()
        assert resolve_workspace()==(ws/'from-env').resolve()
        with patch.dict(os.environ,{'MIRAVIA_WS':''}):assert resolve_workspace()==(ws/'from-file').resolve()
    assert documents_folder().is_absolute()
    print('工作区：命令行、环境变量、用户配置优先级及系统文档目录查询通过')
    print('AUXILIARY OK')


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f'AUXILIARY FAILED：{exc}')
        raise SystemExit(1)
