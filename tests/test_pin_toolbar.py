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
            ['rect', 'ellipse', 'arrow', 'pen', 'text', 'mosaic', 'marker',
             'translate', 'save', 'close', 'confirm'])
        self.assertGreater(
            toolbar.geometry().center().y(), win.geometry().center().y())

    def test_toolbar_spec_is_the_single_source_for_screenshot_actions(self):
        import screenshot

        self.assertEqual(
            list(screenshot.SHOT_TOOLBAR_KINDS),
            ['rect', 'ellipse', 'arrow', 'pen', 'text', 'mosaic', 'marker',
             'undo', 'translate', 'long', 'pin', 'save', 'close', 'confirm'])
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
                if kind not in win._toolbar_btns:   # 钉图工具条排除的按钮（pin/long/undo）
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

    def test_pen_drag_creates_polyline_shape(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        import screenshot
        win._toolbar_btns['pen'].click()
        editor = win._editor
        self.assertEqual(   # 画笔走线宽量程
            (editor._size_slider.minimum(), editor._size_slider.maximum()),
            screenshot.STROKE_RANGE)
        QTest.mousePress(editor, Qt.LeftButton, pos=QPoint(40, 50))
        for pt in (QPoint(80, 60), QPoint(120, 90), QPoint(150, 110)):
            QTest.mouseMove(editor, pt, 10)
        QTest.mouseRelease(editor, Qt.LeftButton, pos=QPoint(150, 110))
        self.qapp.processEvents()

        pen = editor._shapes[-1]
        self.assertEqual(pen['kind'], 'pen')
        self.assertGreaterEqual(len(pen['points']), 3)
        self.assertEqual(pen['points'][0], QPointF(40, 50))
        self.assertEqual(pen['points'][-1], QPointF(150, 110))
        rendered = editor._result_image()   # 默认红色画笔画在米色底图上
        c = rendered.pixelColor(40, 50)
        self.assertGreater(c.red(), 200)
        self.assertLess(c.green(), 120)

    def test_pen_click_without_drag_leaves_no_shape(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['pen'].click()
        editor = win._editor
        QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(60, 60))
        self.qapp.processEvents()
        self.assertEqual(editor._shapes, [])

    def test_mosaic_brush_pixelates_painted_stripes(self):
        img = QImage(320, 200, QImage.Format_ARGB32)   # 竖条斑马纹：原生逐像素明暗交替
        for x in range(img.width()):
            for y in range(img.height()):
                img.setPixelColor(x, y, QColor('#ffffff') if x % 2 == 0 else QColor('#000000'))
        win = PinWindow(img, QPoint(120, 120), '#999999', _Cfg())
        win.show()
        self.qapp.processEvents()
        self.addCleanup(win.close)
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        import screenshot
        win._toolbar_btns['mosaic'].click()
        editor = win._editor
        self.assertEqual(   # 马赛克走笔刷直径量程
            (editor._size_slider.minimum(), editor._size_slider.maximum()),
            screenshot.MOSAIC_RANGE)
        self.assertTrue(editor._dots[0][1].isHidden())        # 马赛克无颜色语义
        editor._size_slider.setValue(20)
        QTest.mousePress(editor, Qt.LeftButton, pos=QPoint(40, 40))
        QTest.mouseMove(editor, QPoint(160, 100), 10)
        QTest.mouseRelease(editor, Qt.LeftButton, pos=QPoint(160, 100))
        self.qapp.processEvents()

        sh = editor._shapes[-1]
        self.assertEqual(sh['kind'], 'mosaic')
        self.assertEqual(sh['size'], 20)
        self.assertEqual(sh['points'][0], QPointF(40, 40))    # 笔刷记折线，不是矩形
        mos = editor._mosaic_image(sh, 1.0)
        self.assertIsNotNone(mos)
        out, tl = mos
        self.assertEqual(tl, QPoint(30, 30))   # 包围盒 = 路径外扩笔刷半径 10
        # 涂抹路径上的点：同一块内相邻像素已被抹平（原生斑马纹相邻列必然不同）
        self.assertEqual(out.pixelColor(5, 5), out.pixelColor(6, 5))
        # 打码结果与原生底图不同（条纹被平均成灰）
        self.assertNotEqual(out.pixelColor(5, 5).name(), img.pixelColor(35, 35).name())
        # 蒙版之外保持透明：远离路径的角落没有打码内容
        self.assertEqual(out.pixelColor(out.width() - 2, 2).alpha(), 0)
        # 缓存：路径不变时重算返回同一对象
        self.assertIs(editor._mosaic_image(sh, 1.0)[0], out)

    def test_undo_button_pops_last_shape(self):
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['rect'].click()
        editor = win._editor
        self.assertIn('undo', editor._toolbar_btns)     # 编辑窗工具条有撤销
        self.assertNotIn('undo', win._toolbar_btns)     # 钉图窗没有可撤销的标注，不出现
        for x in (20, 100):
            QTest.mousePress(editor, Qt.LeftButton, pos=QPoint(x, 40))
            QTest.mouseMove(editor, QPoint(x + 40, 80), 10)
            QTest.mouseRelease(editor, Qt.LeftButton, pos=QPoint(x + 40, 80))
            self.qapp.processEvents()
        self.assertEqual(len(editor._shapes), 2)
        editor._toolbar_btns['undo'].click()            # 等同 Ctrl+Z
        self.assertEqual(len(editor._shapes), 1)
        editor._toolbar_btns['undo'].click()
        self.assertEqual(editor._shapes, [])
        editor._toolbar_btns['undo'].click()            # 空栈再点 = no-op
        self.assertEqual(editor._shapes, [])

    def test_mosaic_cursor_is_circle_sized_to_brush(self):
        import screenshot
        win = self._pin()
        QTest.mouseClick(win, Qt.LeftButton, pos=win.rect().center())
        self.qapp.processEvents()

        win._toolbar_btns['mosaic'].click()
        editor = win._editor
        editor._size_slider.setValue(20)
        cur = editor._brush_cursor()
        pm = cur.pixmap()
        self.assertEqual(pm.width(), pm.height())
        self.assertGreaterEqual(pm.width(), 20)   # 直径随笔刷大小走
        center = pm.toImage().pixelColor(pm.width() // 2, pm.height() // 2)
        self.assertGreater(center.alpha(), 150)   # 灰色实心圆
        self.assertAlmostEqual(center.red(), center.green(), delta=2)
        self.assertAlmostEqual(center.green(), center.blue(), delta=2)
        edge = pm.toImage().pixelColor(pm.width() // 2, 2)
        self.assertEqual(edge.red(), 0)           # 外圈黑色轮廓
        editor._update_cursor(editor.mapToGlobal(QPoint(100, 100)))
        self.assertEqual(editor.cursor().shape(), Qt.BitmapCursor)  # 自定义圆形光标
        editor._set_tool('pen')
        editor._update_cursor(editor.mapToGlobal(QPoint(100, 100)))
        self.assertEqual(editor.cursor().shape(), Qt.CrossCursor)  # 切走恢复十字


class PinTranslateBusyTest(unittest.TestCase):
    """钉图窗翻译态：高斯模糊 + loading，完成后压平译文并可切换原文/译文。"""

    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def _pin(self):
        img = QImage(320, 200, QImage.Format_ARGB32)
        img.fill(QColor('#f5f0e6'))
        win = PinWindow(img, QPoint(120, 120), '#999999', _Cfg())
        win.show()
        self.qapp.processEvents()
        self.addCleanup(win.close)
        return win

    def test_busy_paints_scan_line_and_status_pill(self):
        """A 方案：顶部扫描线 + 底部状态胶囊，图片中心保持原样。"""
        win = self._pin()
        before = win.grab().toImage()
        win.set_translate_busy(True)
        self.qapp.processEvents()
        self.assertTrue(win._tl8n_busy)
        self.assertTrue(win._mq_timer.isActive())
        after = win.grab().toImage()
        self.assertNotEqual(before.constBits().tobytes(),
                            after.constBits().tobytes())
        c = win.rect().center()
        self.assertEqual(before.pixelColor(c), after.pixelColor(c))
        # 顶部有蓝色扫描线。
        self.assertTrue(any(
            after.pixelColor(x, 2).blue() > after.pixelColor(x, 2).red() + 20
            for x in range(2, win.width() - 2)), '顶部应有扫描亮线')
        # 底部图片内部出现状态胶囊；旧边框跑马灯不会覆盖这一区域。
        x, y = win.width() // 2, win.height() - 28
        self.assertNotEqual(before.pixelColor(x, y), after.pixelColor(x, y))

    def test_busy_stop_without_result_keeps_original(self):
        win = self._pin()
        original = win._img.constBits().tobytes()
        win.set_translate_busy(True)
        win.set_translate_busy(False)
        self.qapp.processEvents()
        self.assertFalse(win._tl8n_busy)
        self.assertFalse(win._mq_timer.isActive())
        self.assertEqual(win._img.constBits().tobytes(), original)
        self.assertIsNone(win._tl8n_pair)

    def test_finish_translate_flattens_layer_and_enables_toggle(self):
        win = self._pin()
        original = win._img.constBits().tobytes()
        layer = QImage(win._img.size(), QImage.Format_ARGB32)
        layer.fill(QColor('#ff0000'))
        win.set_translate_busy(True)
        win.finish_translate(layer)
        self.qapp.processEvents()
        self.assertFalse(win._tl8n_busy)
        self.assertNotEqual(win._img.constBits().tobytes(), original)
        self.assertIsNotNone(win._tl8n_pair)
        # 工具条翻译键 = 切换原文/译文
        win._translate_clicked()
        self.assertEqual(win._img.constBits().tobytes(), original)
        win._translate_clicked()
        self.assertNotEqual(win._img.constBits().tobytes(), original)

    def test_pinned_translate_shows_busy_on_pin(self):
        """已钉住的截图点翻译：loading 做在钉图窗上，编辑窗退到幕后。"""
        import translation_core as tc
        from screenshot import ShotOverlay
        from unittest.mock import patch

        class _FakeTr:
            def __init__(self):
                self.on_login_required = None
            def translate(self, texts, target, on_done, on_error, preloaded=False):
                on_done(['译文'])
            def cancel(self):
                pass

        regions = [tc.OcrRegion('hello', 0.99, None, (20, 20, 60, 12))]
        page = type('FakePage', (), {'close': lambda self: None})
        win = self._pin()
        with patch('ocr_runtime.supported', return_value=True), \
             patch('doubao_web.supported', return_value=True), \
             patch('ocr_runtime.ocr_ready', return_value=True), \
             patch.object(ShotOverlay, '_run_ocr_job', lambda self, job: job()), \
             patch.object(ShotOverlay, '_run_warm_job', lambda self, job: job()), \
             patch.object(ShotOverlay, '_ocr_recognize',
                          lambda self, png, cancel: list(regions)), \
             patch.object(ShotOverlay, '_make_page', lambda self: page()), \
             patch.object(ShotOverlay, '_prepare_page',
                          lambda self, page, cb: cb(True)), \
             patch.object(ShotOverlay, '_make_translator', lambda self: _FakeTr()):
            win._translate_clicked()
            editor = win._editor
            self.assertIsNotNone(editor)
            self.assertTrue(win._tl8n_busy)          # 钉图窗进 loading
            self.assertTrue(win.isVisible())       # 钉图窗露出来做 loading
            self.assertFalse(editor.isVisible())     # 编辑窗退到幕后
            # 等图层构建完：译文压进钉图窗，编辑窗销毁
            import time
            t0 = time.time()
            while time.time() - t0 < 10 and (
                    win._tl8n_pair is None or win._editor is not None):
                self.qapp.processEvents()   # deleteLater 也要事件循环才销毁
                time.sleep(0.01)
            self.assertIsNotNone(win._tl8n_pair)
            self.assertFalse(win._tl8n_busy)
            self.assertIsNone(win._editor)

    def _translated_pin_showing_original(self):
        win = self._pin()
        layer = QImage(win._img.size(), QImage.Format_ARGB32)
        layer.fill(QColor('#ff0000'))
        win.finish_translate(layer)
        win._translate_clicked()   # 切回原文预览；输出仍应选译文
        return win

    def test_confirm_copies_translation_even_when_original_previewed(self):
        win = self._translated_pin_showing_original()
        translated = win._tl8n_pair[1]
        win._copy_image()
        copied = QApplication.clipboard().image()
        self.assertEqual(copied.constBits().tobytes(), translated.constBits().tobytes())

    def test_save_writes_translation_even_when_original_previewed(self):
        import tempfile
        from unittest.mock import patch
        win = self._translated_pin_showing_original()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'translated.png')
            with patch('pinshot.QFileDialog.getSaveFileName', return_value=(path, 'PNG')):
                win._save_image()
            saved = QImage(path)
        self.assertEqual(saved.constBits().tobytes(),
                         win._tl8n_pair[1].constBits().tobytes())

    def test_double_click_copies_translation_and_closes(self):
        win = self._translated_pin_showing_original()
        translated = win._tl8n_pair[1]
        QTest.mouseDClick(win, Qt.LeftButton, pos=win.rect().center())
        copied = QApplication.clipboard().image()
        self.assertEqual(copied.constBits().tobytes(), translated.constBits().tobytes())
        self.assertFalse(win.isVisible())

    def test_edit_image_clears_translation_pair(self):
        win = self._pin()
        layer = QImage(win._img.size(), QImage.Format_ARGB32)
        layer.fill(QColor('#ff0000'))
        win.finish_translate(layer)
        self.assertIsNotNone(win._tl8n_pair)
        win._apply_edited_image(QImage(100, 80, QImage.Format_ARGB32))
        self.assertIsNone(win._tl8n_pair)


if __name__ == '__main__':
    unittest.main()
