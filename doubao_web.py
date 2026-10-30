# -*- coding: utf-8 -*-
"""豆包网页翻译适配层：Edge CDP 页面准备、流式接口调用和登录引导。

只把 OCR 识别出的文字发给豆包，不上传截图；按网页版 SSE 响应中的编号还原译文。
仅当翻译接口返回认证错误时才引导登录。Edge profile 与 session Cookie 罐均保存在
%APPDATA%\\zbox 下，不写入应用配置或日志。

DoubaoSession 是可注入 page/timer 的纯 Python 状态机；Edge CDP 驱动延迟到功能使用时导入。
"""

import ctypes
import json
import os
import shutil
import threading


CHAT_URL = 'https://www.doubao.com/chat/'
TRANSLATE_URL = '/samantha/plugin/stream_article_translate'
LAUNCH_URL = '/alice/user/launch'

# JS 标记串：FakePage 测试按标记路由应答，生产 JS 里是无害注释
TAG_TRANSLATE = '/*ZBOX_TRANSLATE*/'


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


class DoubaoLoginRequired(DoubaoError):
    """豆包流式接口返回需要登录的错误码。"""


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
    try:
        os.remove(_cookies_file())
    except OSError:
        pass


# ---------------- 登录态 cookie 罐 ----------------
# Chromium 不把 session cookie 写盘（实测：登录后 Cookies DB 仍是空壳，
# Edge 全关再开登录态就丢）。登录成功时经 CDP 把内存里的 cookie 抓进
# 本地罐（DPAPI 加密），每次启动 Edge 连接后、页面加载前恢复。

def _cookies_file():
    import sysutil
    return os.path.join(sysutil.appdata_dir(), 'edge_cookies.bin')


class _Blob(ctypes.Structure):
    _fields_ = [('cbData', ctypes.c_ulong),
                ('pbData', ctypes.POINTER(ctypes.c_byte))]


def _dpapi(raw, protect):
    """Windows DPAPI 加/解密（仅当前用户可解）；失败返回 None。"""
    try:
        crypt32 = ctypes.windll.crypt32
        blob_p = ctypes.POINTER(_Blob)
        for fn_name in ('CryptProtectData', 'CryptUnprotectData'):
            fn = getattr(crypt32, fn_name)
            fn.argtypes = [blob_p, ctypes.c_wchar_p, blob_p,
                           ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, blob_p]
            fn.restype = ctypes.c_int
        buf = ctypes.create_string_buffer(raw, len(raw))
        ib = _Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
        ob = _Blob()
        fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        if not fn(ctypes.byref(ib), None, None, None, None, 0, ctypes.byref(ob)):
            return None
        try:
            return ctypes.string_at(ob.pbData, ob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(ctypes.cast(ob.pbData, ctypes.c_void_p))
    except Exception:
        return None


def _jar_entry(c):
    """CDP cookie dict → 可恢复的最简 CookieParam；已过期的丢弃（None），
    session cookie 恢复时不带 expires。"""
    import time
    exp = c.get('expires')
    if not c.get('session') and exp and exp <= time.time():
        return None   # 已过期的持久 cookie 直接丢
    e = {'name': c['name'], 'value': c['value'], 'domain': c.get('domain', ''),
         'path': c.get('path', '/'), 'secure': bool(c.get('secure')),
         'httpOnly': bool(c.get('httpOnly'))}
    ss = c.get('sameSite')
    if ss in ('Lax', 'Strict', 'None'):
        e['sameSite'] = ss
    if not c.get('session') and exp:
        e['expires'] = exp
    return e


def _save_cookie_jar(cookies, path=None):
    """把豆包域 cookie 写进本地罐（DPAPI 加密；加密失败不存，宁可重新登录）。"""
    jar = [e for e in (_jar_entry(c) for c in cookies
                       if (c.get('domain') or '').endswith('.doubao.com')
                       or c.get('domain') == 'doubao.com')
           if e is not None]
    if not jar:
        return
    blob = _dpapi(json.dumps(jar).encode('utf-8'), True)
    if blob is None:
        return
    try:
        with open(path or _cookies_file(), 'wb') as f:
            f.write(b'DP1\n' + blob)
    except OSError:
        pass


def _load_cookie_jar(path=None):
    """读本地罐 → list[CookieParam]；没有/损坏/解密失败 → None。"""
    try:
        with open(path or _cookies_file(), 'rb') as f:
            raw = f.read()
        if not raw.startswith(b'DP1\n'):
            return None
        data = _dpapi(raw[4:], False)
        if data is None:
            return None
        jar = json.loads(data.decode('utf-8'))
        return jar if isinstance(jar, list) and jar else None
    except Exception:
        return None


_DOUBAO_COOKIE_URLS = ['https://www.doubao.com/', 'https://accounts.doubao.com/']


# ---------------- JS 构建 ----------------

def _decode(raw):
    """JS 侧 JSON 字符串 → dict。"""
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return 'malformed'
    return raw if isinstance(raw, dict) else 'malformed'


def build_translate_js(texts, target_lang):
    """按 CometixTranslate 的网页版流式接口协议发起翻译。"""
    return TAG_TRANSLATE + r"""
(async () => {
  const key = '__zbox_doubao_tea_uuid';
  let teaUuid = localStorage.getItem(key);
  if (!/^\d{18}$/.test(teaUuid || '')) {
    const r = new Uint32Array(2);
    crypto.getRandomValues(r);
    teaUuid = String(100000000 + Math.floor(r[0] / 4294967296 * 900000000))
            + String(100000000 + Math.floor(r[1] / 4294967296 * 900000000));
    localStorage.setItem(key, teaUuid);
  }
  const tabId = window.__zbox_doubao_tab_id ||
                (window.__zbox_doubao_tab_id = crypto.randomUUID());
  const params = (deviceId, webId, country) => new URLSearchParams({
    language: 'zh', browser_language: navigator.language || 'zh-CN',
    device_platform: 'web', aid: '586864', real_aid: '586864',
    pkg_type: 'release_version', device_id: deviceId, tea_uuid: teaUuid,
    web_id: webId, is_new_user: '0', region: country, sys_region: country,
    'use-olympus-account': '1', samantha_web: '1', version: '1.38.0',
    version_code: '20800', pc_version: '1.38.0', web_tab_id: tabId,
  });
  let deviceId = '0', webId = teaUuid, country = '';
  try {
    const boot = await fetch(%(launch)s + '?' + params('0', teaUuid, ''), {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
    });
    const data = await boot.json();
    if (data.code === 0 && data.data) {
      const config = data.data.config || {};
      country = typeof data.data.country === 'string' ? data.data.country : '';
      if (config.ttwid && config.web_id) {
        webId = String(config.web_id).slice(0, 64);
        deviceId = webId;
      }
    }
  } catch (e) {}
  const response = await fetch(%(endpoint)s + '?' + params(deviceId, webId, country), {
    method: 'POST', credentials: 'include',
    headers: {'Content-Type': 'application/json', 'Accept': 'text/event-stream'},
    body: JSON.stringify({raw_text: %(texts)s, target_lang: %(target)s,
                          translate_service: '1'}),
  });
  return JSON.stringify({status: response.status, body: await response.text()});
})().catch(e => JSON.stringify({networkError: String(e)}))
""" % {'launch': json.dumps(LAUNCH_URL),
       'endpoint': json.dumps(TRANSLATE_URL),
       'texts': json.dumps(list(texts), ensure_ascii=False),
       'target': json.dumps(target_lang, ensure_ascii=False)}


_AUTH_CODES = {'710012000', '710012001', '710022013'}


def _raise_api_error(code):
    code = str(code)
    if code in _AUTH_CODES:
        raise DoubaoLoginRequired('doubao login required (%s)' % code)
    raise DoubaoError('doubao rejected translation (%s)' % code)


def parse_stream_response(raw, expected_count):
    """解析 CometixTranslate 同款 SSE 响应，按 index 还原译文顺序。"""
    response = _decode(raw)
    if not isinstance(response, dict):
        raise DoubaoReplyError('invalid stream response')
    if response.get('networkError'):
        raise DoubaoNetworkError('doubao request failed')
    status = response.get('status')
    if status == 401:
        raise DoubaoLoginRequired('doubao login required (HTTP 401)')
    if status == 403:
        raise DoubaoError('doubao request forbidden (HTTP 403)')
    if not isinstance(status, int) or not 200 <= status < 300:
        raise DoubaoNetworkError('doubao request failed (HTTP %s)' % status)
    body = response.get('body')
    if not isinstance(body, str):
        raise DoubaoReplyError('invalid stream body')

    # 鉴权/限流错误可能直接返回普通 JSON，而不是 SSE event:err（插件 QT 分支同款）。
    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get('code') not in (None, 0, '0'):
        _raise_api_error(payload.get('code'))

    translations = [None] * expected_count
    body = body.replace('\r\n', '\n').replace('\r', '\n')
    for block in body.split('\n\n'):
        event = 'message'
        data_lines = []
        for line in block.split('\n'):
            if line.startswith('event:'):
                event = line[6:].strip()
            elif line.startswith('data:'):
                data_lines.append(line[5:].lstrip())
        if event not in ('json', 'err') or not data_lines:
            continue
        try:
            payload = json.loads('\n'.join(data_lines))
        except ValueError:
            raise DoubaoReplyError('invalid stream event')
        if not isinstance(payload, dict):
            raise DoubaoReplyError('invalid stream event')
        code = payload.get('code')
        if code not in (0, '0'):
            _raise_api_error(code)
        if event == 'err':
            raise DoubaoError('doubao stream failed')
        data = payload.get('data')
        items = data.get('items') if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise DoubaoReplyError('invalid translation items')
        for item in items:
            if not isinstance(item, dict):
                raise DoubaoReplyError('invalid translation item')
            index, text = item.get('index'), item.get('res')
            if (not isinstance(index, int) or isinstance(index, bool)
                    or index < 0 or index >= expected_count
                    or not isinstance(text, str) or not text.strip()):
                raise DoubaoReplyError('invalid translation item')
            translations[index] = text
    if any(text is None for text in translations):
        raise DoubaoReplyError('doubao returned incomplete translations')
    return translations


# ---------------- 会话状态机 ----------------

class DoubaoSession(object):
    """一次翻译任务：加载豆包页面 → 调用网页版 SSE 翻译接口。"""

    @staticmethod
    def _qt_timer(ms, fn):
        from PySide6.QtCore import QTimer
        QTimer.singleShot(ms, fn)

    def __init__(self, page):
        self._page = page
        self._cancelled = False
        self._finished = False
        self._texts = []
        self._target = 'zh'
        self._on_done = None
        self._on_error = None
        self.on_login_required = None

    def cancel(self):
        self._cancelled = True
        close = getattr(self._page, 'close', None)
        if close:
            close()

    def _alive(self):
        return not self._cancelled and not self._finished

    def _fail(self, err):
        if self._alive():
            self._finished = True
            self._on_error(err)

    def _succeed(self, texts):
        if not self._alive():
            return
        self._finished = True
        get_cookies = getattr(self._page, 'get_cookies', None)
        if get_cookies is None:
            self._on_done(texts)
            return

        def refreshed(cookies):
            # 插件始终使用浏览器实时 Cookie；zbox 每次成功后也刷新本地快照，
            # 避免服务端轮换会话后仍反复恢复登录时的旧 Cookie。
            if cookies:
                _save_cookie_jar(cookies)
            if not self._cancelled:
                self._on_done(texts)

        get_cookies(_DOUBAO_COOKIE_URLS, refreshed)

    def translate(self, texts, target_lang, on_done, on_error, preloaded=False):
        """页面预加载时跳过导航，随后直接发送流式翻译请求。"""
        self._texts = list(texts)
        self._target = target_lang
        self._on_done = on_done
        self._on_error = on_error
        if preloaded:
            self._translate()
        else:
            self._page.load(CHAT_URL, self._on_loaded)

    def _on_loaded(self, ok):
        if not self._alive():
            return
        if not ok:
            self._fail(DoubaoNetworkError('doubao page load failed'))
            return
        self._translate()

    def _translate(self):
        if self._alive():
            self._page.run_js(build_translate_js(self._texts, self._target),
                              self._on_translated)

    def _on_translated(self, raw):
        if not self._alive():
            return
        try:
            texts = parse_stream_response(raw, len(self._texts))
        except DoubaoLoginRequired as e:
            if self.on_login_required is not None:
                self._finished = True
                self.on_login_required()
            else:
                self._fail(e)
        except DoubaoError as e:
            self._fail(e)
        else:
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
    edge_page = edge_driver.EdgePage(headless=True, profile_dir=profile_dir(),
                                     cookie_provider=_load_cookie_jar)

    class _Page(object):
        def load(self, url, cb):
            edge_page.load(url, lambda ok: dispatcher.post(cb, ok))

        def run_js(self, script, cb):
            edge_page.run_js(script, lambda v: dispatcher.post(cb, v))

        def get_cookies(self, urls, cb):
            edge_page.get_cookies(urls, lambda cs: dispatcher.post(cb, cs))

        def close(self):
            edge_page.close()

        def widget(self):
            return None

        _dispatcher = dispatcher   # 防 GC

    return _Page()


def prepare_page(page, cb):
    """加载豆包页面供同源流式接口调用；此接口当前不要求先登录。"""
    page.load(CHAT_URL, lambda ok: cb(True if ok else None))


class DoubaoLoginWindow(object):
    """有头 Edge 登录窗：用同一翻译接口确认服务可用，避免依赖旧登录探测接口。"""

    POLL_MS = 2000

    def __init__(self, on_logged_in, on_aborted=None, timer=None):
        self._cbs_ok = [on_logged_in]
        self._cbs_abort = [on_aborted] if on_aborted is not None else []
        self._timer = timer or DoubaoSession._qt_timer
        self._done = False
        self._dispatcher = _gui_dispatcher()
        edge_driver.kill_profile_instances(profile_dir())
        self._page = edge_driver.EdgePage(headless=False, profile_dir=profile_dir(),
                                          cookie_provider=_load_cookie_jar)
        self._page.load(CHAT_URL, self._post(self._on_loaded))
        if self._page._proc is not None:
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
            self._finish(False)
            return
        self._page.run_js(build_translate_js(['.'], 'zh'),
                          self._post(self._on_probe))

    def _on_probe(self, raw):
        try:
            parse_stream_response(raw, 1)
        except DoubaoError:
            if not self._done:
                self._timer(self.POLL_MS, self._tick)
            return
        self._finish(True)

    def add_callbacks(self, on_logged_in, on_aborted=None):
        """去重复用存活窗口时，把新调用方的回调挂上来。"""
        self._cbs_ok.append(on_logged_in)
        if on_aborted is not None:
            self._cbs_abort.append(on_aborted)

    def bring_to_front(self):
        """把已开的登录窗重新抢到前台（去重命中时用户可能在找它）。"""
        if self._page._proc is not None:
            threading.Thread(target=edge_driver.bring_window_to_front,
                             args=(self._page._proc.pid,), daemon=True).start()

    def _finish(self, logged_in):
        if self._done:
            return
        self._done = True
        global _active_login
        if _active_login is self:
            _active_login = None
        get_ck = getattr(self._page, 'get_cookies', None)
        if logged_in and get_ck is not None:
            get_ck(_DOUBAO_COOKIE_URLS,
                   lambda cs: self._finish_close(logged_in, cs))
            return
        self._finish_close(logged_in, None)

    def _finish_close(self, logged_in, cookies):
        if cookies:
            _save_cookie_jar(cookies)
        self._page.close()
        cbs = self._cbs_ok if logged_in else self._cbs_abort
        for cb in cbs:
            cb()

    def close(self):
        """外部取消（截图窗已关等）：关窗且不回调登录成功。"""
        self._finish(False)


_active_login = None


def open_login_window(on_logged_in, on_aborted=None, timer=None):
    """截图翻译的登录入口：有头 Edge 登录窗控制器（非 Qt 窗口）。
    已有存活登录窗时不重复开（用户连点也不会开一排 Edge）：
    把既有窗口抢到前台，回调挂到它上面一起通知。"""
    global _active_login
    win = _active_login
    if win is not None and not win._done and win._page.alive():
        win.add_callbacks(on_logged_in, on_aborted)
        win.bring_to_front()
        return win
    win = DoubaoLoginWindow(on_logged_in, on_aborted, timer=timer)
    _active_login = win
    return win
