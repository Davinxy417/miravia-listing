"""A5 配置与空批次报告；只用仓库 .tmp 数据。"""
import copy
from helpers import cli, json_write, workspace
from listing_core.common import read_json
from listing_core.workspace import AUTO_DEFAULTS, load_shop


def main():
    ws = workspace('auto-report-')
    cli(ws, 'init'); cli(ws, 'new-batch', 'empty')
    original = read_json(ws / 'shop.json')
    old = copy.deepcopy(original); old.pop('auto')
    json_write(ws / 'shop.json', old)
    before = (ws / 'shop.json').read_bytes()
    assert load_shop(ws)['auto'] == AUTO_DEFAULTS and (ws / 'shop.json').read_bytes() == before
    for key, value in [('enabled', 'true'), ('budget_units_per_group', 0), ('budget_units_per_batch', -1),
                       ('budget_units_per_group', True), ('max_groups_per_file', 0.5)]:
        bad = copy.deepcopy(original); bad['auto'][key] = value
        json_write(ws / 'shop.json', bad)
        result = cli(ws, 'report', '--batch', 'empty', ok=False)
        assert key in str(result['errors']), result
    bad = copy.deepcopy(original); del bad['auto']['budget_units_per_group']
    json_write(ws / 'shop.json', bad)
    assert 'budget_units_per_group' in str(cli(ws, 'report', '--batch', 'empty', ok=False)['errors'])
    json_write(ws / 'shop.json', original)
    batch = ws / 'batches/empty'
    result = cli(ws, 'report', '--batch', 'empty')
    assert not result['upload_ready'] and result['count'] == 0 and result['outputs'] == []
    assert '没做到这一步' in (batch / '早上看这里.md').read_text('utf-8')
    notes = '# 自动决定\n保留原文  双空格。\n'
    (batch / 'notes.md').write_text(notes, 'utf-8')
    json_write(batch / 'seedream_log.json', {'G01/crema/01': [dict(state='failed')],
        'G01B/crema/02': [dict(state='started', units=1.45)], 'over_budget': ['G01/crema/03']})
    json_write(batch / 'image_review.json', dict(version=1, reviews={'G01/crema/01': dict(result='redo', note='颜色不对')}))
    result = cli(ws, 'report', '--batch', 'empty')
    assert result['spent_units'] == 2.81 and result['group_units'] == {'G01': 1.36, 'G01B': 1.45}
    assert result['over_budget'] == ['G01/crema/03'] and len(result['image_problems']) == 3
    assert (batch / '早上看这里.md').read_text('utf-8').endswith(notes)
    # A directory with none of the batch scaffold is still reportable.
    for name in ('candidates.csv', 'priced.csv', 'content.json', 'variantes.csv'):
        (batch / name).unlink()
    assert not cli(ws, 'report', '--batch', 'empty')['upload_ready']
    # An old output alone cannot be mistaken for a complete batch.
    (batch / 'output/miravia_upload.xlsm').write_bytes(b'old incomplete test output')
    result = cli(ws, 'report', '--batch', 'empty')
    assert not result['upload_ready'] and any('先 price' in t for t in result['todos'])
    assert '--auto' in cli(ws, 'seedream', '--help')['help']
    for command in ('fetch', 'yollgo-search', 'yollgo-login'):
        assert '--auto' in cli(ws, command, '--help')['help']
    print('AUTO OK：配置默认与校验、空批次报告、累计单位、问题 id、原文待办和新参数帮助通过')


if __name__ == '__main__':
    main()
