# -*- coding: utf-8 -*-
"""轮廓灯效卡片（传输页 / 视频解析页共享）：待机呼吸灯、彩色跑马灯。
自绘描边（QSS 无法做动画）：定时器推相位，paintEvent 在 QSS 背景之上叠一层边框。
独立成模块而不是放 app.py：transfer_ui / video_ui 在 import 期就要以它为基类，
放 app.py 会撞三方循环 import（app → transfer_ui → app，类体求值时 GlowCard 还没定义）。
本模块只经 ui.sc() 运行期取 DPI 缩放，import 期不碰 app 的任何属性，循环安全。
"""

import math

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath
from PySide6.QtWidgets import QFrame

def _sc(v):
    """DPI 缩放（运行期惰性 import app，绕开 transfer_ui/video_ui 与 app 的循环）。"""
    import app as ui
    return ui.sc(v)


class GlowCard(QFrame):
    """轮廓灯效卡片（传输页 / 视频解析页共享）：待机呼吸灯、彩色跑马灯。
    自绘描边（QSS 无法做动画）：定时器推相位，paintEvent 在 QSS 背景之上叠一层边框。
    用法：set_glow('breath'/'run'/'')；呼吸灯用 set_accent 跟随主题（跑马灯是彩虹色不需要）。"""

    def __init__(self, parent=None):
        super(GlowCard, self).__init__(parent)
        self._mode = ''              # '' 无光 / 'breath' 呼吸 / 'run' 跑马灯
        self._phase = 0.0
        self._accent = QColor('#e8a33d')
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._poly_key = None        # 边框折线缓存键（尺寸）
        self._poly = None            # [(起始累计长度, a, b)...], 周长

    def set_accent(self, color):
        self._accent = QColor(color)

    def set_glow(self, mode):
        """mode: '' 熄灭 / 'breath' 呼吸灯 / 'run' 彩色跑马灯。"""
        if mode == self._mode:
            return
        self._mode = mode
        if mode:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.025) % 1.0   # 约 2.5s 一个周期
        self.update()

    def paintEvent(self, e):
        super(GlowCard, self).paintEvent(e)         # QSS 背景与基础边框
        if not self._mode:
            return
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
            rad = _sc(8)
            if self._mode == 'breath':
                alpha = 0.30 + 0.45 * (0.5 + 0.5 * math.sin(2 * math.pi * self._phase))
                c = QColor(self._accent)
                c.setAlphaF(alpha)
                pen = QPen(c, 2)
            else:   # run：彩虹沿边框顺时针追跑——逐段画折线，色相由「沿周长的
                # 位置 - 相位」决定（旧实现对角渐变+转色相：上下边同向变色，不像跑马灯）
                segs, total = self._border_segments(r, rad)
                for start, a, b in segs:
                    frac = ((start / total) - self._phase) % 1.0
                    p.setPen(QPen(QColor.fromHsv(int(frac * 360), 210, 255),
                                  2, Qt.SolidLine, Qt.RoundCap))
                    p.drawLine(a, b)
                p.end()
                return
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, rad, rad)
            p.end()
        except Exception:
            pass


    def _border_segments(self, r, rad):
        """圆角矩形边框的折线段 + 各段起点的累计周长（尺寸不变时缓存）。
        addRoundedRect 的 toSubpathPolygons 已把圆弧离散成小线段。"""
        key = (r.width(), r.height(), rad)
        if self._poly_key != key:
            path = QPainterPath()
            path.addRoundedRect(r, rad, rad)
            poly = path.toSubpathPolygons()[0]
            step = _sc(6)   # 直边在折线里是一整段，细分成小段彩虹才能沿边连续流动
            segs = []
            acc = 0.0
            for i in range(len(poly) - 1):
                a, b = poly[i], poly[i + 1]
                seg_len = math.hypot(b.x() - a.x(), b.y() - a.y())
                n = max(1, int(seg_len / step))
                for k in range(n):
                    t0, t1 = k / n, (k + 1) / n
                    segs.append((acc + seg_len * t0,
                                 a + (b - a) * t0, a + (b - a) * t1))
                acc += seg_len
            self._poly_key = key
            self._poly = (segs, acc)
        return self._poly

