# -*- coding: utf-8 -*-
"""桌面格子顶部操作图标悬停显隐回归测试。"""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QCursor, QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect

from boxes import BoxWindow


class _BoxManagerStub:
    def save_rec(self, _win):
        pass

    def remove(self, _win):
        pass

    def ungroup_paths(self, _paths):
        pass


class BoxTitleActionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        rec = {
            'id': 'title-actions-test', 'kind': 'blank', 'path': '',
            'name': '示例格子', 'x': 0, 'y': 0, 'w': 320, 'h': 240,
            'collapsed': False, 'locked': False, 'sort': 'name', 'view': 'list',
        }
        self.box = BoxWindow(_BoxManagerStub(), rec)
        self.box.move(200, 200)
        self.box.show()
        self.qapp.processEvents()
        self.addCleanup(self.box.deleteLater)

    def test_actions_start_hidden_and_keep_layout_width(self):
        effect = self.box.title_actions.graphicsEffect()
        before = self.box.btn_menu.mapTo(self.box, QPoint(0, 0))

        self.assertIsInstance(effect, QGraphicsOpacityEffect)
        self.assertEqual(effect.opacity(), 0.0)
        self.assertTrue(self.box.title_actions.testAttribute(
            Qt.WA_TransparentForMouseEvents))

        self.box._show_title_actions()
        QTest.qWait(170)

        self.assertAlmostEqual(effect.opacity(), 1.0)
        self.assertEqual(self.box.btn_menu.mapTo(self.box, QPoint(0, 0)), before)

    def test_title_enter_fades_in_and_leave_fades_out(self):
        self.box._show_title_actions()
        QTest.qWait(170)
        self.assertAlmostEqual(
            self.box.title_actions.graphicsEffect().opacity(), 1.0)

        center = self.box.title.rect().center()
        QApplication.sendEvent(
            self.box.title,
            QEnterEvent(QPointF(center), QPointF(center), QPointF(center)))
        self.assertEqual(self.box._title_actions_target, 1.0)

        QCursor.setPos(self.box.mapToGlobal(QPoint(-10, -10)))
        QApplication.sendEvent(self.box.title, QEvent(QEvent.Leave))
        self.box._title_actions_tick()
        QTest.qWait(210)

        self.assertEqual(
            self.box.title_actions.graphicsEffect().opacity(), 0.0)
        self.assertTrue(self.box.title_actions.testAttribute(
            Qt.WA_TransparentForMouseEvents))

    def test_open_menu_holds_actions_visible(self):
        seen = []

        class _MenuStub:
            def exec(self, _pos):
                seen.append(box._title_actions_hold)

        box = self.box
        box._build_menu = lambda: _MenuStub()

        box._show_menu()

        self.assertEqual(seen, [True])
        self.assertFalse(box._title_actions_hold)


if __name__ == '__main__':
    unittest.main()
