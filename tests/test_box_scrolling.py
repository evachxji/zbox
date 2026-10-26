# -*- coding: utf-8 -*-
"""桌面格子滚动条悬停显隐与 Shift 横向滚动回归测试。"""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QEnterEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidgetItem

from boxes import BoxWindow


class _BoxManagerStub:
    def save_rec(self, _win):
        pass


class BoxScrollingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        rec = {
            'id': 'scrolling-test', 'kind': 'blank', 'path': '',
            'name': '示例格子', 'x': 0, 'y': 0, 'w': 320, 'h': 240,
            'collapsed': False, 'locked': False, 'sort': 'name', 'view': 'list',
        }
        self.box = BoxWindow(_BoxManagerStub(), rec)
        self.box.show()
        self.qapp.processEvents()
        self.addCleanup(self.box.deleteLater)

    def _wheel(self, modifiers=Qt.NoModifier):
        pos = QPointF(self.box.list.viewport().rect().center())
        event = QWheelEvent(pos, QPointF(self.box.list.viewport().mapToGlobal(pos.toPoint())),
                            QPoint(0, 0), QPoint(0, -120),
                            Qt.NoButton, modifiers, Qt.NoScrollPhase, False)
        QApplication.sendEvent(self.box.list.viewport(), event)
        QTest.qWait(250)

    def test_scrollbars_follow_box_hover(self):
        QApplication.sendEvent(self.box, QEvent(QEvent.Leave))
        for policy in (self.box.list.horizontalScrollBarPolicy(),
                       self.box.list.verticalScrollBarPolicy()):
            self.assertEqual(policy,
                             Qt.ScrollBarAlwaysOff)

        center = QPointF(self.box.rect().center())
        QApplication.sendEvent(
            self.box, QEnterEvent(center, center, QPointF(self.box.mapToGlobal(center.toPoint()))))
        for policy in (self.box.list.horizontalScrollBarPolicy(),
                       self.box.list.verticalScrollBarPolicy()):
            self.assertEqual(policy,
                             Qt.ScrollBarAsNeeded)

        QApplication.sendEvent(self.box, QEvent(QEvent.Leave))
        for policy in (self.box.list.horizontalScrollBarPolicy(),
                       self.box.list.verticalScrollBarPolicy()):
            self.assertEqual(policy,
                             Qt.ScrollBarAlwaysOff)

    def test_shift_wheel_scrolls_horizontal_when_available(self):
        horizontal = self.box.list.horizontalScrollBar()
        vertical = self.box.list.verticalScrollBar()
        for i in range(30):
            QListWidgetItem('x' * 120 + str(i), self.box.list)
        self.qapp.processEvents()
        vertical.setValue(100)

        self._wheel(Qt.ShiftModifier)

        self.assertGreater(horizontal.value(), 0)
        self.assertEqual(vertical.value(), 100)

    def test_shift_wheel_falls_back_to_vertical_without_horizontal_overflow(self):
        horizontal = self.box.list.horizontalScrollBar()
        vertical = self.box.list.verticalScrollBar()
        for i in range(30):
            QListWidgetItem('file-%02d' % i, self.box.list)
        self.qapp.processEvents()

        self._wheel(Qt.ShiftModifier)

        self.assertEqual(horizontal.value(), 0)
        self.assertGreater(vertical.value(), 0)


if __name__ == '__main__':
    unittest.main()
