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

    def test_mosaic_blurs_original_text(self):
        base = _base()
        out = tr.render(base, [_para(20, 20, 60, 12, 'hello')], ['你好'])
        # 原文字是锐利的黑白交界，马赛克后块内应趋同、边缘不再锐利
        # 采样跨黑白交界（文字块 x 从 20 开始，左侧 3px 白边），马赛克后边界被平均
        self.assertLess(_variance(out, (17, 21, 10, 10)), _variance(base, (17, 21, 10, 10)))
        # 块级马赛克：块内（8px 块）颜色一致
        self.assertEqual(out.pixel(18, 34), out.pixel(19, 34))   # 同一块内、避开译文区

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