"""UI 步骤的执行：用 Playwright 驱动真浏览器，把页面做成"能判定的快照"。

两条边界：
- 懒加载：没装 playwright 时 API 用例照跑，只在真遇到 UI 用例时报缺依赖
- 快照口径与 API 对称：{url, title, text, elements} 直接喂 core/asserts.evaluate，
  判定规则不在这里复制一份

为什么是"快照"而不是直接返回元素对象：断言结果要能存库、能复跑对比。
把页面变成字符串再判，跟 API 把响应体变成文本再判是同一套思路——
差别只在取值来源，不在规则。

被测系统是 uni-app 编译的 H5（<uni-view>/<uni-button> 这类自定义标签），
这些标签没有隐式 ARIA role，所以定位方式留了 text/css/role 三种，
哪个稳用哪个，由录制时的事实决定，不预设。
"""

import os

SNAPSHOT_TEXT_LIMIT = 4000

# 被测前端是固定 420px 宽的 H5（pages.config.ts 里锁的），
# 默认用移动端 UA + 同宽视口，页面布局才跟人手点时一致。
DEFAULT_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
              "Mobile/15E148 Safari/604.1")
DEFAULT_VIEWPORT = (420, 900)


class UiError(Exception):
    """UI 步骤执行失败：浏览器起不来 / 元素找不到 / 页面跳走。"""


def available():
    """返回 (是否可用, 原因)。runner 启动时用它决定要不要提示装依赖。"""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False, ("没装 playwright（pip install playwright && "
                       "playwright install chromium）")
    return True, ""


def target_key(target):
    """步骤的 target 与 checks 里 element.path 用同一个键，才对得上。

    字符串 target 在 core/steps.py 里已经被规范成 {"text": ...}，
    这里的 text 值就是人写用例时看到的那个词。
    """
    if isinstance(target, str):
        return target
    if not isinstance(target, dict):
        return str(target)
    if target.get("text"):
        return str(target["text"])
    if target.get("css"):
        return str(target["css"])
    if target.get("role"):
        name = target.get("name") or ""
        return f"{target['role']}:{name}" if name else str(target["role"])
    return str(target)


def _locator(page, target):
    """把 target 变成 Playwright 定位器。三种方式按显式字段分派，不猜。"""
    t = target if isinstance(target, dict) else {"text": str(target)}
    if t.get("css"):
        return page.locator(str(t["css"])).first
    if t.get("role"):
        if t.get("name"):
            return page.get_by_role(str(t["role"]), name=str(t["name"])).first
        return page.get_by_role(str(t["role"])).first
    return page.get_by_text(str(t.get("text") or ""), exact=False).first


class Session:
    """一个 run 一个 Session：cookie、登录态、UA 都复用。

    每条用例都新起浏览器的话，SPA 首屏要重跑一次，21 条用例光启动就几百秒。
    """

    def __init__(self, base_url, timeout_ms=15000, headless=True,
                 viewport=DEFAULT_VIEWPORT, ignore_https_errors=True,
                 user_agent=None):
        self.base_url = (base_url or "").rstrip("/")
        self.timeout_ms = int(timeout_ms)
        self.headless = bool(headless)
        self.viewport = viewport or DEFAULT_VIEWPORT
        self.ignore_https_errors = bool(ignore_https_errors)
        self.user_agent = user_agent or DEFAULT_UA
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None
        # 见过就记着：后面步骤要断言前面出现过的元素时，不用重复声明 target
        self._seen = {}

    # ---- 生命周期 ---------------------------------------------------
    @property
    def page(self):
        """给调试脚本直接操作用（录选择器、看 DOM）；正式执行路径不依赖它。"""
        return self._page

    def open(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise UiError("没装 playwright：pip install playwright && "
                          "playwright install chromium")
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self.headless)
            self._ctx = self._browser.new_context(
                viewport={"width": self.viewport[0], "height": self.viewport[1]},
                ignore_https_errors=self.ignore_https_errors,
                user_agent=self.user_agent,
            )
            self._ctx.set_default_timeout(self.timeout_ms)
            self._page = self._ctx.new_page()
        except Exception as exc:                  # noqa: BLE001 启动失败原因照原样带出
            self.close()
            raise UiError(f"浏览器启动失败：{exc}")
        return self

    def close(self):
        """幂等关闭；任何一步失败都不能挡住后面的清理。"""
        for obj, name in ((self._ctx, "close"), (self._browser, "close"),
                          (self._pw, "stop")):
            if obj is None:
                continue
            try:
                getattr(obj, name)()
            except Exception:                     # noqa: BLE001
                pass
        self._pw = self._browser = self._ctx = self._page = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc_info):
        self.close()
        return False

    # ---- 动作 -------------------------------------------------------
    def goto(self, path):
        url = self.base_url + path
        self._page.goto(url, wait_until="domcontentloaded")
        # 单页应用的路由守卫是异步的：domcontentloaded 时可能还停在 /#/，
        # 几百毫秒后才重定向到登录页。不等这一步，"打开首页"的断言会打在
        # 跳转前的旧地址上——实测就是这么 false fail 的（run 1 / case 142）。
        # 用 networkidle 把这次跳转吃掉；页面有长轮询时永远到不了 networkidle，
        # 所以超时兜底，不能死等。
        try:
            self._page.wait_for_load_state(
                "networkidle", timeout=min(self.timeout_ms, 8000))
        except Exception:                     # noqa: BLE001 常驻请求的页面到不了 idle
            pass
        return self._page.url

    def click(self, target):
        loc = _locator(self._page, target)
        loc.wait_for(state="visible")
        loc.click()
        self._seen[target_key(target)] = target

    def fill(self, target, value):
        loc = _locator(self._page, target)
        loc.wait_for(state="visible")
        loc.fill(str(value))
        self._seen[target_key(target)] = target

    def wait(self, target=None, ms=None):
        if target:
            _locator(self._page, target).wait_for(state="visible")
            self._seen[target_key(target)] = target
        elif ms:
            self._page.wait_for_timeout(int(ms))

    def dispatch(self, ui):
        """按 ui 结构执行一步，返回这一步最终落在哪个地址。"""
        do = ui.get("do")
        if do == "goto":
            return self.goto(ui.get("url") or "/")
        if do == "click":
            self.click(ui.get("target"))
        elif do == "fill":
            self.fill(ui.get("target"), ui.get("value"))
        elif do == "wait":
            self.wait(ui.get("target"), ui.get("ms"))
        elif do == "eval":
            self._page.evaluate(str(ui.get("script")))
        else:
            raise UiError(f"不认识的 ui.do: {do}")
        return self._page.url

    # ---- 观测 -------------------------------------------------------
    def snapshot(self, targets=()):
        """当前页面快照，字段名跟 core/asserts 的 SRCS_UI 一一对应。"""
        page = self._page
        for t in targets:
            if t:
                self._seen[target_key(t)] = t
        text = ""
        try:
            text = page.locator("body").inner_text(timeout=3000) or ""
        except Exception:                         # noqa: BLE001 页面正在跳转时取不到
            pass
        elements = {}
        for key, t in self._seen.items():
            try:
                elements[key] = _locator(page, t).inner_text(timeout=1500)
            except Exception:                     # noqa: BLE001 取不到=不存在，交给断言判
                pass
        try:
            title = page.title()
        except Exception:                         # noqa: BLE001
            title = ""
        return {
            "url": page.url,
            "title": title,
            "text": text[:SNAPSHOT_TEXT_LIMIT],
            "elements": elements,
        }

    def screenshot(self, path):
        """失败留证。目录不存在就建，截图失败不能让结果变成 blocked。"""
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._page.screenshot(path=path, full_page=True)
            return path
        except Exception:                         # noqa: BLE001
            return ""
