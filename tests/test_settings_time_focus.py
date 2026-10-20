# -*- coding: utf-8 -*-
"""设置窗时间框：点击窗口空白处（含标题栏）即失焦，editingFinished 归一化落盘。

回归背景：午休/下班时间框原先只有点到桌面（整个窗口失焦）才触发 editingFinished；
在设置窗内部点其他区域时空白处没有可聚焦控件，输入框一直挂着编辑态不落盘。
"""
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import i18n
from app import Config, SettingsDialog


class _PanelStub(QWidget):
    class Transfer:
        def service_enabled(self):
            return False

        def set_enabled(self, value):
            return value

        enabled_changed = type('Sig', (), {'connect': lambda *args: None})()

    class Video:
        def service_enabled(self):
            return False

        def set_enabled(self, value):
            return value

        enabled_changed = type('Sig', (), {'connect': lambda *args: None})()

    _theme = 'nocturne'
    transfer = Transfer()
    video = Video()

    def __init__(self):
        super(_PanelStub, self).__init__()
        self.cal = MagicMock()

    def apply_theme(self, _key):
        pass

    def frameGeometry(self):
        return QApplication.primaryScreen().availableGeometry()


class SettingsTimeFocusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        i18n.set_language(i18n.ZH)
        with patch('app.sysutil.autostart_get', return_value=False):
            self.panel = _PanelStub()
            self.panel.cfg = Config(os.devnull)
            self.dlg = SettingsDialog(self.panel, lambda *a, **k: None, lambda: None)
        self.addCleanup(self.panel.close)
        self.addCleanup(self.dlg.close)
        self.dlg.show()
        self.qapp.processEvents()

    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def _click_titlebar(self):
        QTest.mouseClick(self.dlg.titlebar, Qt.LeftButton,
                         pos=QPoint(self.dlg.titlebar.width() // 2, 10))
        self.qapp.processEvents()

    def test_click_blank_commits_evening_field(self):
        cfg = self.panel.cfg
        evening = self.dlg._time_rows[-1][0]   # 热键、午休起止之后最后登记的是下班框
        evening.setFocus()
        evening.setText('25:61')   # 解析不了：输入中途不落半截状态
        self.assertEqual(cfg.data['off_evening'], '18:00')

        self._click_titlebar()
        self.assertEqual(cfg.data['off_evening'], '')   # 失焦归一化：无效即清空落盘
        self.assertEqual(evening.text(), '')

    def test_click_blank_commits_noon_pair(self):
        cfg = self.panel.cfg
        noon_a, noon_b = self.dlg._time_rows[1][0], self.dlg._time_rows[2][0]
        noon_b.setFocus()
        noon_b.setText('99')   # 单端失效：输入中途不覆盖原配置
        self.assertEqual(cfg.data['off_noon'], '12:00-13:00')

        self._click_titlebar()
        self.assertEqual(cfg.data['off_noon'], '')   # 另一端无效：整体存空
        self.assertEqual(noon_a.text(), '12:00')     # 能解析的框归一化后留着等补齐
        self.assertEqual(noon_b.text(), '')


if __name__ == '__main__':
    unittest.main()
