# -*- coding: utf-8 -*-
"""Edge 浏览器 CDP 驱动：进程管理 + DevTools WebSocket 连接 + page 适配。

为什么是它：系统自带 Edge（Win10/11 除 LTSC 精简版外预装），CDP 协议稳定，
省掉 Qt WebEngine 那 ~200MB Chromium。只有 edge 找不到时翻译功能降级「不可用」。

- 定位：注册表 App Paths + 常见安装路径兜底。
- attach-or-launch：profile 目录的 DevToolsActivePort 文件指向存活实例就直连
  （比如登录窗正开着），否则 --remote-debugging-port=0 新起进程（端口防冲突，
  从 DevToolsActivePort 读回）。
- 干活 headless（--headless=new 无窗），登录 headed（同一 profile；两进程不能
  同时开同一 profile，靠 kill_owned 先收 headless 再开有头）。
- CDP 走 websocket-client（纯 Python）；消息经 id 配对、事件按 method 分发，
  大消息由库内重组帧。
"""

import json
import os
import subprocess
import threading
import time
import urllib.request

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

EDGE_ARGS = ('--no-first-run', '--no-default-browser-check',
             '--disable-session-crashed-bubble', '--hide-crash-restore-bubble',
             # 新版 Chromium 校验 WS 握手 Origin，不在白名单直接 403（实测）
             '--remote-allow-origins=*')

_LAUNCH_WAIT_S = 15.0
_LOAD_TIMEOUT_S = 30.0


# ---------------- Edge 定位 ----------------

def _reg_edge():
    """注册表 App Paths 里的 msedge.exe（HKLM/HKCU 都查）。"""
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(
                        hive, r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe') as k:
                    path, _t = winreg.QueryValueEx(k, None)
                    if path and os.path.isfile(path):
                        return path
            except OSError:
                continue
    except ImportError:
        pass
    return None


def find_edge():
    """Edge 可执行文件路径；找不到返回 None（LTSC 精简版等）。"""
    path = _reg_edge()
    if path:
        return path
    candidates = [
        os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                     r'Microsoft\Edge\Application\msedge.exe'),
        os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'),
                     r'Microsoft\Edge\Application\msedge.exe'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''),
                     r'Microsoft\Edge\Application\msedge.exe'),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def supported():
    return find_edge() is not None


# ---------------- 进程管理 ----------------

def read_devtools_port(profile_dir):
    """读 profile 目录的 DevToolsActivePort：(port, ws_path)；缺失/损坏返回 None。"""
    try:
        with open(os.path.join(profile_dir, 'DevToolsActivePort'), 'r') as f:
            lines = f.read().splitlines()
        port = int(lines[0].strip())
        return port, lines[1].strip()
    except (OSError, ValueError, IndexError):
        return None


def _http_json(url, method='GET', timeout=3):
    try:
        req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8', 'replace'))
    except Exception:
        return None


_OWNED = {}          # profile_dir → 我们拉起的 Popen（attach 来的不在这里）
_OWNED_LOCK = threading.Lock()


def attach_or_launch(profile_dir, headless, edge_path=None, wait_s=_LAUNCH_WAIT_S):
    """有存活实例直连（proc=None），否则新起进程。返回 (port, proc|None)。"""
    edge_path = edge_path or find_edge()
    if edge_path is None:
        raise EdgeUnavailableError('Microsoft Edge not found')
    os.makedirs(profile_dir, exist_ok=True)
    info = read_devtools_port(profile_dir)
    if info and _http_json('http://127.0.0.1:%d/json/version' % info[0], timeout=1):
        return info[0], None
    args = [edge_path, '--remote-debugging-port=0',
            '--user-data-dir=' + profile_dir]
    if headless:
        args.append('--headless=new')
    args += list(EDGE_ARGS)
    args.append('about:blank')
    proc = subprocess.Popen(args, creationflags=CREATE_NO_WINDOW)
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        info = read_devtools_port(profile_dir)
        if info:
            break
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    if not info:
        proc.kill()
        raise EdgeUnavailableError('edge did not expose devtools port')
    with _OWNED_LOCK:
        _OWNED[profile_dir] = proc
    return info[0], proc


def kill_owned(profile_dir):
    """收掉我们拉起的实例（attach 来的不动）：登录窗要开有头前先收 headless。"""
    with _OWNED_LOCK:
        proc = _OWNED.pop(profile_dir, None)
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


class EdgeUnavailableError(RuntimeError):
    """找不到 Edge 或实例拉不起来。"""


# ---------------- CDP 连接 ----------------

class CdpConnection(object):
    """单 target 的 WebSocket 连接：id 配对分发应答、method 分发事件。
    回调全部发生在 reader 线程——调用方若要碰 UI 请自行转线程。"""

    def __init__(self, ws_url, ws_factory=None):
        if ws_factory is None:
            import websocket
            # suppress_origin：非浏览器客户端不该带 Origin 头；与上面的白名单双保险
            ws_factory = lambda url, **kw: websocket.create_connection(
                url, suppress_origin=True, **kw)
        self._ws = ws_factory(ws_url)
        self._next_id = 0
        self._pending = {}
        self._listeners = {}
        self._lock = threading.Lock()
        self.closed = False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        pending = {}
        try:
            while True:
                raw = self._ws.recv()
                if not raw:
                    break
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if 'id' in msg:
                    with self._lock:
                        cb = self._pending.pop(msg['id'], None)
                    if cb is not None:
                        cb(msg)
                elif 'method' in msg:
                    for cb in list(self._listeners.get(msg['method'], [])):
                        cb(msg.get('params') or {})
        except Exception:
            pass
        with self._lock:
            self.closed = True
            pending = self._pending
            self._pending = {}
        for cb in pending.values():
            cb({'error': {'message': 'connection closed'}})

    def send(self, method, params, cb):
        with self._lock:
            if self.closed:
                cb({'error': {'message': 'connection closed'}})
                return
            self._next_id += 1
            mid = self._next_id
            self._pending[mid] = cb
        try:
            self._ws.send(json.dumps({'id': mid, 'method': method,
                                      'params': params or {}}))
        except Exception as e:
            with self._lock:
                self._pending.pop(mid, None)
            cb({'error': {'message': str(e)}})

    def on(self, event, cb):
        self._listeners.setdefault(event, []).append(cb)

    def close(self):
        with self._lock:
            self.closed = True
        try:
            self._ws.close()
        except Exception:
            pass


def _create_target(port, url='about:blank'):
    """新标签页；新版 Chromium 要 PUT（旧版兼容 GET 兜底）。返回 (target_id, ws_url)。"""
    endpoint = 'http://127.0.0.1:%d/json/new?%s' % (port, urllib.request.quote(url, safe=''))
    info = _http_json(endpoint, method='PUT')
    if info is None:
        info = _http_json(endpoint, method='GET')
    if not info or 'webSocketDebuggerUrl' not in info:
        raise EdgeUnavailableError('failed to create target')
    return info.get('id'), info['webSocketDebuggerUrl']


# ---------------- page 适配 ----------------

class EdgePage(object):
    """DoubaoSession page 契约：load(url, cb(ok)) / run_js(script, cb(value))。
    进程断了（被 kill_owned 收掉等）下次调用自动重连/重启，对上层透明。"""

    def __init__(self, headless=True, profile_dir=None, launcher=None,
                 conn_factory=None, target_factory=None):
        self._headless = headless
        self._profile = profile_dir
        self._launcher = launcher or attach_or_launch
        self._conn_factory = conn_factory or CdpConnection
        self._target_factory = target_factory or _create_target
        self._conn = None
        self._proc = None
        self._target = None

    def _ensure(self):
        if self._conn is not None and not self._conn.closed:
            return
        self._teardown_conn()
        port, proc = self._launcher(self._profile, self._headless)
        self._proc = proc
        self._target, ws_url = self._target_factory(port)
        self._conn = self._conn_factory(ws_url)

    def _teardown_conn(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._target = None

    def load(self, url, cb):
        try:
            self._ensure()
        except EdgeUnavailableError:
            cb(False)
            return
        conn = self._conn
        done = {'v': False}
        timer = threading.Timer(_LOAD_TIMEOUT_S, lambda: _finish(False))
        timer.daemon = True

        def _finish(ok):
            if done['v']:
                return
            done['v'] = True
            timer.cancel()
            cb(ok)

        conn.on('Page.loadEventFired', lambda _params: _finish(True))
        conn.send('Page.enable', {}, lambda _msg: None)

        def _on_nav(msg):
            if 'error' in msg:
                _finish(False)
                return
            if (msg.get('result') or {}).get('errorText'):
                _finish(False)
        conn.send('Page.navigate', {'url': url}, _on_nav)
        timer.start()

    def run_js(self, script, cb):
        try:
            self._ensure()
        except EdgeUnavailableError:
            cb(None)
            return

        def _on_resp(msg):
            if 'error' in msg:
                cb(None)
                return
            result = msg.get('result') or {}
            if result.get('exceptionDetails'):
                cb(None)
                return
            cb((result.get('result') or {}).get('value'))

        self._conn.send('Runtime.evaluate',
                        {'expression': script, 'returnByValue': True,
                         'awaitPromise': True}, _on_resp)

    def alive(self):
        """页面还活着吗：连接断开（标签页/窗口被关）或我们拉起的进程退出都算死。"""
        if self._conn is not None and self._conn.closed:
            return False
        if self._proc is not None and self._proc.poll() is not None:
            return False
        return True

    def close(self):
        """收掉连接与我们拉起的进程（attach 来的实例只断开，不杀）。"""
        self._teardown_conn()
        if self._profile is not None:
            kill_owned(self._profile)
        self._proc = None