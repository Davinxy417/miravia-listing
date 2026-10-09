"""keywords:亚马逊/Google 联想解析、合并排序、单边失败、全失败报错(离线假接口)。"""
import io, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from listing_core.common import Problem
from listing_core.keywords import suggest


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


def opener_for(amazon, google):
    def opener(request, timeout):
        url = request.full_url
        if 'amazon' in url:
            if amazon is None: raise OSError('down')
            return Resp(json.dumps({'suggestions': [{'value': v} for v in amazon]}).encode())
        if google is None: raise OSError('down')
        return Resp(json.dumps(['q', google]).encode())
    return opener


def main():
    r = suggest(['ducha filtro'], opener_for(['a', 'b', 'c'], ['c', 'd', 'a']))['suggestions']['ducha filtro']
    assert r['merged'] == ['a', 'c', 'b', 'd'], r
    r = suggest(['x'], opener_for(None, ['z']))
    assert r['suggestions']['x']['merged'] == ['z'] and 'amazon_es' in r['message']
    try: suggest(['x'], opener_for(None, None)); raise AssertionError('should fail')
    except Problem: pass
    try: suggest(['  ']); raise AssertionError('empty seeds')
    except Problem: pass
    print('KEYWORDS OK')


if __name__ == '__main__': main()
