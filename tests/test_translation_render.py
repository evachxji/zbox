# -*- coding: utf-8 -*-
"""翻译渲染层测试：马赛克覆盖、译文绘制、原文/译文切换、dpr 尺寸。"""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

import translation_core as tc
import translation_render as tr


def _para(x, y, w, h, text):
    region = tc.OcrRegion(text, 0.99, None, (x, y, w, h))
    return tc.Paragraph((x, y, w, h), [region])


def _base(w=200, h=100, color=QColor(255, 255, 255)):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(color)
    # 画上「原文字」（黑色块模拟），让马赛克有东西可糊
    p = QPainter(img)
    p.fillRect(20, 20, 60, 12, QColor(0, 0, 0))
    p.fillRect(20, 40, 80, 12, QColor(0, 0, 0))
    p.end()
    return img


def _variance(img, rect):
    x, y, w, h = rect
    values = []
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            values.append(QColor(img.pixel(xx, yy)).red())
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / len(values)


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def test_original_mode_returns_base_unchanged(self):
        base = _base()
        out = tr.render(base, [_para(20, 20, 60, 12, 'hello')], ['你好'],
                        translated=False)
        self.assertEqual(out.pixel(25, 25), base.pixel(25, 25))

    def test_gaussian_blur_is_smooth_and_confined_to_line_rect(self):
        base = _base()
        out = tr.render(base, [_para(20, 20, 60, 12, 'hello')], ['你好'])
        # 锐利黑白交界被平滑，但不能退回 8px 方块马赛克（相邻像素不再等色）
        self.assertLess(_variance(out, (17, 21, 10, 10)), _variance(base, (17, 21, 10, 10)))
        self.assertNotEqual(out.pixel(18, 34), out.pixel(19, 34))
        # 行框外扩 3px 以外必须保持原图，不做全屏或整段模糊
        self.assertEqual(out.pixel(16, 34), base.pixel(16, 34))
        self.assertEqual(out.pixel(84, 34), base.pixel(84, 34))

    def test_gaussian_blur_obscures_original_strokes(self):
        base = _base()
        blurred = tr._gaussian_blur(base, (17, 17, 66, 18), 1.0)
        # 不能只做视觉上几乎无感的轻模糊；黑白原文区域应明显失去锐利对比
        self.assertLess(_variance(blurred, (0, 0, 66, 18)), 4000)

    def test_translated_text_drawn_over(self):
        base = _base()
        paras = [_para(20, 20, 60, 12, 'hello')]
        out = tr.render(base, paras, ['你好世界'])
        # 区域内应有非马赛克背景色的文字像素（深色字）
        region_colors = set()
        for yy in range(18, 40):
            for xx in range(18, 82):
                region_colors.add(out.pixel(xx, yy))
        base_colors = set()
        for yy in range(18, 40):
            for xx in range(18, 82):
                base_colors.add(base.pixel(xx, yy))
        self.assertTrue(region_colors - base_colors)

    def test_translation_does_not_spill_below_source_line(self):
        base = QImage(200, 100, QImage.Format_ARGB32)
        base.fill(QColor(255, 255, 255))
        para = _para(20, 20, 60, 12, 'hi')
        out = tr.render(base, [para], ['这是一段很长很长的译文不能溢出行框'])
        # 原行框（含 3px 模糊外扩）以下不许出现译文字迹，否则会盖住下一行原文
        for yy in range(36, 60):
            for xx in range(20, 80):
                self.assertEqual(out.pixel(xx, yy), base.pixel(xx, yy))

    def test_layer_respects_dpr(self):
        base = _base()
        layer = tr.build_layer(base, [_para(20, 20, 60, 12, 'hello')], ['你好'],
                               dpr=2.0)
        self.assertEqual(layer.width(), 400)
        self.assertEqual(layer.devicePixelRatio(), 2.0)

    def test_long_translation_still_rendered(self):
        base = _base()
        paras = [_para(20, 20, 60, 12, 'hi')]
        out = tr.render(base, paras, ['这是一段远远超出原文长度的翻译结果需要缩字号或换行'])
        self.assertIsInstance(out, QImage)


if __name__ == '__main__':
    unittest.main()