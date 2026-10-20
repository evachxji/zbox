# -*- coding: utf-8 -*-
"""翻译准备引导窗测试：组件下载进度/成功/失败重试、豆包登录联动。"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

import i18n
import ocr_runtime
from translate_guide import TranslateGuideDialog


class _InlineThread:
    """同步执行 target 的 threading.Thread 替身。"""

    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        if self._target:
            self._target()


class TranslateGuideTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def _dialog(self):
        dlg = TranslateGuideDialog()
        self.addCleanup(dlg.close)
        return dlg

    def test_initial_state_when_component_missing(self):
        with patch('ocr_runtime.ocr_ready', return_value=False):
            dlg = self._dialog()
            self.assertTrue(dlg.dl_btn.isVisibleTo(dlg))
            self.assertFalse(dlg.dl_bar.isVisibleTo(dlg))
            self.assertTrue(dlg.login_btn.isVisibleTo(dlg))

    def test_component_ready_hides_download(self):
        with patch('ocr_runtime.ocr_ready', return_value=True):
            dlg = self._dialog()
            self.assertFalse(dlg.dl_btn.isVisibleTo(dlg))
            self.assertIn(i18n.t('shot.guide.ready'), dlg.step1_label.text())

    def test_download_progress_and_success(self):
        calls = []
        ready = {'v': False}

        def fake_download(progress_cb=None, **_kw):
            progress_cb(50, 100)
            calls.append('done')
            ready['v'] = True

        with patch('ocr_runtime.ocr_ready', lambda: ready['v']), \
             patch('ocr_runtime.download_components', side_effect=fake_download), \
             patch('translate_guide.threading.Thread', _InlineThread):
            dlg = self._dialog()
            dlg.dl_btn.click()
            self.qapp.processEvents()
            self.assertEqual(calls, ['done'])
            self.assertEqual(dlg.dl_bar.value(), 100)
            self.assertFalse(dlg.dl_btn.isVisibleTo(dlg))
            self.assertIn(i18n.t('shot.guide.ready'), dlg.step1_label.text())

    def test_progress_updates_bar(self):
        with patch('ocr_runtime.ocr_ready', return_value=False):
            dlg = self._dialog()
            dlg._on_progress(30, 60)
            self.assertEqual(dlg.dl_bar.value(), 50)

    def test_download_failure_offers_retry(self):
        with patch('ocr_runtime.ocr_ready', return_value=False), \
             patch('ocr_runtime.download_components',
                   side_effect=ocr_runtime.OcrDownloadError('boom')), \
             patch('translate_guide.threading.Thread', _InlineThread):
            dlg = self._dialog()
            dlg.dl_btn.click()
            self.qapp.processEvents()
            self.assertTrue(dlg.dl_btn.isEnabled())
            self.assertEqual(dlg.dl_btn.text(), i18n.t('shot.guide.dl_failed'))
            self.assertTrue(dlg.dl_btn.isVisibleTo(dlg))

    def test_login_success_marks_step2(self):
        with patch('ocr_runtime.ocr_ready', return_value=False):
            dlg = self._dialog()

            def _fake_login_window(on_logged_in, on_aborted=None):
                on_logged_in()   # 模拟用户在有头 Edge 里登录成功
                return object()

            with patch('doubao_web.open_login_window', _fake_login_window):
                dlg.login_btn.click()
            self.assertIn(i18n.t('shot.guide.logged_in'), dlg.step2_label.text())
            self.assertFalse(dlg.login_btn.isVisibleTo(dlg))


if __name__ == '__main__':
    unittest.main()