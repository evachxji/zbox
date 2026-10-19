# -*- coding: utf-8 -*-
"""桌面格子本地化回归：确认弹窗在两种语言下都能构造（翻译函数 t 不被局部变量遮蔽）。"""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QToolButton, QWidget

import boxes
import i18n

_app = QApplication.instance() or QApplication([])


class _FakeBox(QWidget):
    """只带 rec 的最小格子替身：够 BoxConfirmDialog 与 _dissolve_confirm_dialog 用。"""

    def __init__(self, kind='blank', name='Demo'):
        super(_FakeBox, self).__init__()
        self.rec = {'kind': kind, 'name': name}


class BoxConfirmDialogI18nTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def _assert_dialog(self, lang):
        i18n.set_language(lang)
        box = _FakeBox()
        title = 'Title ' + lang
        dlg = boxes.BoxConfirmDialog(box, title, 'Body', 'OK')
        try:
            title_lbl = dlg.titlebar.findChild(QLabel)
            self.assertIsNotNone(title_lbl)
            self.assertEqual(title_lbl.text(), title)
            self.assertEqual(title_lbl.objectName(), 'boxName')

            buttons = dlg.findChildren(QPushButton)
            self.assertTrue(buttons)
            self.assertEqual(buttons[-1].text(), i18n.t('common.cancel'))

            close = dlg.titlebar.findChild(QToolButton)
            self.assertIsNotNone(close)
            self.assertEqual(close.toolTip(), i18n.t('common.close'))
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_constructs_in_chinese(self):
        self._assert_dialog(i18n.ZH)

    def test_constructs_in_english(self):
        self._assert_dialog(i18n.EN)

    def test_dissolve_confirm_path_constructs(self):
        """_dissolve_confirm_dialog 是「解散格子」二次确认的真实构造路径。"""
        i18n.set_language(i18n.ZH)
        for kind in ('blank', 'folder'):
            box = _FakeBox(kind, 'Demo')   # 弹窗以它为父，替身必须活到断言之后
            dlg = boxes.BoxWindow._dissolve_confirm_dialog(box)
            try:
                texts = [lbl.text() for lbl in dlg.findChildren(QLabel)]
                self.assertTrue(any('Demo' in text for text in texts), texts)
                self.assertIn(i18n.t('boxes.dissolve'), texts)
            finally:
                dlg.close()
                dlg.deleteLater()


if __name__ == '__main__':
    unittest.main()
