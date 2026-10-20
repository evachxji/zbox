# -*- coding: utf-8 -*-
"""性能优化引入的**功能性**防退化测试（2026-10 性能审计）。

优化不能改变结果，只改变「算得多快」。这几条把「结果必须与优化前逐位相同」
钉死，避免后来者为了更快而悄悄改了算法：

  * `_find_shift`（长图帧匹配）：位移与灰度差必须与优化前的纯 Python 实现完全一致 ——
    不一致 = 长图拼接错位（把已拼内容当新内容拼出重复段）。
  * `_luminance`（译文深浅色选择）：采样亮度必须与优化前一致。
  * `_hue_pens`（跑马灯色相档数）：必须是 360 —— 与原 `int(frac*360)` 同一套索引，
    改档位就会改变渲染像素。
  * `build_qss`（主题 QSS）：带缓存后输出必须与未缓存的原实现逐字节相同。
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import screenshot as S          # noqa: E402
import themes                   # noqa: E402
import translation_render as tr  # noqa: E402


def _ref_find_shift(prev, cur):
    """_find_shift 优化前的参考实现（纯 Python 索引循环）。"""
    n = min(len(prev), len(cur))
    cands = []
    for s in range(0, min(n - 2, n // 2) + 1):
        d, cnt = 0, 0
        for i in range(0, n - s, 2):
            d += abs(prev[s + i][0] - cur[i][0])
            cnt += 1
        if cnt:
            cands.append((d / cnt, s))
    scores = []
    for _m, s in sorted(cands)[:5]:
        d, cnt = 0, 0
        for i in range(0, n - s, 2):
            pa, ca = prev[s + i][1], cur[i][1]
            for x in range(S._SIG_BUCKETS):
                d += abs(pa[x] - ca[x])
                cnt += 1
        if cnt:
            scores.append((d / cnt, s))
    if not scores:
        return 0, 1e9
    best_d = min(d for d, _s in scores)
    best_s = min(s for d, s in scores if d <= best_d * 1.1 + 0.5)
    return best_s, best_d


def _ref_luminance(img, px_rect):
    x, y, w, h = px_rect
    total = count = 0
    for yy in range(y, y + h, 4):
        for xx in range(x, x + w, 4):
            from PySide6.QtGui import QColor
            c = QColor(img.pixel(min(xx, img.width() - 1), min(yy, img.height() - 1)))
            total += 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
            count += 1
    return (total / count / 255.0) if count else 1.0


def _sig(n, seed):
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        b = tuple(rnd.randrange(256) for _ in range(S._SIG_BUCKETS))
        out.append((sum(b) // len(b), b))
    return out


class TestFindShiftUnchanged(unittest.TestCase):
    def test_same_result_as_reference(self):
        for n in (120, 300, 540):
            for seed in range(4):
                prev = _sig(n, seed)
                shift = random.Random(seed * 13 + 5).randrange(1, max(2, n // 3))
                cur = prev[shift:] + _sig(n - shift, seed + 4242)
                a = _ref_find_shift(prev, cur)
                b = S._find_shift(prev, cur)
                self.assertEqual(a[0], b[0], 'n=%d seed=%d 位移不一致' % (n, seed))
                self.assertAlmostEqual(a[1], b[1], places=9,
                                       msg='n=%d seed=%d 灰度差不一致' % (n, seed))

    def test_finds_actual_shift(self):
        """构造明确位移的场景：应找回真实位移。"""
        prev = _sig(200, 11)
        shift = 37
        cur = prev[shift:] + _sig(200 - shift, 99)
        got, diff = S._find_shift(prev, cur)
        self.assertEqual(got, shift)
        self.assertLess(diff, 5.0)


class TestLuminanceUnchanged(unittest.TestCase):
    def test_same_as_reference(self):
        from PySide6.QtGui import QColor, QImage, QPainter
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        rnd = random.Random(3)
        img = QImage(400, 200, QImage.Format_ARGB32)
        img.fill(QColor(10, 20, 30))
        p = QPainter(img)
        for _ in range(60):
            p.fillRect(rnd.randrange(400), rnd.randrange(200), 30, 30,
                       QColor(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
        p.end()
        for rect in ((0, 0, 400, 200), (50, 30, 120, 90), (390, 190, 20, 20), (0, 0, 0, 0)):
            self.assertAlmostEqual(_ref_luminance(img, rect),
                                   tr._luminance(img, rect), places=12,
                                   msg='区域 %s 亮度不一致' % (rect,))


class TestHuePensUnchanged(unittest.TestCase):
    def test_hue_buckets_stay_360(self):
        """色相档数必须是 360 —— 与原 int(frac*360) 同一套索引，改了像素就变。"""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import glow
        card = glow.GlowCard()
        pens = card._hue_pens()
        self.assertEqual(len(pens), 360)
        # 第 i 档的色相应与 fromHsv(i) 一致
        from PySide6.QtGui import QColor
        for i in (0, 1, 123, 359):
            self.assertEqual(pens[i].color().hue(), QColor.fromHsv(i, 210, 255).hue())


class TestBuildQssUnchanged(unittest.TestCase):
    def test_same_bytes_as_uncached(self):
        import re
        for key in themes.THEMES:
            for scale in (1.0, 1.25, 1.5, 2.0):
                qss = themes.THEMES[key]['qss'] \
                    .replace('%CN%', 'Microsoft YaHei').replace('%NUM%', 'Bahnschrift') \
                    .replace('%ICON_DIR%', 'C:/icons')
                if abs(scale - 1.0) > 1e-6:
                    qss = re.sub(r'(\d+(?:\.\d+)?)px',
                                 lambda m: '%gpx' % (round(float(m.group(1)) * scale, 2)), qss)
                qss = re.sub(r'%R=(\d+)%',
                             lambda m: '%d' % (int(round(int(m.group(1)) * scale)) // 2), qss)
                self.assertEqual(
                    themes.build_qss(key, 'Microsoft YaHei', 'Bahnschrift', scale, 'C:/icons'),
                    qss, '主题 %s @ %s 的 QSS 与未缓存实现不一致' % (key, scale))


if __name__ == '__main__':
    unittest.main()
