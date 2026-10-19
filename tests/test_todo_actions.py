# -*- coding: utf-8 -*-
"""待办编辑、复制、删除撤销与空白双击的界面回归测试。"""
import os
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QAbstractAnimation, QDate, QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCalendarWidget, QLabel, QMenu, QToolButton

import app
from themes import build_qss


class TodoActionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = app.TodoStore(os.path.join(self.tmp.name, 'todos.json'))

    def tearDown(self):
        self.tmp.cleanup()

    def _widget(self):
        widget = app.TodoWidget(self.store)
        widget.resize(app.sc(344), app.sc(370))
        widget.show()
        self.qapp.processEvents()
        self.addCleanup(widget.close)
        return widget

    def test_editor_grows_and_shift_enter_inserts_newline(self):
        widget = self._widget()
        widget.start_add()
        editor = widget._editor[1]
        self.assertEqual(editor.placeholderText(), '')
        QTest.keyClicks(editor, 'first')
        QTest.keyClick(editor, Qt.Key_Return, Qt.ShiftModifier)
        QTest.keyClicks(editor, 'second')
        self.assertEqual(editor.toPlainText(), 'first\nsecond')
        self.assertEqual(editor.verticalScrollBar().maximum(), 0)

        QTest.keyClick(editor, Qt.Key_Return)
        self.qapp.processEvents()
        self.assertEqual(self.store.items[0]['text'], 'first\nsecond')

    def test_editor_grows_beyond_old_height_cap_without_inner_scrolling(self):
        widget = self._widget()
        widget.start_add()
        editor = widget._editor[1]
        editor.setPlainText('\n'.join(['x' * 80] * 8))
        self.qapp.processEvents()

        self.assertGreater(editor.height(), app.sc(126))
        self.assertEqual(editor.verticalScrollBar().maximum(), 0)

    def test_two_line_editor_has_no_inner_scroll_with_theme_padding(self):
        old_qss = self.qapp.styleSheet()
        self.addCleanup(self.qapp.setStyleSheet, old_qss)
        self.qapp.setStyleSheet(build_qss('nocturne', 'Microsoft YaHei UI', 'Segoe UI'))
        widget = self._widget()
        widget.start_add()
        editor = widget._editor[1]
        editor.setPlainText('first line\nsecond line')
        self.qapp.processEvents()

        self.assertEqual(editor.verticalScrollBar().maximum(), 0)

    def test_editor_save_button_sits_after_calendar_and_commits(self):
        self.store.add('before')
        widget = self._widget()
        item_id = self.store.items[0]['id']
        widget._edit_item(item_id)
        self.qapp.processEvents()

        date_btn = widget.findChild(QToolButton, 'todoDateBtn')
        save_btn = widget.findChild(QToolButton, 'todoSaveBtn')
        self.assertIsNotNone(date_btn)
        self.assertIsNotNone(save_btn)
        self.assertEqual(save_btn.text(), '✓')
        self.assertGreater(save_btn.mapTo(widget, QPoint(0, 0)).x(),
                           date_btn.mapTo(widget, QPoint(0, 0)).x())

        widget._editor[1].setPlainText('after')
        save_btn.click()
        self.qapp.processEvents()
        self.assertEqual(self.store.items[0]['text'], 'after')

    def test_due_popup_commits_only_with_clear_or_confirm(self):
        widget = self._widget()
        picked = []
        popup = app.DuePopup(widget, '2026-10-16', picked.append, lambda: None)
        popup.show()
        self.qapp.processEvents()

        buttons = [b for b in popup.findChildren(QToolButton) if b.parent() is popup]
        self.assertEqual([b.text() for b in buttons], ['清除', '确定'])
        cal = popup.findChild(QCalendarWidget)
        cal.setSelectedDate(QDate(2026, 11, 3))
        cal.clicked.emit(QDate(2026, 11, 3))
        self.assertEqual(picked, [])

        next(b for b in buttons if b.text() == '确定').click()
        self.qapp.processEvents()
        self.assertEqual(picked, [QDate(2026, 11, 3).toPython()])

        cleared = []
        clear_popup = app.DuePopup(widget, None, cleared.append, lambda: None)
        clear_popup.show()
        self.qapp.processEvents()
        clear_button = next(b for b in clear_popup.findChildren(QToolButton)
                            if b.parent() is clear_popup and b.text() == '清除')
        clear_button.click()
        self.qapp.processEvents()
        self.assertEqual(cleared, [None])

    def test_blank_double_click_appends_editor_then_saves_without_scrolling(self):
        for i in range(14):
            self.store.add('item %02d' % i)
        widget = self._widget()
        widget.list.scrollToBottom()
        self.qapp.processEvents()

        viewport = widget.list.viewport()
        QTest.mouseDClick(viewport, Qt.LeftButton,
                          pos=QPoint(viewport.width() // 2, viewport.height() - 3))
        self.qapp.processEvents()

        self.assertTrue(widget._editing)
        editor_item = widget._editor[0]
        self.assertIs(editor_item, widget.list.item(widget.list.count() - 1))
        self.assertTrue(widget.list.visualItemRect(editor_item).intersects(viewport.rect()))

        widget._editor[1].setPlainText('new item')
        before_save = widget.list.verticalScrollBar().value()
        QTest.keyClick(widget._editor[1], Qt.Key_Return)
        self.qapp.processEvents()
        self.assertEqual(self.store.items[0]['text'], 'new item')
        self.assertEqual(widget.list.verticalScrollBar().value(), before_save)

    def test_store_sorts_due_dates_then_undated_and_completed_last(self):
        self.store.add('late', '2026-11-03')
        self.store.add('undated old')
        self.store.add('early', '2026-10-20')
        self.store.add('undated new')
        self.store.add('same date', '2026-10-20')
        self.assertEqual(
            [i['text'] for i in self.store.items],
            ['same date', 'early', 'late', 'undated new', 'undated old'])

        early_id = next(i['id'] for i in self.store.items if i['text'] == 'early')
        self.store.toggle(early_id, True)
        self.assertEqual(
            [i['text'] for i in self.store.items],
            ['same date', 'late', 'undated new', 'undated old', 'early'])

    def test_new_dated_item_is_inserted_by_due_date(self):
        self.store.add('early', '2026-10-20')
        self.store.add('late', '2026-11-01')
        widget = self._widget()
        widget.start_add()
        widget._edit_due = '2026-10-25'
        widget._editor[1].setPlainText('middle')
        QTest.keyClick(widget._editor[1], Qt.Key_Return)
        self.qapp.processEvents()

        self.assertEqual(
            [i['text'] for i in self.store.items],
            ['early', 'middle', 'late'])
        ids = [widget.list.item(i).data(Qt.UserRole) for i in range(widget.list.count())]
        self.assertEqual(ids, [i['id'] for i in self.store.items])

    def test_edit_and_toggle_keep_scroll_position(self):
        for i in range(24):
            self.store.add('item %02d' % i)
        widget = self._widget()
        bar = widget.list.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        self.qapp.processEvents()

        viewport = widget.list.viewport()
        item = widget.list.itemAt(QPoint(viewport.width() // 2, viewport.height() // 2))
        self.assertIsNotNone(item)
        item_id = item.data(Qt.UserRole)
        widget._edit_item(item_id)
        self.qapp.processEvents()
        before_commit = bar.value()
        widget._editor[1].setPlainText('edited')
        QTest.keyClick(widget._editor[1], Qt.Key_Return)
        self.qapp.processEvents()
        self.assertEqual(bar.value(), before_commit)

        item = widget.list.itemAt(QPoint(viewport.width() // 2, viewport.height() // 2))
        self.assertIsNotNone(item)
        before_toggle = bar.value()
        widget.list.itemWidget(item).findChild(QToolButton, 'todoCheck').click()
        self.qapp.processEvents()
        self.assertEqual(bar.value(), before_toggle)

    def test_copy_and_delete_actions_with_undo(self):
        self.store.add('keep me\nline two')
        widget = self._widget()
        pos = widget.list.visualItemRect(widget.list.item(0)).center()

        def click_copy():
            menu = QApplication.activePopupWidget()
            self.assertIsInstance(menu, QMenu)
            self.assertEqual([a.text() for a in menu.actions()], ['编辑', '复制', '删除'])
            danger = menu.findChild(QLabel, 'todoDeleteActionText')
            self.assertIsNotNone(danger)
            QTest.mouseClick(menu, Qt.LeftButton,
                             pos=menu.actionGeometry(menu.actions()[1]).center())

        QTimer.singleShot(0, click_copy)
        widget._menu(pos)
        self.assertEqual(QApplication.clipboard().text(), 'keep me\nline two')

        def click_delete():
            menu = QApplication.activePopupWidget()
            act_del = menu.actions()[2]
            danger = menu.findChild(QLabel, 'todoDeleteActionText').parentWidget()
            center = danger.rect().center()
            QApplication.sendEvent(
                danger, QEnterEvent(QPointF(center), QPointF(center), QPointF(center)))
            self.assertIs(menu.activeAction(), act_del)
            QTest.mouseClick(danger, Qt.LeftButton, pos=center)

        QTimer.singleShot(0, click_delete)
        widget._menu(pos)
        self.qapp.processEvents()
        self.assertEqual(self.store.items, [])
        toast = widget._undo_toasts[0]
        self.assertTrue(toast.isVisible())
        self.assertTrue(toast._timer.isActive())
        self.assertEqual(toast._timer.interval(), 5000)
        self.assertEqual(len(toast._show_anims), 2)
        self.assertEqual(toast._countdown_anim.state(),
                         QAbstractAnimation.State.Running)

        toast.undo_btn.click()
        self.qapp.processEvents()
        self.assertEqual(self.store.items[0]['text'], 'keep me\nline two')
        self.assertEqual(widget._undo_toasts, [])

    def test_multiple_deletes_stack_toasts_and_undo_independently(self):
        self.store.add('older')
        self.store.add('newer')
        widget = self._widget()
        older_id = next(i['id'] for i in self.store.items if i['text'] == 'older')
        newer_id = next(i['id'] for i in self.store.items if i['text'] == 'newer')

        widget._delete_item(older_id)
        self.qapp.processEvents()
        widget._delete_item(newer_id)
        self.qapp.processEvents()
        QTest.qWait(420)
        self.assertEqual(len(widget._undo_toasts), 2)
        newer_toast, older_toast = widget._undo_toasts
        self.assertGreater(newer_toast.y(), older_toast.y())
        self.assertTrue(newer_toast.isVisible())
        self.assertTrue(older_toast.isVisible())

        newer_toast.undo_btn.click()
        self.qapp.processEvents()
        self.assertEqual(len(widget._undo_toasts), 1)
        self.assertEqual([i['text'] for i in self.store.items], ['newer'])


if __name__ == '__main__':
    unittest.main()
