# -*- coding: utf-8 -*-
"""传输 / 视频界面本地化回归：错误映射、剩余时间格式、同名跳过标记与英文排版。"""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QLabel

import i18n
import transfer_ui
import video_dl
import video_ui


class _Cfg:
    def __init__(self, data):
        self.data = dict(data)

    def set(self, key, value):
        self.data[key] = value

    def __getattr__(self, name):
        if name in self.data:
            return self.data[name]
        raise AttributeError(name)


class _Device:
    alias = 'Pixel 6'
    port = 53327
    fingerprint = 'fp'


class _LangMixin(object):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)


class FriendlyErrTest(_LangMixin, unittest.TestCase):
    ZH_CASES = [
        ('对方未及时确认', '对方长时间未确认'),
        ('connection refused', '对方设备不在线'),
        ('10000:10061', '对方设备不在线'),
        ('10054', '连接被中断'),
        ('timed out', '连接超时'),
        ('', ''),
        ('mystery', '传输出错'),
    ]
    EN_CASES = [
        ('对方未及时确认', 'No confirmation from the other device'),
        ('connection refused', 'The other device is offline'),
        ('10000:10061', 'The other device is offline'),
        ('10054', 'Connection interrupted'),
        ('timed out', 'Connection timed out'),
        ('', ''),
        ('mystery', 'Transfer failed'),
    ]

    def test_chinese_mapping(self):
        i18n.set_language('zh-CN')
        for raw, expected in self.ZH_CASES:
            self.assertEqual(transfer_ui._friendly_err(raw), expected, raw)

    def test_english_mapping(self):
        i18n.set_language('en-US')
        for raw, expected in self.EN_CASES:
            self.assertEqual(transfer_ui._friendly_err(raw), expected, raw)


class FmtEtaTest(_LangMixin, unittest.TestCase):
    def test_chinese_format(self):
        i18n.set_language('zh-CN')
        self.assertEqual(transfer_ui._fmt_eta(0.5), '1 秒')
        self.assertEqual(transfer_ui._fmt_eta(90), '1 分 30 秒')
        self.assertEqual(transfer_ui._fmt_eta(3720), '1 小时 2 分')
        self.assertEqual(transfer_ui._fmt_eta(None), '')
        self.assertEqual(transfer_ui._fmt_eta(0), '')

    def test_english_format(self):
        i18n.set_language('en-US')
        self.assertEqual(transfer_ui._fmt_eta(0.5), '1 s')
        self.assertEqual(transfer_ui._fmt_eta(90), '1 min 30 s')
        self.assertEqual(transfer_ui._fmt_eta(3720), '1 h 2 min')
        self.assertEqual(transfer_ui._fmt_eta(None), '')
        self.assertEqual(transfer_ui._fmt_eta(0), '')


class DuplicateSkippedTest(unittest.TestCase):
    """同名跳过走 Download.start() 的真实判定（不启动真实子进程）。"""

    def _download(self):
        return video_dl.Download('https://example.invalid/v', 1080,
                                 tempfile.gettempdir(), split=True)

    def _start(self, run_once):
        dl = self._download()
        dl._run_once = run_once
        calls = []
        dl.start(lambda *args: None, lambda ok, msg: calls.append((ok, msg)))
        return calls

    def test_skipped_twice_returns_marker(self):
        calls = self._start(lambda progress_cb, dests: (0, '', True, []))
        self.assertEqual(calls, [(False, video_dl.DUPLICATE_SKIPPED)])

    def test_success_returns_output_file(self):
        calls = self._start(lambda progress_cb, dests: (0, 'a.mp4', False, []))
        self.assertEqual(calls, [(True, 'a.mp4')])

    def test_failure_returns_exit_code_text(self):
        calls = self._start(lambda progress_cb, dests: (1, '', False, []))
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0][0])
        self.assertIn('1', calls[0][1])


class EnglishLayoutTest(unittest.TestCase):
    """英文文案排版：空设备提示折行、组件状态行不溢出。"""

    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        i18n.set_language('en-US')

    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_empty_device_hint_wraps_and_fits(self):
        w = transfer_ui.TransferWidget(
            _Cfg({'transfer_dir': '', 'transfer_enabled': False}),
            _Device(), auto_start=False)
        w.resize(360, 420)
        w.show()
        self.qapp.processEvents()
        self.addCleanup(w.deleteLater)

        text = i18n.t('transfer.devices.empty')
        hints = [l for l in w.dev_box.findChildren(QLabel) if l.text() == text]
        self.assertEqual(len(hints), 1)
        hint = hints[0]
        self.assertTrue(hint.wordWrap())
        needed = hint.heightForWidth(hint.width())
        self.assertGreater(needed, 0)
        self.assertGreaterEqual(hint.height(), needed)

    def test_component_status_row_fits_available_width(self):
        w = video_ui.VideoWidget(
            _Cfg({'video_dir': tempfile.gettempdir(), 'video_quality': '1080P'}),
            auto_start=False)
        w.resize(360, 420)
        w.show()
        self.qapp.processEvents()
        self.addCleanup(w.deleteLater)

        w._on_ver('2026.1', '2026.1', '6.0', '6.0')
        self.qapp.processEvents()

        from app import sc
        spacing = sc(6) * 2                      # ver_row 两个间隙
        needed = (w.ver_lab.sizeHint().width()
                  + w.update_btn.sizeHint().width()
                  + w.uninst_btn.sizeHint().width() + spacing)
        available = w.pane.width() - 2 * sc(10)  # ver_row 左右边距
        self.assertLessEqual(needed, available)


if __name__ == '__main__':
    unittest.main()
