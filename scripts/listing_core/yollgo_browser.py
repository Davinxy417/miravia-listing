"""只通过已登录网页调用友购自身函数；不接触密码、签名或 token。"""
from contextlib import contextmanager

from .common import Problem, inside, require

URL = 'https://app.yollgo.com'
USER_ID = "() => angular.element(document.querySelector('[ng-app]')).injector().get('storageFactory').userid()"
READY = "() => !!(window.angular && document.querySelector('[ng-app]') && angular.element(document.querySelector('[ng-app]')).injector())"
CALL = """async ({method, params}) => {
    const af = angular.element(document.querySelector('[ng-app]')).injector().get('ajaxFactory');
    const result = method === 'shops' ? await af.shops() : await af[method](params);
    // Never transfer authentication data out of the browser.
    if (Number(result.code) !== 1000) return {ok: false};
    const key = method === 'shops' ? 'shop_lists' : 'articulo_lists';
    if (!result.data || !Array.isArray(result.data[key])) return {ok: false};
    const publicFields = ['shopId','name','namees','des','tel','baseurl','imgurl'];
    // Product fields are kept raw, including future public product attributes.
    // Authentication envelopes never leave the page. Reject credential-named
    // nested fields as well, rather than writing them into batch files.
    const clean = value => Array.isArray(value) ? value.map(clean) :
      value && typeof value === 'object' ? Object.fromEntries(Object.entries(value)
        .filter(([k]) => !/token|password|passwd|cookie|credential|authorization|session|signature|secret/i.test(k))
        .map(([k,v]) => [k, clean(v)])) : value;
    return {ok: true, items: result.data[key].map(item => method === 'shops'
      ? Object.fromEntries(publicFields.filter(k => k in item).map(k => [k, item[k]]))
      : clean(item))};
}"""


class BrowserClient:
    def __init__(self, page):
        self.page = page

    def call(self, method, params=None):
        try:
            result = self.page.evaluate(CALL, dict(method=method, params=params))
        except Exception:
            raise Problem('友购页面查询失败；请检查网络，重新运行 yollgo-login 后重试。') from None
        require(result.get('ok'), '友购未返回成功结果；请重新运行 yollgo-login，确认能正常访问该批发商后重试。')
        require(isinstance(result.get('items'), list), '友购返回的数据格式变化；请检查网页后重试。')
        return result['items']

    def shops(self):
        return self.call('shops')

    def search(self, shop_id, keyword):
        # Search all pages; otherwise an exact match can be hidden after row 20.
        items, offset, last_page = [], 0, None
        for _ in range(1000):
            page = self.call('select', dict(shopid=shop_id, content=keyword, type=0, **{'from': offset, 'to': offset + 20}))
            if not page: return items
            signature = tuple((str(p.get('artId')), str(p.get('bianhao')), str(p.get('usercode'))) for p in page)
            require(signature != last_page, f'友购批发商 {shop_id} 搜索分页没有前进；请缩小关键词后重试。')
            items.extend(page)
            if len(page) < 20: return items
            last_page, offset = signature, offset + 20
        raise Problem(f'友购批发商 {shop_id} 搜索结果过多；请缩小关键词。')

    def image(self, url):
        # Public image download only; product APIs always run in the App itself.
        from urllib.request import urlopen
        try:
            with urlopen(url, timeout=30) as response:
                data = response.read(20 * 1024 * 1024 + 1)
            require(len(data) <= 20 * 1024 * 1024, '友购原图超过 20MB；请检查图片地址。')
            return data
        except Problem:
            raise
        except Exception:
            raise Problem('友购原图下载失败；请检查网络后重新运行 fetch。') from None


@contextmanager
def session(ws, login=False, notify=None):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Problem('友购命令需要 playwright；请运行 python -m pip install -r requirements.txt。使用系统 Edge，不要运行 playwright install。') from None
    profile = inside(ws, ws / '.yollgo-browser')
    profile.mkdir(parents=True, exist_ok=True)
    context = None
    with sync_playwright() as pw:
        try:
            context = pw.chromium.launch_persistent_context(str(profile), channel='msedge', headless=not login)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(URL, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_function(READY, timeout=60000)
            if login:
                if notify: notify('请在弹出的窗口里登录友购')
                page.wait_for_function("() => { const id = (" + USER_ID + ")(); return id != null && String(id) !== '-1'; }", timeout=0)
            else:
                uid = page.evaluate(USER_ID)
                require(uid is not None and str(uid) != '-1', '友购尚未登录；请先运行 python scripts/mlist.py yollgo-login --ws "工作区路径"。')
        except Problem:
            if context is not None: context.close()
            raise
        except Exception:
            if context is not None: context.close()
            raise Problem('友购浏览器未完成操作；请确认系统 Edge 已安装、网络正常、登录窗口未提前关闭，且没有其他友购命令占用同一工作区。') from None
        try:
            # Business/file errors must retain their own actionable diagnostics.
            yield BrowserClient(page)
        finally:
            if context is not None: context.close()


def login(ws, notify=None):
    with session(ws, login=True, notify=notify):
        return dict(message='已登录。友购窗口已关闭，后续命令会使用本工作区的登录状态。')
