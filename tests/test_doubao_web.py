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
    """按 JS 标记串脚本化应答：probe / fill / poll 各有一队列，load 可设成败。"""

    def __init__(self, load_ok=True, probes=(), fills=(), sends=(True,), polls=()):
        self.load_ok = load_ok
        self.probes = list(probes)
        self.fills = list(fills)
        self.sends = list(sends)
        self.polls = list(polls)
        self.loaded = []
        self.scripts = []

    def load(self, url, cb):
        self.loaded.append(url)
        cb(self.load_ok)

    def run_js(self, script, cb):
        self.scripts.append(script)
        if dw.TAG_PROBE in script:
            cb(self.probes.pop(0) if self.probes else None)
        elif dw.TAG_FILL in script:
            cb(self.fills.pop(0))
        elif dw.TAG_SEND in script:
            cb(self.sends.pop(0) if self.sends else None)
        elif dw.TAG_POLL in script:
            cb(self.polls.pop(0))
        else:
            cb(None)


def immediate_timer(_ms, fn):
    fn()


def queued_timer():
    tasks = []

    def _timer(_ms, fn):
        tasks.append(fn)
    return _timer, tasks


OK_PROBE = json.dumps({'settled': True, 'logged_in': True, 'input': True})


class PureJsTest(unittest.TestCase):
    def test_probe_js_has_tag_and_login_endpoint(self):
        js = dw.build_probe_js()
        self.assertIn(dw.TAG_PROBE, js)
        self.assertIn('/alice/profile/self', js)

    def test_collect_js_evaluates_selectors(self):
        js = dw.build_probe_collect_js()
        self.assertIn('chat_input', js)

    def test_send_js_has_tag_and_selector(self):
        js = dw.build_send_js()
        self.assertIn(dw.TAG_SEND, js)
        self.assertIn('chat_input_send_button', js)

    def test_fill_js_escapes_prompt(self):
        prompt = '第一行\n带"引号"和\\反斜杠'
        js = dw.build_fill_js(prompt)
        self.assertIn(dw.TAG_FILL, js)
        # prompt 以 JSON 字符串字面量嵌入，原始换行/引号不能直接出现在 JS 里
        body = js.split(dw.TAG_FILL, 1)[1]
        self.assertNotIn('第一行\n带"引号"', body)
        self.assertIn(json.dumps(prompt), js)

    def test_poll_js_has_tag(self):
        self.assertIn(dw.TAG_POLL, dw.build_poll_js())


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
    def _run(self, page, timer=immediate_timer):
        results = {}

        def on_done(texts):
            results['done'] = texts

        def on_error(err):
            results['error'] = err

        session = dw.DoubaoSession(page, timer=timer)
        session.translate(['Hello'], 'zh', on_done, on_error)
        return results

    def test_happy_path(self):
        reply = json.dumps([{'id': 1, 'text': '你好'}], ensure_ascii=False)
        page = FakePage(probes=[True, OK_PROBE], fills=[True],
                        polls=[json.dumps({'done': False, 'text': None}),
                               json.dumps({'done': True, 'text': reply})])
        out = self._run(page)
        self.assertEqual(out.get('done'), ['你好'])
        self.assertEqual(page.loaded, [dw.CHAT_URL])

    def test_network_load_failure(self):
        page = FakePage(load_ok=False)
        out = self._run(page)
        self.assertIsInstance(out.get('error'), dw.DoubaoNetworkError)

    def test_not_logged_in_triggers_login_then_retries(self):
        reply = json.dumps([{'id': 1, 'text': '你好'}], ensure_ascii=False)
        page = FakePage(probes=[True, json.dumps({'settled': True, 'logged_in': False, 'input': True}),
                                True, OK_PROBE],
                        fills=[True], polls=[{'done': True, 'text': reply}])
        out = {}
        session = dw.DoubaoSession(page, timer=immediate_timer)
        session.on_login_required = lambda: session.notify_logged_in()
        session.translate(['Hello'], 'zh',
                          lambda texts: out.setdefault('done', texts),
                          lambda err: out.setdefault('error', err))
        self.assertEqual(out.get('done'), ['你好'])
        self.assertEqual(len(page.loaded), 2)   # 登录成功后重新走了一遍流程

    def test_structure_changed(self):
        page = FakePage(probes=[True, json.dumps({'settled': True, 'logged_in': True, 'input': False})])
        out = self._run(page)
        self.assertIsInstance(out.get('error'), dw.DoubaoStructureChanged)

    def test_fill_failure_is_structure_error(self):
        page = FakePage(probes=[True, OK_PROBE], fills=[False])
        out = self._run(page)
        self.assertIsInstance(out.get('error'), dw.DoubaoStructureChanged)

    def test_bad_reply_json(self):
        page = FakePage(probes=[True, OK_PROBE], fills=[True],
                        polls=[json.dumps({'done': True, 'text': '不是 JSON'})])
        out = self._run(page)
        self.assertIsInstance(out.get('error'), dw.DoubaoReplyError)

    def test_send_button_never_appears_is_structure_error(self):
        page = FakePage(probes=[True, OK_PROBE], fills=[True], sends=[None] * 50)
        timer, tasks = queued_timer()
        session = dw.DoubaoSession(page, timer=timer)
        out = {}
        session.translate(['Hello'], 'zh',
                          lambda texts: out.setdefault('done', texts),
                          lambda err: out.setdefault('error', err))
        for _ in range(100):
            if not tasks:
                break
            tasks.pop(0)()
        self.assertIsInstance(out.get('error'), dw.DoubaoStructureChanged)

    def test_poll_timeout(self):
        timer, tasks = queued_timer()
        page = FakePage(probes=[True, OK_PROBE], fills=[True],
                        polls=[json.dumps({'done': False, 'text': None})] * 200)
        session = dw.DoubaoSession(page, timer=timer, poll_timeout_s=5)
        out = {}
        session.translate(['Hello'], 'zh',
                          lambda texts: out.setdefault('done', texts),
                          lambda err: out.setdefault('error', err))
        for _ in range(200):
            if not tasks:
                break
            tasks.pop(0)()
        self.assertIsInstance(out.get('error'), dw.DoubaoTimeout)

    def test_unsettled_probe_keeps_polling(self):
        import json as _json
        page = FakePage(probes=[True,
                                _json.dumps({'settled': False}),
                                _json.dumps({'settled': False}),
                                OK_PROBE],
                        fills=[True],
                        polls=[_json.dumps({'done': True,
                                            'text': _json.dumps([{'id': 1, 'text': '你好'}])})])
        out = self._run(page)
        self.assertEqual(out.get('done'), ['你好'])

    def test_probe_never_settles_times_out(self):
        page = FakePage(probes=[True])   # start 成功，collect 永远 None
        session = dw.DoubaoSession(page, timer=immediate_timer)
        out = {}
        session.translate(['Hello'], 'zh',
                          lambda texts: out.setdefault('done', texts),
                          lambda err: out.setdefault('error', err))
        self.assertIsInstance(out.get('error'), dw.DoubaoTimeout)

    def test_collect_js_has_tag(self):
        self.assertIn(dw.TAG_PROBE, dw.build_probe_collect_js())
        self.assertIn('__zbox_login', dw.build_probe_collect_js())

    def test_late_result_ignored_after_cancel(self):
        timer, tasks = queued_timer()
        page = FakePage(probes=[True, OK_PROBE], fills=[True],
                        polls=[json.dumps({'done': True,
                                'text': json.dumps([{'id': 1, 'text': 'x'}])})])
        session = dw.DoubaoSession(page, timer=timer)
        out = {}
        session.translate(['Hello'], 'zh',
                          lambda texts: out.setdefault('done', texts),
                          lambda err: out.setdefault('error', err))
        session.cancel()
        while tasks:
            tasks.pop(0)()
        self.assertEqual(out, {})


class _LoginFakePage(object):
    """登录窗假页：区分探测启动（含 fetch）与收取，收取按队列脚本化应答。"""

    def __init__(self, collects, load_ok=True):
        self.collects = list(collects)
        self.load_ok = load_ok
        self.probe_starts = 0
        self.closed = False
        self._alive = True
        self._proc = None   # 无进程对象：跳过抢前台逻辑

    def load(self, url, cb):
        cb(self.load_ok)

    def run_js(self, script, cb):
        if dw.TAG_PROBE in script and 'fetch(' in script:
            self.probe_starts += 1
            cb(True)
        elif dw.TAG_PROBE in script:
            cb(self.collects.pop(0) if self.collects else '')
        else:
            cb(None)

    def alive(self):
        return self._alive

    def close(self):
        self.closed = True


class LoginWindowTest(unittest.TestCase):
    """DoubaoLoginWindow 轮询状态机：探测重发、关窗放弃、加载失败。"""

    def _make_window(self, collects, load_ok=True):
        import os as _os
        _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        self.qapp = QApplication.instance() or QApplication([])
        page = _LoginFakePage(collects, load_ok=load_ok)
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

    def test_reissues_probe_after_navigation_wipes_result(self):
        """登录跳转/重载会清掉 window.__zbox_login：连续空收必须重发探测，
        否则永远停在 collect 相位探不到登录（实测缺陷）。"""
        ok = json.dumps({'settled': True, 'logged_in': True, 'input': True})
        win, page, tasks, events = self._make_window(['', '', ok])
        self._pump(tasks)        # start：首发探测
        self._pump(tasks)        # collect 空 1（fetch 未落地/被清了）
        self._pump(tasks)        # collect 空 2 → 标记重发
        self._pump(tasks)        # start：重发探测
        self.assertEqual(page.probe_starts, 2)
        self._pump(tasks)        # collect：已登录
        self.assertEqual(events, ['login'])
        self.assertTrue(page.closed)

    def test_settled_not_logged_in_reissues_probe(self):
        win, page, tasks, events = self._make_window(
            [json.dumps({'settled': True, 'logged_in': False, 'input': True}),
             json.dumps({'settled': True, 'logged_in': True, 'input': True})])
        self._pump(tasks, 2)     # start + collect（未登录）→ 标记重发
        self.assertEqual(events, [])
        self._pump(tasks)        # start：重发探测
        self.assertEqual(page.probe_starts, 2)
        self._pump(tasks)        # collect：已登录
        self.assertEqual(events, ['login'])

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