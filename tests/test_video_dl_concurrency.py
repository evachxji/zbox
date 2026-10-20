# -*- coding: utf-8 -*-
"""视频组件下载的并发安全回归测试（2026-10 性能审计发现）。

原缺陷：组件准备被快速开关时会起两条下载线程，两条线程写**同一个**临时文件
（tools\\.dl_partial / <目标>.new）→ 互相覆盖、读到半截数据 → 装出损坏的 exe。
"""
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import video_dl


class TestDownloadTmpUnique(unittest.TestCase):
    def test_uniq_tmp_differs_per_thread(self):
        """不同线程/进程必须拿到不同的临时文件名。"""
        base = os.path.join('tools', '.dl_partial')
        names = []
        lock = threading.Lock()

        def grab():
            n = video_dl._uniq_tmp(base)
            with lock:
                names.append(n)

        ts = [threading.Thread(target=grab) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(set(names)), 8, '并发线程的临时文件名必须互不相同：%s' % names)

    def test_uniq_tmp_keeps_prefix(self):
        """唯一化只加后缀，不改前缀（清理逻辑按前缀 glob）。"""
        n = video_dl._uniq_tmp(r'C:\x\yt-dlp.exe.new')
        self.assertTrue(n.startswith(r'C:\x\yt-dlp.exe.new'))
        self.assertNotEqual(n, r'C:\x\yt-dlp.exe.new')

    def test_try_sources_two_threads_dont_clobber(self):
        """两条线程同时下载同一批源 → 各自拿到完整内容，不互相污染。"""
        payloads = {'a': b'A' * 4096, 'b': b'B' * 4096}
        d = tempfile.mkdtemp(prefix='zbox_vdltest_')
        orig_tools_dir = video_dl.tools_dir
        orig_fetch = video_dl._fetch
        video_dl.tools_dir = lambda: d
        results = {}

        def fake_fetch(url, dst, progress_cb=None):
            body = payloads[url]
            with open(dst, 'wb') as f:
                f.write(body)
            if progress_cb:
                progress_cb(len(body), len(body))

        video_dl._fetch = fake_fetch
        try:
            def run(key):
                results[key] = video_dl._try_sources([key])

            ts = [threading.Thread(target=run, args=(k,)) for k in ('a', 'b')]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(results.get('a'), payloads['a'])
            self.assertEqual(results.get('b'), payloads['b'])
            # 临时文件应已清理
            left = [f for f in os.listdir(d) if f.startswith('.dl_partial')]
            self.assertEqual(left, [], '临时文件未清理：%s' % left)
        finally:
            video_dl.tools_dir = orig_tools_dir
            video_dl._fetch = orig_fetch
            import shutil
            shutil.rmtree(d, ignore_errors=True)


class TestCancelledPropagation(unittest.TestCase):
    def test_cancelled_is_not_treated_as_source_failure(self):
        """取消异常要穿透 _try_sources / ensure_tools，不能被当成「换下一个源」。"""
        d = tempfile.mkdtemp(prefix='zbox_vdlcancel_')
        orig_tools_dir = video_dl.tools_dir
        orig_fetch = video_dl._fetch
        video_dl.tools_dir = lambda: d

        def cancel_fetch(url, dst, progress_cb=None):
            raise video_dl._Cancelled()

        video_dl._fetch = cancel_fetch
        try:
            with self.assertRaises(video_dl._Cancelled):
                video_dl._try_sources(['x', 'y'])   # 不该去试第二个源
            with self.assertRaises(video_dl._Cancelled):
                video_dl.ensure_tools(lambda *a: None)
        finally:
            video_dl.tools_dir = orig_tools_dir
            video_dl._fetch = orig_fetch
            import shutil
            shutil.rmtree(d, ignore_errors=True)


class TestPrepConcurrencyGuard(unittest.TestCase):
    def test_prep_running_flag_blocks_second_thread(self):
        """set_enabled 快速开关时不得起第二条组件下载线程。"""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import video_ui

        w = video_ui.VideoWidget.__new__(video_ui.VideoWidget)
        w._prep_running = True
        w._prep_cancel = False
        w._prep_seq = 0
        started = []

        class _Cfg:
            def set(self, *a):
                pass

        w.cfg = _Cfg()
        w._on = False
        w.gate_msg = None
        w._show_gate = lambda mode: None
        # 已经在跑 -> 不应再起线程
        import threading as _th
        orig_thread = _th.Thread
        calls = []

        class _FakeThread(orig_thread):
            def __init__(self, *a, **k):
                calls.append(a)
                orig_thread.__init__(self, *a, **k)

        _th.Thread = _FakeThread
        try:
            w.set_enabled(True)
        finally:
            _th.Thread = orig_thread
        self.assertEqual(calls, [], '已有下载在跑时不应再起线程')


if __name__ == '__main__':
    unittest.main()
