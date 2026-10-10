"""发布/填表共用失败判定，不允许放宽审阅开关放行失败组。"""
from .image_workflow import review_data
from .image_layout import SLOTS, SHARED_SLOTS, hero_variant, output_dir, variant_folders


def group_issues(batch, require_complete=False):
    registry = variant_folders(batch / 'variantes.csv')
    reviews = review_data(batch)['reviews']
    issues = {g: [] for g in registry}
    for jid, record in reviews.items():
        pieces = jid.split('/')
        if len(pieces) != 3 or pieces[0] not in registry or pieces[1] not in registry[pieces[0]]: continue
        group, _, slot = pieces
        if record.get('result') == 'redo' or record.get('severity') in ('major', 'critical'):
            message = f'{jid} 审阅失败：{record.get("note", "请重新审阅")}；该组只出草稿，不发布。'
            issues[group].append(message)
            if slot in SHARED_SLOTS and group + 'B' in registry:
                issues[group + 'B'].append('共用来源失败：' + message)
    if require_complete:
        for group, variants in registry.items():
            hero = hero_variant(group, variants, batch / 'images')
            for variant in variants:
                required = dict(SLOTS) if variant == hero else {'01': SLOTS['01']}
                required['variante'] = 'variante.jpg'
                for slot, filename in required.items():
                    if not (output_dir(batch / 'images', group, variant) / filename).is_file():
                        issues[group].append(f'{group}/{variant}/{slot} 缺成品；八图及变体主图不齐，只出草稿。')
    return {g: reasons for g, reasons in issues.items() if reasons}
