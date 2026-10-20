# -*- coding: utf-8 -*-
"""Edge CDP 驱动测试：Edge 定位、DevToolsActivePort、attach-or-launch、CDP 连接与 page 适配。"""
import json
import os
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

import edge_driver as ed


class FakeWs(object):
    """websocket.create_connection 替身：脚本化收发。"""

    def __init__(self):
        self.sent = []
        self.inbox = queue.Queue()
        self.closed = False

    def send(self, data):
        self.sent.append(json.loads(data))

    def recv(self):
        item = self.inbox.get(timeout=5)
        if item is None:
            return ''
        return item

    def close(self):
        self.closed = True
        self.inbox.put(None)


class PortFileTest(unittest.TestCase):
    def test_read_valid_file(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'DevToolsActivePort'), 'w') as f:
                f.write('53327\n/devtools/browser/abc')
            self.assertEqual(ed.read_devtools_port(d), (53327, '/devtools/browser/abc'))

    def test_missing_or_malformed(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(ed.read_devtools_port(d))
            with open(os.path.join(d, 'DevToolsActivePort'), 'w') as f:
                f.write('not-a-port')
            self.assertIsNone(ed.read_devtools_port(d))


class FindEdgeTest(unittest.TestCase):
    def test_registry_hit(self):
        with patch('edge_driver._reg_edge', return_value=r'C:\Edge\msedge.exe'), \
             patch('os.path.isfile', return_value=True):
            self.assertEqual(ed.find_edge(), r'C:\Edge\msedge.exe')
            self.assertTrue(ed.supported())

    def test_fallback_paths(self):
        with patch('edge_driver._reg_edge', return_value=None), \
             patch('os.path.isfile', lambda p: p.endswith('msedge.exe')):
            self.assertTrue(ed.find_edge().endswith('msedge.exe'))

    def test_missing(self):
        with patch('edge_driver._reg_edge', return_value=None), \
             patch('os.path.isfile', return_value=False):
            self.assertIsNone(ed.find_edge())
            self.assertFalse(ed.supported())


class AttachLaunchTest(unittest.TestCase):
    def test_attach_to_alive_instance(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'DevToolsActivePort'), 'w') as f:
                f.write('53327\n/devtools/browser/abc')
            popen_calls = []
            with patch('edge_driver._http_json', return_value={'Browser': 'Edge'}), \
                 patch('edge_driver.subprocess.Popen',
                       side_effect=lambda *a, **k: popen_calls.append(1)):
                port, proc = ed.attach_or_launch(d, headless=True, edge_path=r'C:\Edge\msedge.exe')
            self.assertEqual(port, 53327)
            self.assertIsNone(proc)          # 直连，不起新进程
            self.assertEqual(popen_calls, [])

    def test_launch_when_stale(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'DevToolsActivePort'), 'w') as f:
                f.write('53327\n/devtools/browser/abc')

            class _Proc:
                pid = 123

            def fake_http(url, **kw):
                if 'json/version' in url:
                    return None                       # 端口文件是死的
                return {'id': 'T1', 'webSocketDebuggerUrl': 'ws://x'}

            with patch('edge_driver._http_json', side_effect=fake_http), \
                 patch('edge_driver.subprocess.Popen', return_value=_Proc()) as popen, \
                 patch('edge_driver.read_devtools_port',
                       side_effect=[(53327, '/x'), (53328, '/y')]):
                port, proc = ed.attach_or_launch(d, headless=True,
                                                 edge_path=r'C:\Edge\msedge.exe',
                                                 wait_s=0.01)
            self.assertEqual(port, 53328)
            self.assertIsNotNone(proc)
            args = popen.call_args[0][0]
            self.assertIn('--headless=new', args)
            self.assertIn('--remote-debugging-port=0', args)
            self.assertIn('--remote-allow-origins=*', args)   # 新版 Chromium 默认拒绝带 Origin 的 WS
            self.assertIn('--user-data-dir=' + d, args)

    def test_headed_omits_headless_flag(self):
        with tempfile.TemporaryDirectory() as d:
            class _Proc:
                pid = 1
            with patch('edge_driver._http_json', return_value=None), \
                 patch('edge_driver.subprocess.Popen', return_value=_Proc()) as popen, \
                 patch('edge_driver.read_devtools_port', return_value=(53329, '/y')):
                ed.attach_or_launch(d, headless=False, edge_path=r'C:\Edge\msedge.exe',
                                    wait_s=0.01)
            args = popen.call_args[0][0]
            self.assertNotIn('--headless=new', args)


class CdpConnectionTest(unittest.TestCase):
    def _conn(self):
        ws = FakeWs()
        conn = ed.CdpConnection('ws://fake', ws_factory=lambda url, **kw: ws)
        return conn, ws

    def test_id_pairing_out_of_order(self):
        conn, ws = self._conn()
        got = {}
        conn.send('Runtime.evaluate', {'expression': '1'}, lambda m: got.setdefault(1, m))
        conn.send('Runtime.evaluate', {'expression': '2'}, lambda m: got.setdefault(2, m))
        id1, id2 = ws.sent[0]['id'], ws.sent[1]['id']
        self.assertNotEqual(id1, id2)
        ws.inbox.put(json.dumps({'id': id2, 'result': {'result': {'value': 'two'}}}))
        ws.inbox.put(json.dumps({'id': id1, 'result': {'result': {'value': 'one'}}}))
        for _ in range(50):
            if len(got) == 2:
                break
            threading.Event().wait(0.02)
        self.assertEqual(got[1]['result']['result']['value'], 'one')
        self.assertEqual(got[2]['result']['result']['value'], 'two')
        conn.close()

    def test_large_message(self):
        conn, ws = self._conn()
        got = {}
        conn.send('Runtime.evaluate', {}, lambda m: got.setdefault('r', m))
        big = 'x' * 300000
        ws.inbox.put(json.dumps({'id': ws.sent[0]['id'],
                                 'result': {'result': {'value': big}}}))
        for _ in range(50):
            if got:
                break
            threading.Event().wait(0.02)
        self.assertEqual(len(got['r']['result']['result']['value']), 300000)
        conn.close()

    def test_event_dispatch(self):
        conn, ws = self._conn()
        events = []
        conn.on('Page.loadEventFired', lambda params: events.append(params))
        ws.inbox.put(json.dumps({'method': 'Page.loadEventFired',
                                 'params': {'timestamp': 1.5}}))
        for _ in range(50):
            if events:
                break
            threading.Event().wait(0.02)
        self.assertEqual(events, [{'timestamp': 1.5}])
        conn.close()

    def test_close_fails_pending(self):
        conn, ws = self._conn()
        got = {}
        conn.send('Runtime.evaluate', {}, lambda m: got.setdefault('r', m))
        ws.inbox.put(None)   # 连接断
        for _ in range(50):
            if got:
                break
            threading.Event().wait(0.02)
        self.assertIn('error', got['r'])
        self.assertTrue(conn.closed)


class EdgePageTest(unittest.TestCase):
    def _page(self, ws=None):
        ws = ws or FakeWs()
        conn = ed.CdpConnection('ws://fake', ws_factory=lambda url, **kw: ws)
        page = ed.EdgePage.__new__(ed.EdgePage)
        page._headless = True
        page._profile = None
        page._conn = conn
        page._proc = None
        page._target = 'T1'
        page._launcher = None
        page._conn_factory = None
        page._target_url = None
        return page, ws

    def _wait(self, fn, times=100):
        for _ in range(times):
            if fn():
                return True
            threading.Event().wait(0.02)
        return False

    def test_run_js_returns_value(self):
        page, ws = self._page()
        got = {}
        page.run_js('({a:1})', lambda v: got.setdefault('v', v))
        ws.inbox.put(json.dumps({'id': ws.sent[0]['id'],
                                 'result': {'result': {'value': {'a': 1}}}}))
        self.assertTrue(self._wait(lambda: 'v' in got))
        self.assertEqual(got['v'], {'a': 1})
        # 请求参数符合 CDP 契约
        params = ws.sent[0]['params']
        self.assertTrue(params['returnByValue'])
        self.assertTrue(params['awaitPromise'])
        self.assertEqual(params['expression'], '({a:1})')

    def test_run_js_exception_details_gives_none(self):
        page, ws = self._page()
        got = {}
        page.run_js('bad()', lambda v: got.__setitem__('v', v))
        ws.inbox.put(json.dumps({'id': ws.sent[0]['id'],
                                 'result': {'exceptionDetails': {'text': 'boom'}}}))
        self.assertTrue(self._wait(lambda: 'v' in got))
        self.assertIsNone(got['v'])

    def test_run_js_cdp_error_gives_none(self):
        page, ws = self._page()
        got = {}
        page.run_js('x', lambda v: got.__setitem__('v', v))
        ws.inbox.put(json.dumps({'id': ws.sent[0]['id'],
                                 'error': {'message': 'fail'}}))
        self.assertTrue(self._wait(lambda: 'v' in got))
        self.assertIsNone(got['v'])

    def test_load_waits_load_event(self):
        page, ws = self._page()
        got = {}
        page.load('https://example.com', lambda ok: got.setdefault('ok', ok))
        # 先发 Page.enable / Page.navigate 应答
        self.assertTrue(self._wait(lambda: len(ws.sent) >= 2))
        methods = [m['method'] for m in ws.sent]
        self.assertEqual(methods, ['Page.enable', 'Page.navigate'])
        for m in ws.sent:
            ws.inbox.put(json.dumps({'id': m['id'], 'result': {}}))
        self.assertTrue(self._wait(lambda: len(ws.inbox.queue) == 0))
        ws.inbox.put(json.dumps({'method': 'Page.loadEventFired', 'params': {}}))
        self.assertTrue(self._wait(lambda: 'ok' in got))
        self.assertTrue(got['ok'])

    def test_load_navigate_error_text(self):
        page, ws = self._page()
        got = {}
        page.load('https://bad', lambda ok: got.setdefault('ok', ok))
        self.assertTrue(self._wait(lambda: len(ws.sent) >= 2))
        ws.inbox.put(json.dumps({'id': ws.sent[0]['id'], 'result': {}}))
        ws.inbox.put(json.dumps({'id': ws.sent[1]['id'],
                                 'result': {'errorText': 'net::ERR_NAME_NOT_RESOLVED'}}))
        self.assertTrue(self._wait(lambda: 'ok' in got))
        self.assertFalse(got['ok'])


if __name__ == '__main__':
    unittest.main()