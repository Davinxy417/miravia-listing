"""买家搜索词:亚马逊西班牙 + Google 西班牙搜索框联想(公开接口,只读)。
米拉维亚自己的联想会对自动浏览器弹验证码,不去绕;亚马逊.es 的搜索习惯和米拉维亚买家最接近。"""
import json
import urllib.parse
import urllib.request

from .common import Problem

SOURCES = {
    'amazon_es': ('https://completion.amazon.es/api/2017/suggestions?mid=A1RKKUPIHCS9HS&alias=aps&prefix={q}',
                  lambda d: [s['value'] for s in d.get('suggestions', [])]),
    'google_es': ('https://suggestqueries.google.com/complete/search?client=firefox&hl=es&gl=es&q={q}',
                  lambda d: list(d[1])),
}


def fetch(url, parse, opener=urllib.request.urlopen):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with opener(request, timeout=15) as response:
        return parse(json.loads(response.read().decode('utf-8', 'replace')))


def suggest(seeds, opener=urllib.request.urlopen):
    seeds = [s.strip() for s in seeds if s.strip()]
    if not seeds: raise Problem('请给至少一个种子词,如 "alcachofa ducha"。')
    result, failed = {}, set()
    for seed in seeds:
        per = {}
        for name, (template, parse) in SOURCES.items():
            try: per[name] = fetch(template.format(q=urllib.parse.quote(seed)), parse, opener)
            except Exception: per[name] = []; failed.add(name)
        # 两边都出现的词排前面:这是最多人搜的说法
        both = [w for w in per['amazon_es'] if w in per['google_es']]
        per['merged'] = list(dict.fromkeys(both + per['amazon_es'] + per['google_es']))
        result[seed] = per
    if failed and not any(v['merged'] for v in result.values()):
        raise Problem('搜索联想都没拿到;请检查网络后重试。')
    return dict(suggestions=result, message=f'查了 {len(seeds)} 个词' + (f';{"、".join(sorted(failed))} 部分失败' if failed else ''))
