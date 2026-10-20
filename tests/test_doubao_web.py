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


if __name__ == '__main__':
    unittest.main()