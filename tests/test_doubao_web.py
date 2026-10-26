# -*- coding: utf-8 -*-
"""豆包 Web 适配层测试：JS 构建、回复抽取、会话状态机（FakePage 驱动）、登录与登出。"""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import doubao_web as dw


class FakePage(object):
    """会话假页：导航和流式翻译应答可脚本化。"""

    def __init__(self, load_ok=True, translations=()):
        self.load_ok = load_ok
        self.translations = list(translations)
        self.loaded = []
        self.scripts = []
        self.pending_translation = None

    def load(self, url, cb):
        self.loaded.append(url)
        cb(self.load_ok)

    def run_js(self, script, cb):
        self.scripts.append(script)
        if dw.TAG_TRANSLATE in script:
            if self.translations:
                cb(self.translations.pop(0))
            else:
                self.pending_translation = cb
        else:
            cb(None)


def immediate_timer(_ms, fn):
    fn()


def queued_timer():
    tasks = []

    def _timer(_ms, fn):
        tasks.append(fn)
    return _timer, tasks


def stream_response(items, code=0):
    payload = json.dumps({'code': code, 'data': {'items': items}}, ensure_ascii=False)
    body = 'event:json\ndata:' + payload + '\n\nevent:done\ndata:\n\n'
    return json.dumps({'status': 200, 'body': body})


class StreamingApiTest(unittest.TestCase):
    def test_builds_cometix_stream_request_with_escaped_text(self):
        js = dw.build_translate_js(['line 1\n"quoted"'], 'zh')
        self.assertIn('stream_article_translate', js)
        self.assertIn('raw_text', js)
        self.assertIn(json.dumps(['line 1\n"quoted"'], ensure_ascii=False), js)
        self.assertIn('/alice/user/launch', js)
        self.assertNotIn('/alice/profile/self', js)

    def test_parses_cometix_sse_items_by_index(self):
        payload = json.dumps({'code': 0, 'data': {'items': [
            {'index': 1, 'res': '世界'}, {'index': 0, 'res': '你好'}]}})
        raw = json.dumps({'status': 200, 'body':
                          'event:json\ndata:' + payload + '\n\nevent:done\ndata:\n\n'})
        self.assertEqual(dw.parse_stream_response(raw, 2), ['你好', '世界'])


class ProfileTest(unittest.TestCase):
    def test_profile_dir_under_appdata_and_clear(self):
        with tempfile.TemporaryDirectory() as d:
            with patch('sysutil.appdata_dir', return_value=d):
                pdir = dw.profile_dir()
                self.assertTrue(pdir.startswith(d))
                os.makedirs(pdir)
                open(os.path.join(pdir, 'Cookies'), 'w').close()
                dw.clear_profile()
                self.assertFalse(os.path.exists(pdir))


class SessionFlowTest(unittest.TestCase):
    _stream = staticmethod(stream_response)

    def _run(self, page, preloaded=False):
        results = {}
        session = dw.DoubaoSession(page)
        session.translate(['Hello'], 'zh',
                          lambda texts: results.setdefault('done', texts),
                          lambda err: results.setdefault('error', err),
                          preloaded=preloaded)
        return results

    def test_happy_path(self):
        page = FakePage(translations=[self._stream([{'index': 0, 'res': '你好'}])])
        out = self._run(page)
        self.assertEqual(out.get('done'), ['你好'])
        self.assertEqual(page.loaded, [dw.CHAT_URL])
        self.assertIn(dw.TAG_TRANSLATE, page.scripts[0])

    def test_preloaded_page_skips_navigation(self):
        page = FakePage(translations=[self._stream([{'index': 0, 'res': '你好'}])])
        out = self._run(page, preloaded=True)
        self.assertEqual(out.get('done'), ['你好'])
        self.assertEqual(page.loaded, [])

    def test_network_load_failure(self):
        page = FakePage(load_ok=False)
        out = self._run(page)
        self.assertIsInstance(out.get('error'), dw.DoubaoNetworkError)

    def test_auth_error_triggers_login_handler(self):
        page = FakePage(translations=[self._stream([], code=710012000)])
        session = dw.DoubaoSession(page)
        events = []
        session.on_login_required = lambda: events.append('login')
        session.translate(['Hello'], 'zh', lambda _: None,
                          lambda err: events.append(type(err).__name__))
        self.assertEqual(events, ['login'])

    def test_auth_error_without_handler_is_reported(self):
        page = FakePage(translations=[self._stream([], code=710012000)])
        out = self._run(page)
        self.assertIsInstance(out.get('error'), dw.DoubaoLoginRequired)

    def test_http_401_triggers_login_handler(self):
        page = FakePage(translations=[json.dumps({'status': 401, 'body': ''})])
        session = dw.DoubaoSession(page)
        events = []
        session.on_login_required = lambda: events.append('login')
        session.translate(['Hello'], 'zh', lambda _: events.append('done'),
                          lambda err: events.append(type(err).__name__))
        self.assertEqual(events, ['login'])

    def test_http_403_does_not_trigger_login_guide(self):
        page = FakePage(translations=[json.dumps({'status': 403, 'body': ''})])
        session = dw.DoubaoSession(page)
        events = []
        session.on_login_required = lambda: events.append('login')
        session.translate(['Hello'], 'zh', lambda _: events.append('done'),
                          lambda err: events.append(type(err).__name__))
        self.assertEqual(events, ['DoubaoError'])

    def test_bad_stream_is_reply_error(self):
        page = FakePage(translations=[json.dumps({'status': 200, 'body': 'not SSE'})])
        out = self._run(page)
        self.assertIsInstance(out.get('error'), dw.DoubaoReplyError)

    def test_cancel_ignores_late_translation(self):
        page = FakePage()
        session = dw.DoubaoSession(page)
        out = {}
        session.translate(['Hello'], 'zh',
                          lambda texts: out.setdefault('done', texts),
                          lambda err: out.setdefault('error', err), preloaded=True)
        session.cancel()
        page.pending_translation(self._stream([{'index': 0, 'res': '你好'}]))
        self.assertEqual(out, {})


class _LoginFakePage(object):
    """登录窗假页：把同一 SSE API 的结果按队列返回。"""

    def __init__(self, responses=(), load_ok=True):
        self.responses = list(responses)
        self.load_ok = load_ok
        self.closed = False
        self._alive = True
        self._proc = None
        self.cookies_to_serve = None
        self.probe_starts = 0

    def load(self, url, cb):
        cb(self.load_ok)

    def run_js(self, script, cb):
        if dw.TAG_TRANSLATE in script:
            self.probe_starts += 1
            cb(self.responses.pop(0) if self.responses else stream_response([], 710012000))
        else:
            cb(None)

    def alive(self):
        return self._alive

    def close(self):
        self.closed = True

    def get_cookies(self, urls, cb):
        cb(self.cookies_to_serve)


class LoginWindowDedupTest(unittest.TestCase):
    # open_login_window 去重：已有存活登录窗时不重复开，回调挂到既有窗口

    def setUp(self):
        import os as _os
        _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        self.qapp = QApplication.instance() or QApplication([])
        dw._active_login = None
        self.addCleanup(setattr, dw, '_active_login', None)

    def _open(self, pages, events, tag, responses=(), timer=None):
        with patch('edge_driver.kill_profile_instances'), \
             patch('edge_driver.EdgePage',
                   lambda **kw: pages.append(_LoginFakePage(responses)) or pages[-1]):
            return dw.open_login_window(
                on_logged_in=lambda: events.append(tag + ':login'),
                on_aborted=lambda: events.append(tag + ':abort'),
                timer=timer)

    def test_second_open_reuses_alive_window(self):
        pages, events = [], []
        timer, tasks = queued_timer()
        w1 = self._open(pages, events, 'a', timer=timer)
        w2 = self._open(pages, events, 'b', timer=timer)
        self.assertIs(w1, w2)
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(tasks), 1)

    def test_reused_window_notifies_all_callers(self):
        pages, events = [], []
        timer, tasks = queued_timer()
        ok = stream_response([{'index': 0, 'res': '.'}])
        w1 = self._open(pages, events, 'a', responses=[ok], timer=timer)
        w2 = self._open(pages, events, 'b', timer=timer)
        self.assertIs(w1, w2)
        tasks.pop(0)()
        self.assertEqual(sorted(events), ['a:login', 'b:login'])

    def test_open_after_window_closed_creates_new(self):
        pages, events = [], []
        timer, _tasks = queued_timer()
        w1 = self._open(pages, events, 'a', timer=timer)
        pages[0]._alive = False
        w2 = self._open(pages, events, 'b', timer=timer)
        self.assertIsNot(w1, w2)
        self.assertEqual(len(pages), 2)


class CookieJarTest(unittest.TestCase):
    # session cookie 本地罐：登录成功时抓进 DPAPI 加密文件，下次启动 Edge 恢复

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='zbox_jar_')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.jar = os.path.join(self.tmp, 'edge_cookies.bin')

    def _entry(self, **kw):
        base = {'name': 'sessionid', 'value': 'abc', 'domain': '.doubao.com',
                'path': '/', 'secure': True, 'httpOnly': True, 'session': True}
        base.update(kw)
        return base

    def test_roundtrip_session_cookie_kept_and_expires_dropped(self):
        dw._save_cookie_jar([self._entry()], path=self.jar)
        jar = dw._load_cookie_jar(path=self.jar)
        self.assertEqual(len(jar), 1)
        c = jar[0]
        self.assertEqual(c['name'], 'sessionid')
        self.assertEqual(c['value'], 'abc')
        self.assertNotIn('expires', c)   # session cookie 恢复时不带 expires
        self.assertTrue(c['httpOnly'])

    def test_non_doubao_cookies_filtered_out(self):
        dw._save_cookie_jar([self._entry(),
                             self._entry(name='x', domain='.example.com')],
                            path=self.jar)
        jar = dw._load_cookie_jar(path=self.jar)
        self.assertEqual([c['name'] for c in jar], ['sessionid'])

    def test_expired_persistent_cookie_dropped(self):
        import time
        dw._save_cookie_jar(
            [self._entry(session=False, expires=time.time() - 10),
             self._entry(name='keep', session=False, expires=time.time() + 86400)],
            path=self.jar)
        jar = dw._load_cookie_jar(path=self.jar)
        self.assertEqual([c['name'] for c in jar], ['keep'])
        self.assertGreater(jar[0]['expires'], 0)

    def test_missing_or_corrupt_jar_returns_none(self):
        self.assertIsNone(dw._load_cookie_jar(path=self.jar))
        with open(self.jar, 'wb') as f:
            f.write(b'junk')
        self.assertIsNone(dw._load_cookie_jar(path=self.jar))

    def test_jar_file_is_not_plaintext(self):
        dw._save_cookie_jar([self._entry()], path=self.jar)
        raw = open(self.jar, 'rb').read()
        self.assertNotIn(b'abc', raw)   # DPAPI 加密（或至少不是明文 json）


class LoginWindowCookieDumpTest(unittest.TestCase):
    # 登录成功时把 cookie 抓进本地罐（含 session cookie），放弃/失败不抓

    def setUp(self):
        import os as _os
        _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        self.qapp = QApplication.instance() or QApplication([])
        self.tmp = tempfile.mkdtemp(prefix='zbox_jar_')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.jar = os.path.join(self.tmp, 'edge_cookies.bin')
        self._orig = dw._cookies_file
        dw._cookies_file = lambda: self.jar
        self.addCleanup(setattr, dw, '_cookies_file', self._orig)

    def _make(self, responses, cookies=None, load_ok=True):
        page = _LoginFakePage(responses, load_ok=load_ok)
        page.cookies_to_serve = cookies
        events = []
        with patch('edge_driver.kill_profile_instances'), \
             patch('edge_driver.EdgePage', lambda **kw: page):
            win = dw.DoubaoLoginWindow(
                on_logged_in=lambda: events.append('login'),
                on_aborted=lambda: events.append('abort'),
                timer=immediate_timer)
        return win, events

    def test_login_success_dumps_cookies_to_jar(self):
        ok = stream_response([{'index': 0, 'res': '.'}])
        jar_cookies = [{'name': 'sessionid', 'value': 'abc', 'domain': '.doubao.com',
                        'path': '/', 'secure': True, 'httpOnly': True,
                        'session': True}]
        win, events = self._make([ok], cookies=jar_cookies)
        self.assertEqual(events, ['login'])
        jar = dw._load_cookie_jar(path=self.jar)
        self.assertIsNotNone(jar)
        self.assertEqual(jar[0]['name'], 'sessionid')

    def test_abort_does_not_dump(self):
        win, events = self._make([], cookies=None, load_ok=False)
        self.assertEqual(events, ['abort'])
        self.assertIsNone(dw._load_cookie_jar(path=self.jar))


class LoginWindowTest(unittest.TestCase):
    """登录窗轮询同一流式接口，直到成功或用户关闭窗口。"""

    def _make_window(self, responses, load_ok=True):
        import os as _os
        _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        self.qapp = QApplication.instance() or QApplication([])
        page = _LoginFakePage(responses, load_ok=load_ok)
        events = []
        timer, tasks = queued_timer()
        with patch('edge_driver.kill_profile_instances'), \
             patch('edge_driver.EdgePage', lambda **kw: page):
            win = dw.DoubaoLoginWindow(
                on_logged_in=lambda: events.append('login'),
                on_aborted=lambda: events.append('abort'),
                timer=timer)
        return win, page, tasks, events

    def _pump(self, tasks, n=1):
        for _ in range(n):
            tasks.pop(0)()

    def test_retries_auth_error_until_api_accepts_translation(self):
        ok = stream_response([{'index': 0, 'res': '.'}])
        win, page, tasks, events = self._make_window(
            [stream_response([], 710012000), ok])
        self._pump(tasks)
        self.assertEqual(events, [])
        self._pump(tasks)
        self.assertEqual(events, ['login'])
        self.assertEqual(page.probe_starts, 2)
        self.assertTrue(page.closed)

    def test_user_closing_window_aborts(self):
        win, page, tasks, events = self._make_window([])
        page._alive = False
        self._pump(tasks)
        self.assertEqual(events, ['abort'])
        self.assertTrue(page.closed)

    def test_load_failure_aborts(self):
        win, page, tasks, events = self._make_window([], load_ok=False)
        self.assertEqual(events, ['abort'])


if __name__ == '__main__':
    unittest.main()