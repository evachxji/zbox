# -*- coding: utf-8 -*-
"""OCR 运行时测试：helper 命令拼装、组件就绪判定、pip 镜像链安装、stdio 协议。"""
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import ocr_runtime


FAKE_HELPER = '''
import json, struct, sys
n = struct.unpack("<I", sys.stdin.buffer.read(4))[0]
png = sys.stdin.buffer.read(n)
if png.startswith(b"SLEEP"):
    import time; time.sleep(30)
elif png.startswith(b"BADEXIT"):
    sys.stderr.write("boom"); sys.exit(3)
elif png.startswith(b"GARBAGE"):
    sys.stdout.write("not json\\n"); sys.exit(0)
else:
    sys.stdout.write(json.dumps({"version": 1, "regions": [
        {"text": "ok", "confidence": 0.9,
         "quad": [[0,0],[1,0],[1,1],[0,1]], "bbox": [0, 0, 1, 1]}]}) + "\\n")
'''


class HelperCmdTest(unittest.TestCase):
    def test_source_cmd_points_at_repo_script(self):
        with patch.object(sys, 'frozen', False, create=True):
            cmd = ocr_runtime.helper_cmd()
        self.assertEqual(cmd[0], sys.executable)
        self.assertTrue(cmd[1].endswith('ocr_helper.py'))

    def test_frozen_cmd_uses_exe_sub_mode(self):
        with patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, 'executable', r'C:\zbox\zbox.exe'):
            cmd = ocr_runtime.helper_cmd()
        self.assertEqual(cmd, [r'C:\zbox\zbox.exe', '--ocr-helper'])

    def test_stdio_cmd_appends_args(self):
        cmd = ocr_runtime.stdio_cmd()
        self.assertEqual(cmd[-3:], ['--site-packages',
                                    ocr_runtime.site_packages_dir(), '--stdio'])


class ReadyTest(unittest.TestCase):
    def _plant(self, d, version, packages=True):
        with open(os.path.join(d, 'component.json'), 'w') as f:
            json.dump({'version': version}, f)
        if packages:
            sp = os.path.join(d, 'site-packages')
            for pkg in ('rapidocr_onnxruntime', 'onnxruntime', 'numpy', 'cv2'):
                os.makedirs(os.path.join(sp, pkg))

    def test_ready_requires_marker_and_packages(self):
        with tempfile.TemporaryDirectory() as d:
            with patch('ocr_runtime.ocr_dir', return_value=d):
                self.assertFalse(ocr_runtime.ocr_ready())      # 无标记
                self._plant(d, ocr_runtime.COMPONENT_VERSION, packages=False)
                self.assertFalse(ocr_runtime.ocr_ready())      # 无包
                self._plant(d, ocr_runtime.COMPONENT_VERSION)
                self.assertTrue(ocr_runtime.ocr_ready())

    def test_version_mismatch_not_ready(self):
        with tempfile.TemporaryDirectory() as d:
            self._plant(d, ocr_runtime.COMPONENT_VERSION - 1)
            with patch('ocr_runtime.ocr_dir', return_value=d):
                self.assertFalse(ocr_runtime.ocr_ready())


class DownloadTest(unittest.TestCase):
    def test_installs_all_packages_with_mirror_fallback(self):
        calls = []

        def fake_install(pkg, mirror, target):
            calls.append((pkg, mirror))
            # 第一包在第一个镜像失败，验证回退
            return (mirror != ocr_runtime.PIP_MIRRORS[0] or pkg != 'six'), ''

        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, 'ocr')
            progress = []
            with patch('ocr_runtime.ocr_dir', return_value=target):
                ocr_runtime.download_components(
                    progress_cb=lambda dn, tot: progress.append((dn, tot)),
                    install_one=fake_install)
            self.assertEqual(progress[-1], (len(ocr_runtime.PIP_PACKAGES),
                                            len(ocr_runtime.PIP_PACKAGES)))
            # six 在镜像 1 失败后回退镜像 2
            six_calls = [c for c in calls if c[0] == 'six']
            self.assertEqual([m for _p, m in six_calls],
                             ocr_runtime.PIP_MIRRORS[:2])
            self.assertTrue(os.path.isfile(os.path.join(target, 'component.json')))

    def test_all_mirrors_fail_cleans_staging(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, 'ocr')
            with patch('ocr_runtime.ocr_dir', return_value=target):
                with self.assertRaises(ocr_runtime.OcrDownloadError):
                    ocr_runtime.download_components(
                        install_one=lambda pkg, mirror, t: (False, 'boom'))
            self.assertFalse(os.path.exists(target))
            self.assertEqual([x for x in os.listdir(d) if x.startswith('.ocr_stage_')], [])

    def test_old_component_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, 'ocr')
            os.makedirs(target)
            open(os.path.join(target, 'ocr_helper.exe'), 'w').close()   # v1 残留
            with patch('ocr_runtime.ocr_dir', return_value=target):
                ocr_runtime.download_components(
                    install_one=lambda pkg, mirror, t: (True, ''))
            self.assertFalse(os.path.exists(os.path.join(target, 'ocr_helper.exe')))
            self.assertTrue(os.path.isdir(os.path.join(target, 'site-packages')))


class RunOcrTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.helper = os.path.join(self.tmp.name, 'fake_helper.py')
        with open(self.helper, 'w', encoding='utf-8') as f:
            f.write(FAKE_HELPER)
        self.cmd = [sys.executable, self.helper, '--stdio']

    def tearDown(self):
        self.tmp.cleanup()

    def test_encode_request_frame(self):
        frame = ocr_runtime.encode_request(b'PNGDATA')
        self.assertEqual(struct.unpack('<I', frame[:4])[0], 7)
        self.assertEqual(frame[4:], b'PNGDATA')

    def test_run_ocr_roundtrip(self):
        regions = ocr_runtime.run_ocr(b'\x89PNG-fake', cmd=self.cmd, timeout=10)
        self.assertEqual(regions[0].text, 'ok')

    def test_run_ocr_applies_scale(self):
        regions = ocr_runtime.run_ocr(b'\x89PNG-fake', cmd=self.cmd, timeout=10, scale=2.0)
        self.assertEqual(regions[0].bbox, (0, 0, 2, 2))

    def test_bad_exit_raises_with_stderr(self):
        with self.assertRaises(ocr_runtime.OcrRuntimeError) as ctx:
            ocr_runtime.run_ocr(b'BADEXIT', cmd=self.cmd, timeout=10)
        self.assertIn('boom', str(ctx.exception))

    def test_garbage_output_raises_protocol_error(self):
        import translation_core
        with self.assertRaises(translation_core.OcrProtocolError):
            ocr_runtime.run_ocr(b'GARBAGE', cmd=self.cmd, timeout=10)

    def test_timeout_kills_process(self):
        with self.assertRaises(ocr_runtime.OcrTimeout):
            ocr_runtime.run_ocr(b'SLEEP', cmd=self.cmd, timeout=1)

    def test_cancel_event_kills_process(self):
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        timer.start()
        try:
            with self.assertRaises(ocr_runtime.OcrCancelled):
                ocr_runtime.run_ocr(b'SLEEP', cmd=self.cmd, timeout=30, cancel_event=cancel)
        finally:
            timer.cancel()

    def test_not_ready_raises(self):
        with patch('ocr_runtime.ocr_ready', return_value=False):
            with self.assertRaises(ocr_runtime.OcrRuntimeError):
                ocr_runtime.run_ocr(b'x')


class WheelPickTest(unittest.TestCase):
    """mini wheel 安装器的选包/校验逻辑（ocr_helper 纯函数）。"""
    INDEX = """
<a href="https://mirror/pkgs/numpy-2.1.3-cp312-cp312-win_amd64.whl#sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">numpy-2.1.3-cp312-cp312-win_amd64.whl</a>
<a href="https://mirror/pkgs/numpy-2.2.0-cp312-cp312-win_amd64.whl#sha256=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb">numpy-2.2.0-cp312-cp312-win_amd64.whl</a>
<a href="https://mirror/pkgs/numpy-2.2.0-cp311-cp311-win_amd64.whl#sha256=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc">numpy-2.2.0-cp311-cp311-win_amd64.whl</a>
<a href="https://mirror/pkgs/numpy-2.2.0-cp312-cp312-win32.whl#sha256=dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd">numpy-2.2.0-cp312-cp312-win32.whl</a>
<a href="https://mirror/pkgs/numpy-2.2.0.tar.gz#sha256=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee">numpy-2.2.0.tar.gz</a>
"""
    ABI3_INDEX = """
<a href="https://m/cv-4.10.0.84-cp37-abi3-win_amd64.whl#sha256=ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff">opencv_python_headless-4.10.0.84-cp37-abi3-win_amd64.whl</a>
<a href="https://m/cv-4.11.0.86-cp37-abi3-win_amd64.whl#sha256=0000000000000000000000000000000000000000000000000000000000000000">opencv_python_headless-4.11.0.86-cp37-abi3-win_amd64.whl</a>
"""
    PURE_INDEX = """
<a href="https://m/six-1.16.0-py2.py3-none-any.whl#sha256=1111111111111111111111111111111111111111111111111111111111111111">six-1.16.0-py2.py3-none-any.whl</a>
<a href="https://m/six-1.17.0-py2.py3-none-any.whl#sha256=2222222222222222222222222222222222222222222222222222222222222222">six-1.17.0-py2.py3-none-any.whl</a>
"""

    def test_picks_latest_compatible_binary_wheel(self):
        import ocr_helper
        url, sha, ver = ocr_helper.pick_wheel(self.INDEX, 'numpy', None)
        self.assertIn('numpy-2.2.0-cp312-cp312-win_amd64.whl', url)
        self.assertEqual(sha, 'b' * 64)
        self.assertEqual(ver, '2.2.0')

    def test_pin_exact_version(self):
        import ocr_helper
        url, sha, ver = ocr_helper.pick_wheel(self.INDEX, 'numpy', '2.1.3')
        self.assertIn('2.1.3', url)

    def test_abi3_wheel_accepted(self):
        import ocr_helper
        url, _s, ver = ocr_helper.pick_wheel(self.ABI3_INDEX,
                                             'opencv-python-headless', None)
        self.assertEqual(ver, '4.11.0.86')

    def test_pure_python_wheel(self):
        import ocr_helper
        url, sha, ver = ocr_helper.pick_wheel(self.PURE_INDEX, 'six', None)
        self.assertEqual(ver, '1.17.0')
        self.assertEqual(sha, '2' * 64)

    def test_no_compatible_raises(self):
        import ocr_helper
        with self.assertRaises(ocr_helper.InstallError):
            ocr_helper.pick_wheel('<a href="x.tar.gz">x</a>', 'numpy', None)

    def test_relative_url_joined_with_base(self):
        import ocr_helper
        html = ('<a href="../../packages/ab/six-1.17.0-py2.py3-none-any.whl">'
                'six-1.17.0-py2.py3-none-any.whl</a>')
        url, _s, _v = ocr_helper.pick_wheel(
            html, 'six', None, base_url='https://mirror.cn/pypi/simple/six/')
        self.assertEqual(
            url, 'https://mirror.cn/pypi/packages/ab/six-1.17.0-py2.py3-none-any.whl')

    def test_prerelease_versions_skipped(self):
        import ocr_helper
        html = ('<a href="https://m/numpy-2.5.0rc1-cp312-cp312-win_amd64.whl">'
                'numpy-2.5.0rc1-cp312-cp312-win_amd64.whl</a>'
                '<a href="https://m/numpy-2.4.2-cp312-cp312-win_amd64.whl">'
                'numpy-2.4.2-cp312-cp312-win_amd64.whl</a>')
        _u, _s, ver = ocr_helper.pick_wheel(html, 'numpy', None)
        self.assertEqual(ver, '2.4.2')

    def test_version_key_orders_numerically(self):
        import ocr_helper
        self.assertGreater(ocr_helper._version_key('4.10.0.84'),
                           ocr_helper._version_key('4.9.0.80'))
        self.assertGreater(ocr_helper._version_key('1.31.0'),
                           ocr_helper._version_key('1.9.9'))


class CliTest(unittest.TestCase):
    def test_cli_rejects_bad_args(self):
        import ocr_helper
        self.assertEqual(ocr_helper.cli([]), 2)
        self.assertEqual(ocr_helper.cli(['--stdio']), 2)


if __name__ == '__main__':
    unittest.main()