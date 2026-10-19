# -*- coding: utf-8 -*-
"""钉图点击工具条回归测试。"""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QInputMethodEvent, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import i18n
from pinshot import PinWindow


class _Cfg:
    def __init__(self):
        self.data = {'theme': 'nocturne'}
        self.saved = 0

    def save(self):
        self.saved += 1


class PinToolbarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def _pin(self, cfg=None):
        img = QImage(320, 200, QImage.Format_ARGB32)
        img.fill(QColor('#f5f0e6'))
        win = PinWindow(img, QPoint(120, 120), '#999999', cfg)
        win.show()
        self.qapp.processEvents()
        self.addCleanup(win.close)
        return win

    def test_click_shows_shared_toolbar_without_pin_and_long(self):
        win = self._pin()

        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        toolbar = getattr(win, '_toolbar', None)
        self.assertIsNotNone(toolbar)
        self.assertTrue(toolbar.isVisible())
        self.assertEqual(
            list(win._toolbar_btns),
            ['rect', 'ellipse', 'arrow', 'text', 'marker',
             'save', 'close', 'confirm'])
        self.assertGreater(
            toolbar.geometry().center().y(), win.geometry().center().y())

    def test_toolbar_spec_is_the_single_source_for_screenshot_actions(self):
        import screenshot

        self.assertEqual(
            list(screenshot.SHOT_TOOLBAR_KINDS),
            ['rect', 'ellipse', 'arrow', 'text', 'marker',
             'long', 'pin', 'save', 'close', 'confirm'])
        self.assertEqual(
            set(screenshot.PIN_TOOLBAR_EXCLUDED), {'pin', 'long'})

    def test_toolbar_copy_follows_current_language(self):
        import screenshot

        old_language = i18n.get_language()
        self.addCleanup(i18n.set_language, old_language)
        i18n.set_language(i18n.EN)
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        for group in screenshot.SHOT_TOOLBAR_GROUPS:
            for kind, tip_key in group:
                if kind in screenshot.PIN_TOOLBAR_EXCLUDED:
                    continue
                if kind == 'confirm':
                    self.assertEqual(win._toolbar_btns[kind].text(),
                                     i18n.t('shot.done'))
                else:
                    self.assertEqual(win._toolbar_btns[kind].toolTip(),
                                     i18n.t(tip_key))

    def test_pin_toolbar_automatically_includes_a_new_screenshot_action(self):
        import screenshot

        original = screenshot.SHOT_TOOLBAR_GROUPS
        screenshot.SHOT_TOOLBAR_GROUPS = original + ((('future', '未来动作'),),)
        self.addCleanup(setattr, screenshot, 'SHOT_TOOLBAR_GROUPS', original)

        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        self.assertIn('future', win._toolbar_btns)

    def test_toolbar_has_a_painted_tray_background(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        toolbar = win._toolbar
        image = toolbar.grab().toImage()
        self.assertGreater(
            image.pixelColor(2, toolbar.height() // 2).alpha(), 0)

    def test_click_outside_pin_and_toolbar_hides_toolbar(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()
        self.assertTrue(win._toolbar.isVisible())

        other = QWidget()
        other.setGeometry(600, 600, 100, 100)
        other.show()
        self.addCleanup(other.close)
        QTest.mouseClick(other, Qt.LeftButton, pos=other.rect().center())
        self.qapp.processEvents()

        self.assertFalse(win._toolbar.isVisible())

    def test_dragging_shows_toolbar(self):
        win = self._pin()

        QTest.mousePress(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()
        self.assertIsNotNone(win._toolbar)
        self.assertTrue(win._toolbar.isVisible())

        QTest.mouseRelease(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

    def test_annotation_mode_keeps_main_toolbar_position(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()
        toolbar_pos = win._toolbar.pos()

        win._toolbar_btns['rect'].click()
        self.qapp.processEvents()

        self.assertIsNotNone(win._editor)
        self.assertEqual(win._editor.bar.pos(), toolbar_pos)

    def test_annotation_subtoolbar_sits_below_main_toolbar(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['rect'].click()
        self.qapp.processEvents()

        self.assertTrue(win._editor.sub.isVisible())
        self.assertGreater(win._editor.sub.y(), win._editor.bar.geometry().bottom())

    def test_arrow_drag_creates_arrow_shape(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['arrow'].click()
        editor = win._editor
        QTest.mousePress(editor, Qt.LeftButton, pos=QPoint(40, 50))
        QTest.mouseMove(editor, QPoint(150, 110), 10)
        QTest.mouseRelease(editor, Qt.LeftButton, pos=QPoint(150, 110))
        self.qapp.processEvents()

        self.assertEqual(editor._shapes[-1]['kind'], 'arrow')
        self.assertEqual(editor._shapes[-1]['start'], QPoint(40, 50))
        self.assertEqual(editor._shapes[-1]['end'], QPoint(150, 110))
        shaft, head_len, head_half = editor._arrow_metrics(editor._shapes[-1])
        self.assertGreater(shaft, editor._shapes[-1]['w'])
        self.assertGreater(head_len, 18)
        self.assertGreaterEqual(head_half * 2, 24)

    def test_marker_tool_places_sequential_numbers(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['marker'].click()
        editor = win._editor
        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(50, 50))
        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(80, 80))
        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(110, 100))
        self.qapp.processEvents()

        markers = [sh for sh in editor._shapes if sh['kind'] == 'marker']
        self.assertEqual([sh['no'] for sh in markers], [1, 2])
        rendered = editor._result_image()
        first_rect = markers[0]['rect']
        self.assertAlmostEqual(first_rect.width(), first_rect.height())
        self.assertNotEqual(
            rendered.pixelColor(int(first_rect.left()), int(first_rect.center().y())).name(),
            '#000000')

    def test_marker_tool_opens_dark_text_box_and_exports_its_text(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['marker'].click()
        editor = win._editor
        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(50, 50))
        self.qapp.processEvents()

        self.assertIsNotNone(editor._marker_edit)
        text_edit = editor._marker_edit[0]
        self.assertEqual(text_edit.placeholderText(), '')
        text_edit.setPlainText('说明文字')
        editor._commit_marker_editor()
        self.qapp.processEvents()

        marker = [sh for sh in editor._shapes if sh['kind'] == 'marker'][0]
        self.assertEqual(marker['text'], '说明文字')
        self.assertIsNone(editor._marker_edit)
        self.assertIsNotNone(win._editor)
        rendered = editor._result_image()
        text_rect = marker['text_rect']
        self.assertLess(
            rendered.pixelColor(int(text_rect.left()), int(text_rect.center().y())).lightness(),
            60)

    def test_marker_editor_click_commits_without_adding_next_marker(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['marker'].click()
        editor = win._editor
        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(50, 50))
        self.qapp.processEvents()
        editor._marker_edit[0].setPlainText('第一条')

        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(210, 140))
        self.qapp.processEvents()
        markers = [sh for sh in editor._shapes if sh['kind'] == 'marker']
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]['text'], '第一条')

        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(240, 150))
        self.qapp.processEvents()
        markers = [sh for sh in editor._shapes if sh['kind'] == 'marker']
        self.assertEqual(len(markers), 2)

    def test_text_editor_click_commits_without_opening_next_editor(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['text'].click()
        editor = win._editor
        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(50, 50))
        editor._editor[0].setPlainText('第一段')

        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(210, 140))
        self.qapp.processEvents()
        texts = [sh for sh in editor._shapes if sh['kind'] == 'text']
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0]['text'], '第一段')
        self.assertIsNone(editor._editor)

        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(240, 150))
        self.qapp.processEvents()
        self.assertIsNotNone(editor._editor)

    def test_marker_number_is_fixed_and_slider_updates_text_live(self):
        win = self._pin(_Cfg())
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['marker'].click()
        editor = win._editor
        editor._size_slider.setValue(30)
        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(50, 50))
        self.qapp.processEvents()

        marker = [sh for sh in editor._shapes if sh['kind'] == 'marker'][0]
        self.assertEqual(marker['dot_size'], 24)
        self.assertEqual(marker['text_size'], 30)
        self.assertEqual(editor._marker_edit[0].font().pixelSize(), 30)

    def test_marker_label_background_grows_and_wraps_with_text(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['marker'].click()
        editor = win._editor
        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(40, 40))
        self.qapp.processEvents()
        marker = [sh for sh in editor._shapes if sh['kind'] == 'marker'][0]

        marker['text'] = '短'
        short = editor._marker_text_rect(marker)
        marker['text'] = '这是一段会换行的较长说明文字' * 5
        long = editor._marker_text_rect(marker)
        self.assertGreater(long.width(), short.width())
        self.assertGreater(long.height(), short.height())

    def test_marker_label_can_be_dragged_and_reopened_for_edit(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['marker'].click()
        editor = win._editor
        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(50, 50))
        self.qapp.processEvents()
        editor._marker_edit[0].setPlainText('可拖动说明')
        editor._commit_marker_editor()
        marker = [sh for sh in editor._shapes if sh['kind'] == 'marker'][0]
        old_pos = QPointF(marker['pos'])
        text_rect = editor._marker_text_rect(marker)
        start = text_rect.center().toPoint()

        QTest.mousePress(editor, Qt.LeftButton, pos=start)
        QTest.mouseMove(editor, start + QPoint(70, 40), 10)
        QTest.mouseRelease(editor, Qt.LeftButton, pos=start + QPoint(70, 40))
        self.qapp.processEvents()
        self.assertNotEqual(marker['pos'], old_pos)

        new_center = editor._marker_text_rect(marker).center().toPoint()
        QTest.mouseClick(editor, Qt.LeftButton, pos=new_center)
        self.qapp.processEvents()
        self.assertIsNotNone(editor._marker_edit)
        self.assertEqual(editor._marker_edit[0].toPlainText(), '可拖动说明')

    def test_marker_editor_preedit_expands_without_committing_text(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['marker'].click()
        editor = win._editor
        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(50, 50))
        self.qapp.processEvents()
        editor._marker_edit[0].setPlainText('已有文字')
        editor._commit_marker_editor()
        marker = [sh for sh in editor._shapes if sh['kind'] == 'marker'][0]

        QTest.mouseClick(editor, Qt.LeftButton,
                         pos=editor._marker_text_rect(marker).center().toPoint())
        self.qapp.processEvents()
        text_edit = editor._marker_edit[0]
        old_width = text_edit.width()
        QApplication.sendEvent(text_edit, QInputMethodEvent('wo', []))
        self.qapp.processEvents()

        self.assertGreater(text_edit.width(), old_width)
        self.assertEqual(text_edit.toPlainText(), '已有文字')
        self.assertEqual(marker['text'], '已有文字')

    def test_editing_marker_label_is_not_painted_under_editor(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['marker'].click()
        editor = win._editor
        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(50, 50))
        self.qapp.processEvents()
        editor._marker_edit[0].setPlainText('已有文字')
        editor._commit_marker_editor()
        marker = [sh for sh in editor._shapes if sh['kind'] == 'marker'][0]

        QTest.mouseClick(editor, Qt.LeftButton,
                         pos=editor._marker_text_rect(marker).center().toPoint())
        self.qapp.processEvents()
        image = QImage(editor.size(), QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        editor._draw_shape(painter, marker)
        painter.end()

        center = editor._marker_text_rect(marker).center().toPoint()
        self.assertEqual(image.pixelColor(center).alpha(), 0)

    def test_marker_text_wraps_at_boundary_without_covering_dot(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['marker'].click()
        editor = win._editor
        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(60, 80))
        self.qapp.processEvents()
        editor._marker_edit[0].setPlainText('一段需要自动换行的长说明文字')
        editor._commit_marker_editor()
        marker = [sh for sh in editor._shapes if sh['kind'] == 'marker'][0]

        start = editor._marker_badge_rect(marker).center().toPoint()
        target = QPoint(editor._sel.right() - 2, start.y())
        QTest.mousePress(editor, Qt.LeftButton, pos=start)
        QTest.mouseMove(editor, target, 10)
        QTest.mouseRelease(editor, Qt.LeftButton, pos=target)
        self.qapp.processEvents()

        badge = editor._marker_badge_rect(marker)
        text_rect = editor._marker_text_rect(marker)
        self.assertLessEqual(badge.right(), editor._sel.right())
        self.assertLess(badge.right(), text_rect.left())
        self.assertLessEqual(text_rect.right(), editor._sel.right())
        self.assertGreater(
            text_rect.height(),
            editor._marker_text_font(marker).pixelSize() + 8)

    def test_tool_slider_sizes_persist_for_reopened_editor(self):
        import screenshot

        cfg = _Cfg()
        first = screenshot.ShotOverlay(
            cfg, pin_image=QImage(320, 200, QImage.Format_ARGB32),
            pin_pos=QPoint(0, 0))
        values = {'rect': 8, 'ellipse': 3, 'arrow': 9, 'text': 27, 'marker': 31}
        for tool, value in values.items():
            first._set_tool(tool)
            first._size_slider.setValue(value)
        first._close()
        self.qapp.processEvents()

        second = screenshot.ShotOverlay(
            cfg, pin_image=QImage(320, 200, QImage.Format_ARGB32),
            pin_pos=QPoint(0, 0))
        for tool, value in values.items():
            second._set_tool(tool)
            self.assertEqual(second._size_slider.value(), value)
        second._close()
        self.qapp.processEvents()
        self.assertGreater(cfg.saved, 0)


if __name__ == '__main__':
    unittest.main()
