# -*- coding: utf-8 -*-
"""下载子进程异常时必须被杀（不留孤儿）——2026-10 性能审计 P0-5 的回归测试。

原缺陷：Download.start() 的异常分支只把 self._proc 置 None 就返回，
yt-dlp 子进程**继续跑着下载并写文件**（孤儿进程：占 CPU/带宽、输出目录留下
半成品，程序退出时也再也终止不了它）。
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import video_dl


class _FakeProc:
    """假装是 yt-dlp 子进程：stdout 里给一行进度（触发 progress_cb 抛异常）。"""

    def __init__(self):
        self.pid = 4242
        self.stdout = io.StringIO('[download]  10.0% of 1.00MiB at 1MiB/s ETA 00:01\n')

    def wait(self, timeout=None):
        return 1

    def terminate(self):
        pass

    def kill(self):
        pass


class TestOrphanProcess(unittest.TestCase):
    def test_exception_kills_child_process(self):
        """progress_cb 抛异常时，子进程必须被杀掉（_kill_tree 被调用）。"""
        killed = []
        done = []

        d = video_dl.Download.__new__(video_dl.Download)
        d.cmd = ['yt-dlp', 'x']
        d._height = 240
        d._split = False
        d._out_dir = os.path.abspath('.')
        d._proc = None
        d._terminated = False
        d._paused = False
        d._resume_evt = __import__('threading').Event()

        def boom(*a, **k):
            raise RuntimeError('模拟回调异常')

        # 让 _run_once 抛异常（模拟 progress_cb 抛错）
        d._run_once = boom
        d._kill_tree = lambda: killed.append(1)
        d._cleanup_parts = lambda dests: None

        d.start(lambda *a: None, lambda ok, msg: done.append((ok, msg)))

        self.assertEqual(killed, [1], '异常分支必须先杀子进程再置空 _proc')
        self.assertEqual(len(done), 1, '异常也要回调一次 done_cb')
        self.assertFalse(done[0][0], '异常时 done_cb 的 ok 应为 False')

    def test_kill_tree_uses_taskkill_tree(self):
        """_kill_tree 用 taskkill /T /F 杀整棵树（yt-dlp 是双进程结构）。"""
        calls = []
        orig_run = video_dl.subprocess.run

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return None

        d = video_dl.Download.__new__(video_dl.Download)
        d._proc = _FakeProc()
        video_dl.subprocess.run = fake_run
        try:
            d._kill_tree()
        finally:
            video_dl.subprocess.run = orig_run
        self.assertTrue(calls, '_kill_tree 应调用 taskkill')
        self.assertIn('/T', calls[0], '必须带 /T 杀整棵进程树')
        self.assertIn('/F', calls[0], '必须带 /F 强制结束')


if __name__ == '__main__':
    unittest.main()
