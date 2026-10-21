# -*- coding: utf-8 -*-
"""豆包网页翻译适配层：登录检测、提示词注入、回复轮询，全部选择器集中维护。

设计约束（已批准计划）：
- 只把 OCR 出的文字发给豆包，截图本身不出本机。
- 登录态走独立持久 profile（%APPDATA%\\zbox\\doubao_profile），Cookie 不进 config/日志。
- 页面结构签名不匹配时返回明确的「豆包页面已更新」错误，绝不猜测回复。
- 译文按编号 JSON 严格解析（translation_core.parse_translations）。

分层：DoubaoSession 是纯 Python 状态机（page/timer 可注入，便于单测）；
WebPage / DoubaoLoginDialog 是 Qt WebEngine 实现，延迟到功能启用时才 import。
"""

import json
import os
import shutil
import threading

import translation_core

CHAT_URL = 'https://www.doubao.com/chat/'

# 豆包 DOM 钩子（2026-10 实测稳定）；页面改版只需改这里
SELECTORS = {
    'input': '[data-testid="chat_input"] .ProseMirror',
    'send': '[data-testid="chat_input_send_button"]',
    'assistant_message': '[data-testid="receive_message"]',
    'stop_button': '[data-testid="chat_input_stop_button"]',
}

# JS 标记串：FakePage 测试按标记路由应答，生产 JS 里是无害注释
TAG_PROBE = '/*ZBOX_PROBE*/'
TAG_FILL = '/*ZBOX_FILL*/'
TAG_POLL = '/*ZBOX_POLL*/'
TAG_SEND = '/*ZBOX_SEND*/'


class DoubaoError(RuntimeError):
    """豆包链路统一错误基类。"""


class DoubaoNetworkError(DoubaoError):
    """页面加载失败（断网 / 被墙 / DNS）。"""


class DoubaoStructureChanged(DoubaoError):
    """豆包页面结构签名不匹配：选择器失效，需要更新适配层。"""


class DoubaoReplyError(DoubaoError):
    """回复内容无法严格解析成编号译文。"""


class DoubaoTimeout(DoubaoError):
    """等待回复超时。"""


class DoubaoLoginCancelled(DoubaoError):
    """用户关掉了登录窗口（未登录）：提示点击重试重新引导。"""


def profile_dir():
    import sysutil
    return os.path.join(sysutil.appdata_dir(), 'edge_profile')


def clear_profile():
    """退出登录：删除整个持久 profile（Cookie / 缓存 / 站点数据）；
    顺带清掉 Qt WebEngine 时代的旧 doubao_profile 目录。"""
    import sysutil
    shutil.rmtree(profile_dir(), ignore_errors=True)
    shutil.rmtree(os.path.join(sysutil.appdata_dir(), 'doubao_profile'),
                  ignore_errors=True)


# ---------------- JS 构建 ----------------

def build_probe_js():
    """启动登录态探测：fetch 是异步的，结果落地 window.__zbox_login
    （Qt runJavaScript 不等待 Promise 解析，实测回调拿到空——必须分两步）。
    注意接口对匿名也返回 200：必须解析响应体 code===0 才算已登录。"""
    return TAG_PROBE + """
(() => {
  window.__zbox_login = null;
  fetch('/alice/profile/self', {credentials: 'include'})
    .then(async r => {
      let logged = false;
      try { logged = (await r.json()).code === 0; } catch (e) {}
      window.__zbox_login = logged;
    })
    .catch(() => { window.__zbox_login = false; });
  return true;
})()
"""


def build_probe_collect_js():
    """读取探测结果（JSON 字符串）；fetch 未落地返回空串，由调用方轮询。
    选择器在收取时求值（SPA 晚渲染；loadFinished 时控件可能还没挂上）。
    注意：当前 Qt/PySide6 组合的 runJavaScript 只封送标量，对象/数组到手是空串，
    结构化结果必须 JSON.stringify。"""
    return TAG_PROBE + """
(() => {
  const login = window.__zbox_login;
  if (login === undefined || login === null) return '';
  const q = (s) => !!document.querySelector(s);
  return JSON.stringify({settled: true, logged_in: login,
                         input: q(%(input)s)});
})()
""" % {'input': json.dumps(SELECTORS['input'])}


def _decode(raw):
    """JS 侧 JSON 字符串 → dict；空串/None = 未就绪，返回 None。"""
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return 'malformed'
    return raw if isinstance(raw, dict) else 'malformed'


def build_fill_js(prompt):
    """把提示词写进输入框；返回是否写入成功。发送按钮要输入文字后才渲染（实测），
    点击发送由 build_send_js 单独负责（会话隔一拍再点）。"""
    return TAG_FILL + """
(() => {
  const ed = document.querySelector(%(input)s);
  if (!ed) return false;
  ed.focus();
  ed.textContent = '';
  document.execCommand('insertText', false, %(text)s);
  return (ed.textContent || '').length > 0;
})()
""" % {'input': json.dumps(SELECTORS['input']), 'text': json.dumps(prompt)}


def build_send_js():
    """点发送；按钮还没渲染/禁用返回 false，由会话在宽限期内重试。"""
    return TAG_SEND + """
(() => {
  const b = document.querySelector(%(send)s);
  if (!b || b.disabled) return false;
  b.click();
  return true;
})()
""" % {'send': json.dumps(SELECTORS['send'])}


def build_poll_js():
    """抓最新一条助手回复：{done, text}；回复流式中 done=false。"""
    return TAG_POLL + '''
(() => {
  const msgs = document.querySelectorAll(%(msg)r);
  if (!msgs.length) return {done: false, text: null};
  const last = msgs[msgs.length - 1];
  const text = (last.innerText || '').trim();
  const stopping = !!document.querySelector(%(stop)r);
  return JSON.stringify({done: !stopping && text.length > 0, text: text || null});
})()
''' % {'msg': json.dumps(SELECTORS['assistant_message']),
       'stop': json.dumps(SELECTORS['stop_button'])}


# ---------------- 会话状态机 ----------------

class DoubaoSession(object):
    """一次翻译任务的流程编排：加载 → 探测 → 填发 → 轮询 → 严格解析。
    page 接口：load(url, cb(ok)) / run_js(script, cb(value))；
    timer(ms, fn) 调度器（生产 = QTimer.singleShot，测试可同步/队列注入）。"""

    def __init__(self, page, timer=None, poll_interval_ms=1000, poll_timeout_s=120):
        self._page = page
        self._timer = timer or self._qt_timer
        self._interval = poll_interval_ms
        self._timeout_ms = poll_timeout_s * 1000
        self._cancelled = False
        self._finished = False
        self.on_login_required = None     # 未登录时回调；登录完成后应调 notify_logged_in()

    @staticmethod
    def _qt_timer(ms, fn):
        from PySide6.QtCore import QTimer
        QTimer.singleShot(ms, fn)

    def cancel(self):
        self._cancelled = True

    def close(self):
        """取消并收掉底层 page（headless Edge 工人随会话结束，不留孤儿进程）。"""
        self.cancel()
        close = getattr(self._page, 'close', None)
        if close is not None:
            close()

    def notify_logged_in(self):
        """登录窗口回报成功后重走整个流程。"""
        if not self._cancelled and not self._finished:
            self._start()

    def translate(self, texts, target_lang, on_done, on_error, preloaded=False):
        """preloaded=True：页面已加载过（登录预检同款页），跳过 load 直接探测。"""
        self._texts = list(texts)
        self._target = target_lang
        self._on_done = on_done
        self._on_error = on_error
        if preloaded:
            self._page.run_js(build_probe_js(), self._on_probe_started)
        else:
            self._start()

    def _start(self):
        self._page.load(CHAT_URL, self._on_loaded)

    def _alive(self):
        return not self._cancelled and not self._finished

    def _fail(self, err):
        if self._alive():
            self._finished = True
            self._on_error(err)

    def _succeed(self, texts):
        if self._alive():
            self._finished = True
            self._on_done(texts)

    PROBE_TIMEOUT_MS = 15000
    PROBE_INTERVAL_MS = 500
    STRUCTURE_GRACE_MS = 8000   # 已落地但控件未渲染的宽限期：SPA 加载慢，别误判结构变化

    def _on_loaded(self, ok):
        if not self._alive():
            return
        if not ok:
            self._fail(DoubaoNetworkError('doubao page load failed'))
            return
        self._page.run_js(build_probe_js(), self._on_probe_started)

    def _on_probe_started(self, started):
        if not self._alive():
            return
        if not started:
            self._fail(DoubaoStructureChanged('probe failed to start'))
            return
        self._probe_elapsed = 0
        self._probe_missing_sel = False
        self._timer(self.PROBE_INTERVAL_MS, self._probe_tick)

    def _probe_tick(self):
        if not self._alive():
            return
        self._probe_elapsed += self.PROBE_INTERVAL_MS
        if self._probe_elapsed > self.PROBE_TIMEOUT_MS:
            if self._probe_missing_sel:
                self._fail(DoubaoStructureChanged('input/send selector missing'))
            else:
                self._fail(DoubaoTimeout('probe not settled within %ds'
                                         % (self.PROBE_TIMEOUT_MS // 1000)))
            return
        self._page.run_js(build_probe_collect_js(), self._on_probe)

    def _on_probe(self, raw):
        if not self._alive():
            return
        probe = _decode(raw)
        if probe is None or (isinstance(probe, dict) and not probe.get('settled')):
            self._timer(self.PROBE_INTERVAL_MS, self._probe_tick)   # 未落地，继续轮询
            return
        if not isinstance(probe, dict):
            self._fail(DoubaoStructureChanged('probe returned %r' % (raw,)))
            return
        if not probe.get('logged_in'):
            if self.on_login_required is not None:
                self.on_login_required()   # 由 UI 开登录窗；成功后 notify_logged_in()
            else:
                self._fail(DoubaoError('not logged in'))
            return
        if not probe.get('input'):
            # 控件还没渲染（SPA 慢）：宽限期内继续等，超期才报结构变化
            self._probe_missing_sel = True
            if self._probe_elapsed > self.STRUCTURE_GRACE_MS:
                self._fail(DoubaoStructureChanged('input selector missing'))
            else:
                self._timer(self.PROBE_INTERVAL_MS, self._probe_tick)
            return
        prompt = translation_core.build_prompt(self._texts, self._target)
        self._page.run_js(build_fill_js(prompt), self._on_filled)

    SEND_GRACE_MS = 5000
    SEND_INTERVAL_MS = 400

    def _on_filled(self, ok):
        if not self._alive():
            return
        if not ok:
            self._fail(DoubaoStructureChanged('failed to fill prompt'))
            return
        self._send_elapsed = 0
        self._timer(self.SEND_INTERVAL_MS, self._send_tick)

    def _send_tick(self):
        if not self._alive():
            return
        self._send_elapsed += self.SEND_INTERVAL_MS
        if self._send_elapsed > self.SEND_GRACE_MS:
            self._fail(DoubaoStructureChanged('send button missing'))
            return
        self._page.run_js(build_send_js(), self._on_sent)

    def _on_sent(self, ok):
        if not self._alive():
            return
        if not ok:   # 按钮还没渲染出来，宽限期内继续等
            self._timer(self.SEND_INTERVAL_MS, self._send_tick)
            return
        self._elapsed = 0
        self._schedule_poll()

    def _schedule_poll(self):
        self._timer(self._interval, self._poll_tick)

    def _poll_tick(self):
        if not self._alive():
            return
        self._elapsed += self._interval
        if self._elapsed > self._timeout_ms:
            self._fail(DoubaoTimeout('no completed reply within %ds'
                                     % (self._timeout_ms // 1000)))
            return
        self._page.run_js(build_poll_js(), self._on_polled)

    def _on_polled(self, raw):
        if not self._alive():
            return
        result = _decode(raw)
        if not isinstance(result, dict) or not result.get('done'):
            self._schedule_poll()
            return
        try:
            texts = translation_core.parse_translations(result.get('text') or '',
                                                        len(self._texts))
        except translation_core.TranslationParseError as e:
            self._fail(DoubaoReplyError(str(e)))
            return
        self._succeed(texts)


# ---------------- Edge CDP 实现（系统浏览器驱动，省 Qt WebEngine 的 ~200MB） ----------------

import edge_driver


def supported():
    """翻译可用性：系统得有 Edge（Win10/11 预装；LTSC 精简版等缺失时降级不可用）。"""
    return edge_driver.supported()


def _gui_dispatcher():
    """CDP 回调发生在 reader 线程，碰 Qt 前必须回 GUI 线程：Signal 跨线程自动转 queued。"""
    from PySide6.QtCore import QObject, Signal

    class _Dispatcher(QObject):
        sig = Signal(object, object)

        def __init__(self):
            super(_Dispatcher, self).__init__()
            self.sig.connect(self._go)

        def _go(self, cb, value):
            cb(value)

        def post(self, cb, value):
            self.sig.emit(cb, value)

    return _Dispatcher()


def make_page(parent=None):
    """生产 page：headless Edge 标签页，回调经 dispatcher 转回 GUI 线程。"""
    dispatcher = _gui_dispatcher()
    edge_page = edge_driver.EdgePage(headless=True, profile_dir=profile_dir())

    class _Page(object):
        def load(self, url, cb):
            edge_page.load(url, lambda ok: dispatcher.post(cb, ok))

        def run_js(self, script, cb):
            edge_page.run_js(script, lambda v: dispatcher.post(cb, v))

        def close(self):
            edge_page.close()

        def widget(self):
            return None

        _dispatcher = dispatcher   # 防 GC

    return _Page()


def check_login(page, cb, timer=None):
    """登录态预检（headless 页，不建 session）：load → 两阶段探测 →
    cb(True=已登录 / False=未登录 / None=检查失败如断网)。与 DoubaoSession 共享
    同一套 JS 与 _decode，但不动状态机本体。"""
    timer = timer or DoubaoSession._qt_timer
    state = {'elapsed': 0}

    def on_loaded(ok):
        if not ok:
            cb(None)
            return
        page.run_js(build_probe_js(), lambda _started: timer(500, tick))

    def tick():
        state['elapsed'] += 500
        if state['elapsed'] > 10000:
            cb(None)
            return
        page.run_js(build_probe_collect_js(), on_collect)

    def on_collect(raw):
        v = _decode(raw)
        if not isinstance(v, dict) or not v.get('settled'):
            timer(500, tick)
            return
        cb(bool(v.get('logged_in')))

    page.load(CHAT_URL, on_loaded)


class DoubaoLoginWindow(object):
    """有头 Edge 打开豆包登录页，后台两阶段探测登录态：
    登录成功（code===0）→ 关窗并 on_logged_in()；用户直接关窗/加载失败 → on_aborted()。
    开窗前先收掉同 profile 的 headless 工人（两进程不能同时开同一 profile）。"""

    POLL_MS = 2000

    def __init__(self, on_logged_in, on_aborted=None, timer=None):
        self._on_logged_in = on_logged_in
        self._on_aborted = on_aborted
        self._timer = timer or DoubaoSession._qt_timer
        self._done = False
        self._empty = 0
        self._dispatcher = _gui_dispatcher()
        # 清掉本 profile 的所有实例（含父进程死后残留的 headless——attach 分不出
        # 有头无头，连上残留 headless 登录窗就"隐形"了），再开有头窗口
        edge_driver.kill_profile_instances(profile_dir())
        self._page = edge_driver.EdgePage(headless=False, profile_dir=profile_dir())
        self._phase = 'start'
        self._page.load(CHAT_URL, self._post(self._on_loaded))
        if self._page._proc is not None:
            # 截图遮罩是全屏置顶窗：登录窗必须抢到它前面
            threading.Thread(target=edge_driver.bring_window_to_front,
                             args=(self._page._proc.pid,), daemon=True).start()

    def _post(self, fn):
        return lambda v: self._dispatcher.post(fn, v)

    def _on_loaded(self, ok):
        if self._done:
            return
        if not ok:
            self._finish(False)
            return
        self._timer(self.POLL_MS, self._tick)

    def _tick(self):
        if self._done:
            return
        if not self._page.alive():
            self._finish(False)      # 用户把浏览器窗口关了
            return
        if self._phase == 'start':
            self._phase = 'collect'
            self._page.run_js(build_probe_js(), self._post(lambda _ok: self._next()))
        else:
            self._page.run_js(build_probe_collect_js(), self._post(self._on_collect))

    def _next(self):
        if not self._done:
            self._timer(self.POLL_MS, self._tick)

    def _on_collect(self, raw):
        result = _decode(raw)
        if isinstance(result, dict):
            self._empty = 0
            if result.get('logged_in'):
                self._finish(True)
                return
            self._phase = 'start'
        else:
            # fetch 未落地：可能是慢，也可能是登录成功后的页面跳转/重载把
            # window.__zbox_login 清了（实测：扫码登录成功回到 chat 会导航）——
            # 连续空收就重发探测，否则永远停在 collect 相位探不到登录
            self._empty += 1
            if self._empty >= 2:
                self._empty = 0
                self._phase = 'start'
        self._next()

    def _finish(self, logged_in):
        if self._done:
            return
        self._done = True
        self._page.close()
        if logged_in:
            self._on_logged_in()
        elif self._on_aborted is not None:
            self._on_aborted()

    def close(self):
        """外部取消（截图窗已关等）：关窗且不回调登录成功。"""
        self._finish(False)


def open_login_window(on_logged_in, on_aborted=None):
    """截图翻译的登录入口：有头 Edge 登录窗控制器（非 Qt 窗口）。"""
    return DoubaoLoginWindow(on_logged_in, on_aborted)
