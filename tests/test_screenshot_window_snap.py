# -*- coding: utf-8 -*-
"""截图窗口悬浮与短点击套选回归测试。"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import screenshot


class _Cfg:
    def __init__(self):
        self.data = {'theme': 'nocturne'}

    def save(self):
        pass


class ScreenshotWindowSnapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def _overlay(self):
        win = screenshot.ShotOverlay(_Cfg())
        win.setGeometry(0, 0, 800, 600)
        win._tl = QPoint(0, 0)
        win.show()
        self.qapp.processEvents()
        self.addCleanup(win._close)
        return win

    def test_hover_shows_and_clears_window_frame(self):
        win = self._overlay()
        frame = QRect(100, 80, 320, 240)
        with patch.object(screenshot, '_window_frame_at',
                          return_value=(123, frame)):
            win._refresh_window_hover(QPoint(140, 120))
        self.assertEqual(win._hover_frame, frame)

        with patch.object(screenshot, '_window_frame_at', return_value=None):
            win._refresh_window_hover(QPoint(500, 500))
        self.assertIsNone(win._hover_frame)

    def test_short_click_selects_whole_window(self):
        win = self._overlay()
        frame = QRect(100, 80, 320, 240)
        with patch.object(screenshot, '_window_frame_at',
                          return_value=(123, frame)):
            QTest.mouseClick(win, Qt.LeftButton, pos=QPoint(140, 120))
            self.qapp.processEvents()
        self.assertEqual(win._mode, 'ready')
        self.assertEqual(win._sel, frame)

    def test_dragging_still_creates_manual_selection(self):
        win = self._overlay()
        frame = QRect(100, 80, 320, 240)
        with patch.object(screenshot, '_window_frame_at',
                          return_value=(123, frame)):
            QTest.mousePress(win, Qt.LeftButton, pos=QPoint(140, 120))
            QTest.mouseMove(win, QPoint(300, 260))
            QTest.mouseRelease(win, Qt.LeftButton, pos=QPoint(300, 260))
            self.qapp.processEvents()
        self.assertEqual(win._mode, 'ready')
        self.assertNotEqual(win._sel, frame)
        self.assertGreater(win._sel.width(), screenshot.MIN_SEL)

    def test_short_click_without_window_stays_idle(self):
        win = self._overlay()
        with patch.object(screenshot, '_window_frame_at', return_value=None):
            QTest.mouseClick(win, Qt.LeftButton, pos=QPoint(140, 120))
            self.qapp.processEvents()
        self.assertEqual(win._mode, 'idle')
        self.assertFalse(win._sel.isValid())

    def test_double_click_on_window_finishes_copy(self):
        win = self._overlay()
        frame = QRect(100, 80, 320, 240)
        with patch.object(screenshot, '_window_frame_at',
                          return_value=(123, frame)), \
                patch.object(win, '_finish_copy') as finish:
            QTest.mouseDClick(win, Qt.LeftButton, pos=QPoint(140, 120))
            self.qapp.processEvents()
        finish.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
