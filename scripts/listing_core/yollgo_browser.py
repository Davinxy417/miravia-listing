"""只通过已登录网页调用友购自身函数；不接触密码、签名或 token。"""
from contextlib import contextmanager
import time

from .common import Problem, inside, require

URL = 'https://app.yollgo.com'
USER_ID = "() => angular.element(document.querySelector('[ng-app]')).injector().get('storageFactory').userid()"
READY = "() => !!(window.angular && document.querySelector('[ng-app]') && angular.element(document.querySelector('[ng-app]')).injector())"
CALL = """async ({method, params}) => {
    const af = angular.element(document.querySelector('[ng-app]')).injector().get('ajaxFactory');
    const response = method === 'shops' ? await af.shops() : await af[method](params);
    // $http wraps the body as response.data; the body itself carries code 1000 on success.
    const body = response && response.data && 'code' in response.data ? response.data : response;
    // Never transfer authentication data out of the browser.
    if (!body || Number(body.code) !== 1000) return {ok: false};
    const key = method === 'shops' ? 'shop_lists' : 'articulo_lists';
    if (!Array.isArray(body[key])) return {ok: false};
    const result = {data: body};
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


ALIVE = """async () => {
    try {
        const af = angular.element(document.querySelector('[ng-app]')).injector().get('ajaxFactory');
        const response = await af.shops();
        const body = response && response.data && 'code' in response.data ? response.data : response;
        return !!body && Number(body.code) === 1000;
    } catch (e) { return false; }
}"""


def session_alive(page):
    # 本地存的用户 id 可能是过期的;只有真的查一次批发商列表成功才算登录着。
    try:
        uid = page.evaluate("() => { try { return (" + USER_ID + ")(); } catch (e) { return null; } }")
        return uid is not None and str(uid) != '-1' and bool(page.evaluate(ALIVE))
    except Exception:
        return False


LOGIN_TIMEOUT = '友购自动登录没成功(可能要验证码或密码失效);请醒来后运行 mlist yollgo-login 手动登录,再重跑 fetch。'
PASSWORD = 'input[ng-model="input.password"]'
AUTOFILLED = """() => {
    const el = document.querySelector('input[ng-model="input.password"]');
    return !!el && (el.matches(':autofill') || el.matches(':-webkit-autofill'));
}"""
CAPTCHA = """() => {
    const visible = el => !!(el.getClientRects().length);
    return Array.from(document.querySelectorAll('[class*="captcha"], [id*="captcha"], [class*="slider"], iframe[src*="captcha"]')).some(visible)
      || /验证码|滑块|滑动验证/.test(document.body ? document.body.innerText : '');
}"""


def auto_login(page, autofill_timeout=15, login_timeout=30):
    """One click attempt using browser autofill state only; never inspect inputs."""
    try:
        if '/#/account/login' not in page.url:
            page.goto(URL + '/#/account/login', wait_until='domcontentloaded', timeout=60000)
        deadline = time.monotonic() + autofill_timeout
        while True:
            if page.is_closed() or page.evaluate(CAPTCHA): return False
            if page.evaluate(AUTOFILLED): break
            if time.monotonic() >= deadline: return False
            page.wait_for_timeout(250)
        page.locator(PASSWORD).click(timeout=5000)
        page.wait_for_timeout(500)
        if page.evaluate(CAPTCHA): return False
        page.locator('button[ng-click="login()"]').click(timeout=5000)
        deadline = time.monotonic() + login_timeout
        while True:
            if session_alive(page): return True
            if page.is_closed() or page.evaluate(CAPTCHA) or time.monotonic() >= deadline: return False
            page.wait_for_timeout(500)
    except Exception:
        # Page navigation/autofill support errors fall back to manual login.
        return False


def wait_for_login(page, timeout=None):
    # 登录成功时 App 会跳转/重载页面,单次 wait_for_function 会因页面上下文销毁而报错;轮询并容忍跳转。
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        require(not page.is_closed(), '友购窗口已关闭，还没登录成功；请重新运行刚才的命令。')
        if session_alive(page):
            return
        if deadline is not None and time.monotonic() >= deadline:
            raise Problem(LOGIN_TIMEOUT)
        time.sleep(2 if deadline is None else min(2, max(0, deadline - time.monotonic())))


@contextmanager
def session(ws, login=False, notify=None, unattended=False, login_timeout=600):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Problem('友购命令需要 playwright；请运行 python -m pip install -r requirements.txt。使用系统 Edge，不要运行 playwright install。') from None
    profile = inside(ws, ws / '.yollgo-browser')
    profile.mkdir(parents=True, exist_ok=True)
    context = None
    with sync_playwright() as pw:
        try:
            # 友购同一账号同一时间只认一个登录(手机 App、别的浏览器登录都会把这里挤掉,接口回 401)。
            # 所以一律开可见窗口:没登录就请用户在这个窗口里登录(用户把密码存在这个 Edge 里,点一下即可),
            # 登录后在同一个窗口里查完再关。
            context = pw.chromium.launch_persistent_context(str(profile), channel='msedge', headless=False)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(URL, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_function(READY, timeout=60000)
            if not session_alive(page):
                if not auto_login(page):
                    if notify: notify('友购自动登录没成功；请在弹出的窗口里手动登录，可能需要验证码。' + ('最多等待 10 分钟。' if unattended else '登录后程序会自动接着做，窗口别关。'))
                    wait_for_login(page, timeout=login_timeout if unattended else None)
                page.wait_for_timeout(3000)  # 让 App 把登录资料写完
                require(session_alive(page), '友购登录后查询仍被拒绝;请关掉窗口重新运行,登录后不要切换账号。')
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


def login(ws, notify=None, unattended=False):
    with session(ws, login=True, notify=notify, unattended=unattended):
        return dict(message='已登录。注意:友购关掉窗口后登录会失效,fetch/yollgo-search 会自己弹窗,没登录时在窗口里再登一次即可。')
