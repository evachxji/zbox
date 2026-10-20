# -*- coding: utf-8 -*-
"""验证 P1-10：预渲染「底图+灰罩」后的遮罩渲染与原算法逐像素一致。

做法：用同一组 _screens（合成底图，不依赖真实桌面）与同一个选区，
分别按「旧算法」和「新算法」渲染到 QPixmap，逐像素比对。

用法：python perf-audit\\verify_overlay.py
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])
import screenshot as S

MASK_COLOR = S.MASK_COLOR

W, H = 1600, 900


def make_screens():
    """两块屏幕的合成底图（随机色块，便于发现错位）。"""
    scr = []
    for i, (x, y, w, h) in enumerate(((0, 0, 1000, 900), (1000, 0, 600, 900))):
        pm = QPixmap(w, h)
        p = QPainter(pm)
        for _ in range(60):
            p.fillRect(random.randrange(w), random.randrange(h),
                       random.randrange(10, 80), random.randrange(10, 80),
                       QColor(random.randrange(256), random.randrange(256),
                                random.randrange(256)))
        p.end()
        scr.append((QRect(x, y, w, h), pm, 1.0))
    return scr


def old_render(screens, sel):
    """原算法：全屏底图 → 全屏灰罩 → clip 选区再画一遍全屏底图。"""
    out = QPixmap(W, H)
    out.fill(Qt.transparent)
    p = QPainter(out)
    for rect, pm, _d in screens:
        p.drawPixmap(rect, pm)
    p.fillRect(out.rect(), MASK_COLOR)
    if sel.isValid() and not sel.isNull():
        p.save()
        p.setClipRect(sel)
        for rect, pm, _d in screens:
            p.drawPixmap(rect, pm)
        p.restore()
    p.end()
    return out


def new_render(screens, sel):
    """新算法：预渲染「底图+灰罩」→ blit 一次 → 选区镂空只画选区大小。"""
    base = QPixmap(W, H)
    base.fill(Qt.transparent)
    p = QPainter(base)
    for rect, pm, _d in screens:
        p.drawPixmap(rect, pm)
    p.fillRect(base.rect(), MASK_COLOR)
    p.end()

    out = QPixmap(W, H)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawPixmap(0, 0, base)
    if sel.isValid() and not sel.isNull():
        hole = QPixmap(sel.size())
        hp = QPainter(hole)
        for rect, pm, _d in screens:
            inter = rect.intersected(sel)
            if inter.isEmpty():
                continue
            src = inter.translated(-rect.topLeft())
            hp.drawPixmap(inter.topLeft() - sel.topLeft(), pm, src)
        hp.end()
        p.drawPixmap(sel.topLeft(), hole)
    p.end()
    return out


def diff(a, b):
    ia = a.toImage().convertToFormat(__import__('PySide6.QtGui', fromlist=['QImage']).QImage.Format_ARGB32)
    ib = b.toImage().convertToFormat(__import__('PySide6.QtGui', fromlist=['QImage']).QImage.Format_ARGB32)
    if ia.size() != ib.size():
        return -1, '尺寸不同'
    ba = bytes(ia.bits())
    bb = bytes(ib.bits())
    n = sum(1 for i in range(0, min(len(ba), len(bb)), 4) if ba[i:i + 4] != bb[i:i + 4])
    return n, ''


random.seed(20261020)
sels = [
    QRect(),
    QRect(100, 80, 400, 300),          # 单屏内
    QRect(900, 200, 300, 400),          # 跨两屏
    QRect(0, 0, 1600, 900),             # 全屏
    QRect(950, 850, 200, 200),          # 跨右下角（超出边界）
]
bad = 0
for i, sel in enumerate(sels):
    screens = make_screens()
    a = old_render(screens, sel)
    b = new_render(screens, sel)
    n, note = diff(a, b)
    ok = (n == 0)
    if not ok:
        bad += 1
    print('选区 %-28s 差异像素 %-8d %s %s' % (str(sel), n, '✓' if ok else '✗', note))
print('\n%s' % ('全部选区逐像素一致 ✓' if bad == 0 else '有 %d 处不一致 ✗' % bad))
sys.exit(0 if bad == 0 else 1)
