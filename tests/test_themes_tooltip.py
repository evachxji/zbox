# -*- coding: utf-8 -*-
"""主题 QSS 完整性：两套主题都必须显式定义 QToolTip 背景（缺失时回落到系统深色调色板）。"""
import re
import unittest

from themes import build_qss


class ThemeTooltipTest(unittest.TestCase):
    def test_both_themes_define_tooltip_background(self):
        for theme in ('nocturne', 'mica'):
            qss = build_qss(theme, 'Microsoft YaHei', 'Segoe UI')
            m = re.search(r'QToolTip\s*\{[^}]*background-color:\s*(#[0-9a-fA-F]{3,8})', qss)
            self.assertIsNotNone(m, '%s 缺少 QToolTip 背景色定义' % theme)
            color = m.group(1).lower()
            rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
            lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
            if theme == 'mica':
                self.assertGreater(lum, 200, '浅色主题 tooltip 背景必须是浅色：%s' % color)
            else:
                self.assertLess(lum, 120, '深色主题 tooltip 背景必须是深色：%s' % color)


if __name__ == '__main__':
    unittest.main()