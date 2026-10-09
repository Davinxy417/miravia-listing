"""离线冒烟：真实 CLI、独立业务检查、列移动及错误输出回归。"""
import copy
import hashlib
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from decimal import Decimal, ROUND_CEILING
from zipfile import ZipFile

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.formula.translate import Translator
from openpyxl.utils import column_index_from_string, get_column_letter

from helpers import FIXTURES, ROOT, cli, csv_rows, json_write, workspace

NS = {'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def checksum_ok(ean):
    return (isinstance(ean,str) and ean.isascii() and ean.isdigit() and len(ean) in (8,12,13,14)
            and (sum(int(d)*(3 if (len(ean)-i)%2==0 else 1) for i,d in enumerate(ean[:-1]))+int(ean[-1]))%10==0)


def independent_zip(template, output):
    with ZipFile(template) as before, ZipFile(output) as after:
        assert before.namelist()==after.namelist()
        assert after.testzip() is None
        assert before.read('xl/vbaProject.bin')==after.read('xl/vbaProject.bin')
        changed=[name for name in before.namelist() if before.read(name)!=after.read(name)]
        assert len(changed)==1 and changed[0].startswith('xl/worksheets/')
        a,b=(ET.fromstring(z.read(changed[0])) for z in (before,after))
        sa,sb=(x.find('m:sheetData',NS) for x in (a,b))
        assert [ET.tostring(r) for r in sa if int(r.get('r'))<5]==[ET.tostring(r) for r in sb if int(r.get('r'))<5]
        for x in (a,b):
            for tag in ('sheetData','dimension'):x.remove(x.find('m:'+tag,NS))
        assert ET.tostring(a)==ET.tostring(b), '非数据区发生变化'


def check_output(ws, batch, template):
    shop=json.loads((ws/'shop.json').read_text('utf-8'))
    raw=json.loads((batch/'content.json').read_text('utf-8'))
    rows=csv_rows(batch/'priced.csv');candidates=csv_rows(batch/'candidates.csv')
    assert len(rows)==len(candidates)==5
    for a,b in zip(candidates,rows):assert all(a[k]==b[k] for k in a)
    p=shop['pricing']
    keep=1-sum(Decimal(str(x)) for x in p['fees'].values())-Decimal(str(p['coupon_rate']))
    for r in rows:
        cost=Decimal(r['unit_cost_ex_iva'])*Decimal(str(p['cost_factor']))*Decimal(r['pack_qty'])
        weight=max(Decimal(r['weight_kg']),Decimal(r['len_cm'])*Decimal(r['wid_cm'])*Decimal(r['hei_cm'])/Decimal(str(p['volumetric_divisor'])))
        ship=next(Decimal(str(fee)) for limit,fee in p['ship_tiers'] if weight<=Decimal(str(limit)))
        profit=max(Decimal(str(p['min_profit'])),cost*Decimal(str(p['profit_rate'])))
        price=((cost+Decimal(str(p['packaging']))+ship+profit)/keep).to_integral_value(rounding=ROUND_CEILING)-Decimal('.01')
        assert price==Decimal(r['price'])==Decimal(r['original_price'])
        assert Decimal(r['profit_with_coupon'])>=Decimal(str(p['min_profit']))
    output=batch/'output/miravia_upload.xlsm'
    independent_zip(template,output)
    wb=openpyxl.load_workbook(output,keep_vba=True)
    try:
        sheet=wb['Pantilla']
        headers={str(c.value):c.column for c in sheet[1] if c.value}
        col=lambda h:headers[h]
        stock=next(k for k in headers if k.startswith('Stock'))
        assert sheet.max_row==len(rows)+4
        source={r['ean']:r for r in rows};seen=set();skus=set();group_cells=defaultdict(list)
        mappings={r['ean']:r['variante'] for r in csv_rows(batch/'variantes.csv')}
        urls={(r['group'],r['variante'],r['slot']):r['url'] for r in csv_rows(batch/'images.csv')}
        for n in range(5,sheet.max_row+1):
            get=lambda h:sheet.cell(n,col(h)).value
            ean=get('Código EAN');assert checksum_ok(ean) and ean not in seen;seen.add(ean)
            src=source[ean];group=src['group'];item={**raw.get(group.removesuffix('B'),{}),**raw[group]}
            assert get('Group No')==group
            assert get('Categoría')==item['category']
            for h,k in [('Nombre del producto','title'),('Descripción','description'),('Atributos adicionales','attributes'),('¿El producto cuenta con advertencia de seguridad?','warning')]:assert get(h)==item[k]
            assert (get('Contenido de la advertencia de seguridad') or '')==item['warning_text']
            assert get('Marca')==shop['brand']
            expected=f"{shop['sku']['prefix']}{src['shop']}-{src['art_id']}-{ean}"+(f"-P{src['pack_qty']}" if int(src['pack_qty'])>1 else '')
            assert get('SKU de vendedor')==expected and expected not in skus;skus.add(expected)
            ean_cell=sheet.cell(n,col('Código EAN'))
            assert ean_cell.data_type=='s' and ean_cell.number_format=='@'
            for h in ('Precio original','Precio en España'):
                cell=sheet.cell(n,col(h));assert cell.data_type=='n' and Decimal(str(cell.value))==Decimal(src['price'])
            assert get('Precio con descuento en España') is None
            assert type(get(stock)) is int and get(stock)==shop['stock_default']
            for h,k in [('Peso del paquete','weight_kg'),('Longitud del paquete','len_cm'),('Ancho del paquete','wid_cm'),('Altura del paquete','hei_cm')]:assert Decimal(str(get(h)))==Decimal(src[k])
            maker=shop['suppliers'][src['shop']]
            assert get('Fabricante')==maker['fabricante'] and get('Persona Responsable de la UE')==maker['responsable']
            assert get('Materiales peligrosos')=='Ninguno'
            hero={'T01':'gris','T01B':'azul','T02':'unico'}[group]
            for i in range(1,9):assert get(f'Imágenes de producto{i}')==urls[group,hero,f'{i:02d}']
            assert get('Image per Variation')==urls[group,mappings[ean],'variante']
            assert 'gpsr' not in get('Image per Variation').lower()
            for h in ('Código EAN','Precio original','Precio en España',stock,'Peso del paquete','Longitud del paquete','Fabricante'):
                assert not sheet.cell(n,col(h)).protection.locked,(h,'被锁定')
            if group=='T02':assert all(get(h) is None for h in ('Variation Name1','Option for Variation1','Variation Name2','Option for Variation2'))
            else:assert get('Variation Name1')==src['var1_name'] and get('Option for Variation1')==src['var1_value']
            group_cells[group].append(n)
        assert seen==set(source) and len(group_cells)==3
        for indexes in group_cells.values():assert indexes==list(range(min(indexes),max(indexes)+1))
        assert all(raw['T01B']['title'].startswith('Pack de 2 ') and r['pack_qty']=='2' for r in rows if r['group']=='T01B')
        print(f'独立检查：{len(rows)} SKU / {len(group_cells)} 组，条码、价格、文案、图片网址、样式、宏和 ZIP 均通过')
    finally:wb.close()


def shifted_template(source,target):
    """可见列整体后移一列；隐藏下拉不移动，公式局部引用随之移动。"""
    def shift(ref):
        return re.sub(r'(\$?)([A-Z]+)(\$?\d*)',lambda m:m[1]+get_column_letter(column_index_from_string(m[2])+1)+m[3],ref)
    with ZipFile(source) as z,ZipFile(target,'w') as out:
        for member in z.infolist():
            data=z.read(member.filename)
            # Workbook first sheet is identified by its actual headers, not ZIP member number.
            if member.filename.startswith('xl/worksheets/') and member.filename.endswith('.xml') and b'<sheetData' in data:
                xml=ET.fromstring(data)
                # The visible Pantilla has dataValidations; hide sheets do not.
                if xml.find('m:dataValidations',NS) is not None and xml.find('m:sheetProtection',NS) is not None:
                    for c in xml.findall('m:sheetData/m:row/m:c',NS):c.set('r',shift(c.get('r')))
                    for c in xml.findall('m:cols/m:col',NS):
                        c.set('min',str(int(c.get('min'))+1));c.set('max',str(int(c.get('max'))+1))
                    for d in xml.findall('m:dataValidations/m:dataValidation',NS):
                        d.set('sqref',shift(d.get('sqref')))
                        for f in d:
                            if not f.text:continue
                            try:
                                tokens=Tokenizer('='+f.text)
                                for token in tokens.items:
                                    if token.subtype=='RANGE' and '!' not in token.value:
                                        token.value=Translator.translate_range(token.value,0,1)
                                f.text=tokens.render().lstrip('=')
                            except Exception:pass  # literal validation values have no references
                    for m in xml.findall('m:mergeCells/m:mergeCell',NS):m.set('ref',shift(m.get('ref')))
                    dim=xml.find('m:dimension',NS);dim.set('ref','A1:'+shift(dim.get('ref').split(':')[-1]))
                    # Extra column is intentionally unknown to the writer.
                    row=xml.find('m:sheetData/m:row',NS)
                    c=ET.Element('{'+NS['m']+'}c',r='A1',t='inlineStr')
                    ET.SubElement(ET.SubElement(c,'{'+NS['m']+'}is'),'{'+NS['m']+'}t').text='Columna adicional'
                    row.insert(0,c)
                    ET.register_namespace('',NS['m'])
                    data=ET.tostring(xml,encoding='utf-8')
            out.writestr(member,data)


def snapshot(path):
    return {str(p.relative_to(path)):(p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()) for p in path.rglob('*') if p.is_file()}


def main():
    ws=workspace('smoke-')
    cli(ws,'init')
    # All assets come from fixtures; there is no dependency on old project or network.
    shutil.copyfile(FIXTURES/'shop.json',ws/'shop.json')
    before=(ws/'shop.json').read_bytes();cli(ws,'init');assert (ws/'shop.json').read_bytes()==before
    shop=json.loads(before)
    template=ws/'template'/shop['template']
    shutil.copyfile(FIXTURES/'template'/shop['template'],template)
    cli(ws,'new-batch','sample')
    batch=ws/'batches/sample';shutil.copytree(FIXTURES/'batch',batch,dirs_exist_ok=True)
    cli(ws,'price','--batch','sample')
    assert cli(ws,'fill','--batch','sample')['count']==5
    check_output(ws,batch,template)
    snap=snapshot(ws);cli(ws,'check','--batch','sample');assert snapshot(ws)==snap,'check 写入了文件'
    assert cli(ws,'status','--batch','sample')['steps']['output']['fresh']
    assert any('Mantas y colchas' in s for s in cli(ws,'categories','--search','Mantas')['categories'])
    # Movement is tested on a temporary copy, never by rewriting fixture/template source.
    moved=ws/'template/shifted.xlsm';shifted_template(template,moved)
    changed=copy.deepcopy(shop);changed['template']=moved.name;json_write(ws/'shop.json',changed)
    cli(ws,'fill','--batch','sample');check_output(ws,batch,moved)
    from listing_core.headers import resolve_columns,HEADERS
    wb=openpyxl.load_workbook(moved,keep_vba=True)
    try:
        cols=resolve_columns(wb);sheet=wb['Pantilla'];col=cols['ean'];sheet.cell(1,col).value='不存在的条码列'
        try:resolve_columns(wb);raise AssertionError('缺表头没有报错')
        except ValueError as e:assert HEADERS['ean'] in str(e)
        sheet.cell(1,col).value=HEADERS['ean'];sheet.cell(1,1).value=HEADERS['ean']
        try:resolve_columns(wb);raise AssertionError('重复表头没有报错')
        except ValueError as e:assert '2 列' in str(e)
    finally:wb.close()
    print('模板回归：列移动、额外列、库存前缀、缺失/重复表头均通过')
    # Failure aggregation and output preservation.
    json_write(ws/'shop.json',shop)
    original=(batch/'content.json').read_bytes();bad=json.loads(original)
    bad['T01']['title']='短';bad['T02']['description']='短';json_write(batch/'content.json',bad)
    bad_shop=copy.deepcopy(shop);bad_shop['suppliers']['3321']['fabricante']='下拉里不存在的制造商';json_write(ws/'shop.json',bad_shop)
    original_urls=(batch/'images.csv').read_bytes()
    (batch/'images.csv').write_bytes(original_urls.replace(b'01-principal.jpg',b'bad-image.png',1))
    original_prices=(batch/'priced.csv').read_bytes()
    from listing_core.common import write_csv
    bad_prices=csv_rows(batch/'priced.csv');bad_prices[0]['ean']=bad_prices[1]['ean']='123';write_csv(batch/'priced.csv',bad_prices)
    output_before=(batch/'output/miravia_upload.xlsm').read_bytes()
    result=cli(ws,'check','--batch','sample',ok=False)
    assert any('T01' in e and 'title' in e for e in result['errors'])
    assert any('T02' in e and 'description' in e for e in result['errors'])
    assert any('fabricante' in e for e in result['errors'])
    assert any('images.csv' in e for e in result['errors'])
    assert any('条码' in e and '无效' in e for e in result['errors'])
    assert any('条码' in e and '重复' in e for e in result['errors'])
    cli(ws,'fill','--batch','sample',ok=False)
    assert (batch/'output/miravia_upload.xlsm').read_bytes()==output_before
    (batch/'content.json').write_bytes(original)
    (batch/'images.csv').write_bytes(original_urls)
    (batch/'priced.csv').write_bytes(original_prices)
    bad_shop=copy.deepcopy(shop);del bad_shop['pricing']['coupon_rate'];del bad_shop['stock_default'];json_write(ws/'shop.json',bad_shop)
    result=cli(ws,'price','--batch','sample',ok=False)
    assert any('coupon_rate' in e for e in result['errors']) and any('stock_default' in e for e in result['errors'])
    json_write(ws/'shop.json',shop)
    cli(ws,'new-batch','../escape',ok=False)
    cli(ws,'fill',ok=False)
    cli(ws,'不存在',ok=False)
    for cmd in ('init','new-batch','import-legacy','price','fill','check','status','categories','gpsr','overlay','images-collect','images-urls','yollgo-login','fetch','yollgo-search','build'):
        assert cli(ws,cmd,'--help')['help']
    assert cli(ws,'--help')['help']
    print('命令回归：全部帮助、JSON、配置缺项、批量报错、失败保留输出和只读检查均通过')
    print('SMOKE OK')
    return 0


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:raise SystemExit(main())
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f'SMOKE FAILED：{exc}')
        raise SystemExit(1)
