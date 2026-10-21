# -*- coding: utf-8 -*-
"""豆包登录引导窗测试：打开登录窗、等待中、成功、放弃后重开。"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

import i18n
from translate_guide import DoubaoLoginGuideDialog


class DoubaoLoginGuideTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def _dialog(self):
        dlg = DoubaoLoginGuideDialog()
        self.addCleanup(dlg.close)
        return dlg

    def test_initial_state_has_open_button(self):
        dlg = self._dialog()
        self.assertEqual(dlg.open_btn.text(), i18n.t('shot.login.guide.open'))
        self.assertTrue(dlg.open_btn.isEnabled())
        self.assertEqual(dlg.state_label.text(), i18n.t('shot.login.guide.desc'))

    def test_click_opens_login_window_and_waits(self):
        opened = []
        with patch('doubao_web.open_login_window',
                   lambda on_logged_in, on_aborted=None: opened.append(
                       (on_logged_in, on_aborted)) or object()):
            dlg = self._dialog()
            dlg.open_btn.click()
            self.assertEqual(len(opened), 1)
            self.assertFalse(dlg.open_btn.isEnabled())
            self.assertEqual(dlg.state_label.text(),
                             i18n.t('shot.login.guide.waiting'))

    def test_login_success_shows_ready(self):
        cbs = {}
        with patch('doubao_web.open_login_window',
                   lambda on_logged_in, on_aborted=None: cbs.update(
                       ok=on_logged_in, abort=on_aborted) or object()):
            dlg = self._dialog()
            dlg.open_btn.click()
            cbs['ok']()
            self.assertEqual(dlg.state_label.text(),
                             i18n.t('shot.login.guide.done'))
            self.assertTrue(dlg.open_btn.isEnabled())
            self.assertEqual(dlg.open_btn.text(), i18n.t('common.close'))

    def test_window_icon_is_zbox_logo(self):
        from app import make_icon
        dlg = self._dialog()
        self.assertFalse(dlg.windowIcon().isNull())
        self.assertEqual(dlg.windowIcon().pixmap(32, 32).toImage(),
                         make_icon().pixmap(32, 32).toImage())

    def test_always_on_top_above_pin_windows(self):
        from PySide6.QtCore import Qt
        dlg = self._dialog()
        self.assertTrue(dlg.windowFlags() & Qt.WindowStaysOnTopHint)

    def test_desc_stresses_first_time_only(self):
        # 强调仅首次需要登录：两种语言的文案都要表达这层意思
        import i18n_zh
        import i18n_en
        self.assertIn('仅首次', i18n_zh.CATALOG['shot.login.guide.desc'])
        self.assertIn('first', i18n_en.CATALOG['shot.login.guide.desc'].lower())

    def test_aborted_re_enables_button(self):
        cbs = {}
        with patch('doubao_web.open_login_window',
                   lambda on_logged_in, on_aborted=None: cbs.update(
                       ok=on_logged_in, abort=on_aborted) or object()):
            dlg = self._dialog()
            dlg.open_btn.click()
            cbs['abort']()
            self.assertTrue(dlg.open_btn.isEnabled())
            self.assertEqual(dlg.open_btn.text(), i18n.t('shot.login.guide.open'))
            # 可再次点击重开登录窗
            dlg.open_btn.click()
            self.assertFalse(dlg.open_btn.isEnabled())


if __name__ == '__main__':
    unittest.main()