# -*- coding: utf-8 -*-
"""顶部栏（悬浮滑出 tab 栏）边角缩放：栏窗是独立顶层窗，展开时盖住面板顶边，
边角的缩放命中要在栏窗上做、拖拽手动改面板几何（命中边角优先于拖拽移动）。"""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import app as ui
import calendar_data as cd
import i18n


class BarResizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        i18n.set_language(i18n.ZH)
        # FloatingPanel 构造会写全局状态（应用级 QSS、数字字体选择），
        # 用后还原，避免污染同进程排后面的测试
        self._qss_backup = None if QApplication.instance() is None else \
            QApplication.instance().styleSheet()
        self._num_font_backup = ui._NUM_FONT['name']
        self._tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmp, True)
        self.cfg = ui.Config(os.path.join(self._tmp, 'config.json'))
        self.panel = ui.FloatingPanel(
            self.cfg, cd.HolidayStore(os.path.join(self._tmp, 'holidays.json')),
            ui.TodoStore(os.path.join(self._tmp, 'todos.json')),
            transfer_autostart=False, video_autostart=False)
        self.addCleanup(self.panel.close_panel)
        self.addCleanup(self.panel.deleteLater)
        self.panel.setGeometry(400, 300, 420, 400)
        self.panel.show()
        # 栏窗直接摆到展开终态（跳过滑出动画等待）
        self.panel._tb_anim.stop()
        self.panel.titlebar.show()
        self.panel._set_tb_height(ui.sc(42))
        self.qapp.processEvents()
        self.bar = self.panel.titlebar

    def tearDown(self):
        QApplication.instance().setStyleSheet(self._qss_backup)
        ui._NUM_FONT['name'] = self._num_font_backup
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def _bar_event(self, etype, lx, ly, gx, gy, buttons=Qt.LeftButton):
        return QMouseEvent(etype, QPointF(lx, ly), QPointF(gx, gy),
                           Qt.LeftButton, buttons, Qt.NoModifier)

    def _hover(self, x, y):
        """合成悬停 MouseMove 直送栏窗（sendEvent 走 eventFilter，与平台光标状态无关：
        QTest.mouseMove 在 offscreen 下依赖真实光标轨迹，前面测试动过 QCursor 会丢事件）。"""
        ev = QMouseEvent(QEvent.MouseMove, QPointF(x, y), QPointF(x, y),
                         Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(self.bar, ev)

    def test_hover_corner_shows_resize_cursor(self):
        self._hover(2, 2)
        self.assertEqual(self.bar.cursor().shape(), Qt.SizeFDiagCursor)
        self._hover(self.bar.width() - 2, 2)
        self.assertEqual(self.bar.cursor().shape(), Qt.SizeBDiagCursor)
        self._hover(self.bar.width() * 3 // 4, self.bar.height() // 2)
        self.assertEqual(self.bar.cursor().shape(), Qt.ArrowCursor)

    def test_corner_drag_resizes_panel(self):
        g0 = self.panel.geometry()
        w, h = self.bar.width(), self.bar.height()
        self.panel.eventFilter(self.bar, self._bar_event(
            QEvent.MouseButtonPress, w - 2, 2, 1000, 500))
        self.assertIsNotNone(self.panel._tb_resize)   # 右上角命中，不落到拖拽
        # 向左 40、向下 30：宽度减 40，顶边下移 30（高度减 30）
        self.panel.eventFilter(self.bar, self._bar_event(
            QEvent.MouseMove, w - 2, 2, 960, 530))
        g1 = self.panel.geometry()
        self.assertEqual(g1.width(), g0.width() - 40)
        self.assertEqual(g1.top(), g0.top() + 30)
        self.assertEqual(g1.height(), g0.height() - 30)
        # 栏窗随面板缩放保持贴合（_sync_bar）：同宽、底边探进面板顶边一个圆角半径
        ov = int(ui.bar_corner_radius(self.bar))
        self.assertEqual(self.bar.width(), g1.width())
        self.assertEqual(self.bar.geometry().bottom(), g1.top() + ov - 1)
        self.panel.eventFilter(self.bar, self._bar_event(
            QEvent.MouseButtonRelease, w - 2, 2, 960, 530, Qt.NoButton))
        self.assertIsNone(self.panel._tb_resize)
        self.assertFalse(self.panel._sizing)
        self.assertEqual(self.cfg.data['size'], [g1.width(), g1.height()])

    def test_corner_drag_clamps_to_minimum_size(self):
        w = self.bar.width()
        self.panel.eventFilter(self.bar, self._bar_event(
            QEvent.MouseButtonPress, w - 2, 2, 1000, 500))
        self.panel.eventFilter(self.bar, self._bar_event(
            QEvent.MouseMove, w - 2, 2, 0, 1500))   # 大幅左移 + 下拉，宽高都越过最小尺寸
        g = self.panel.geometry()
        self.assertEqual(g.width(), self.panel.minimumWidth())
        self.assertEqual(g.height(), self.panel.minimumHeight())
        self.panel.eventFilter(self.bar, self._bar_event(
            QEvent.MouseButtonRelease, w - 2, 2, 0, 1500, Qt.NoButton))

    def test_center_press_still_drags_panel(self):
        """栏窗中部（非边角）按下仍是拖拽移动，不被缩放逻辑截胡。"""
        g0 = self.panel.geometry()
        cx = self.bar.width() // 2
        self.panel.eventFilter(self.bar, self._bar_event(
            QEvent.MouseButtonPress, cx, self.bar.height() // 2, 1000, 500))
        self.assertIsNone(self.panel._tb_resize)
        self.assertIsNotNone(self.panel._drag)
        self.panel.eventFilter(self.bar, self._bar_event(
            QEvent.MouseMove, cx, self.bar.height() // 2, 1025, 515))
        self.assertEqual(self.panel.geometry().topLeft(),
                         g0.topLeft() + QPoint(25, 15))
        self.panel.eventFilter(self.bar, self._bar_event(
            QEvent.MouseButtonRelease, cx, self.bar.height() // 2, 1025, 515,
            Qt.NoButton))
        self.assertIsNone(self.panel._drag)


if __name__ == '__main__':
    unittest.main()
