# -*- coding: utf-8 -*-
"""实测：纯 ctypes 的 ExtractIconExW / SHGetFileInfoW 对 .lnk 返回什么图标？

ShellLink 的图标处理有两条路：
  · ExtractIconExW(path)      —— 走 shell 的 icon 提取器
  · SHGetFileInfoW(path,SHGFI_ICON)
已知 SHGetFileInfoW 对 .lnk 返回「快捷方式」默认图标（不解析目标）。
本脚本验证 ExtractIconExW 是否解析 .lnk 目标，并导出对比图。
"""
import ctypes
import os
import sys
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from PySide6.QtCore import QFileInfo, QSize
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QPixmap
from PySide6.QtWidgets import QApplication, QFileIconProvider

app = QApplication.instance() or QApplication([])
import boxes as bx

s32 = ctypes.windll.shell32
u32 = ctypes.windll.user32
s32.ExtractIconExW.restype = wintypes.UINT
s32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]

LNK = sys.argv[1] if len(sys.argv) > 1 else r'D:\Document\桌面快捷方式\LocalSend.lnk'
EXE = sys.argv[2] if len(sys.argv) > 2 else r'D:\Document\桌面快捷方式\快捷键检测.exe'


def extract(path, index=0):
    h_big, h_small = ctypes.c_void_p(), ctypes.c_void_p()
    n = s32.ExtractIconExW(path, index, ctypes.byref(h_big), ctypes.byref(h_small), 1)
    out = []
    for h, metric in ((h_small, 49), (h_big, 11)):   # SM_CXSMICON / SM_CXICON
        if h:
            img = bx._hicon_to_image(int(h.value), u32.GetSystemMetrics(metric))
            u32.DestroyIcon(int(h.value))
            if img is not None and not img.isNull():
                out.append(img)
    return n, out


for label, path in (('.lnk', LNK), ('.exe', EXE)):
    print('== %s : %s (%.1f KB)' % (label, os.path.basename(path),
                                     os.path.getsize(path) / 1024))
    t0 = __import__('time').perf_counter()
    n, imgs = extract(path)
    dt = (__import__('time').perf_counter() - t0) * 1000
    print('   ExtractIconExW -> n=%d, 图标 %d 个, 用时 %.1f ms' % (n, len(imgs), dt))
    qt = QFileIconProvider().icon(QFileInfo(path)).pixmap(QSize(16, 16), 1.0)
    print('   Qt QFileIconProvider -> %dx%d' % (qt.width(), qt.height()))

    # 并排导出
    sheet = QImage(420, 140, QImage.Format_ARGB32)
    sheet.fill(QColor(24, 24, 24))
    p = QPainter(sheet)
    p.setFont(QFont('Segoe UI', 9))
    p.setPen(QColor(230, 230, 230))
    p.drawText(8, 16, 'Qt (QFileIconProvider) %dx%d' % (qt.width(), qt.height()))
    p.drawPixmap(8, 22, qt)
    x = 80
    for i, im in enumerate(imgs):
        p.drawText(x, 16, 'ExtractIconEx %s' % ('small' if i == 0 else 'big'))
        p.drawPixmap(x, 22, QPixmap.fromImage(im))
        x += 70
    p.setPen(QColor(120, 200, 255))
    p.drawText(8, 120, 'x4 放大')
    for i, im in enumerate(imgs):
        big = QPixmap.fromImage(im).scaled(im.width() * 4, im.height() * 4,
                                           Qt.KeepAspectRatio, Qt.FastTransformation)
        p.drawPixmap(80 + i * 70, 44, big)
    p.end()
    out = os.path.join(HERE, 'results', 'lnk-icon-%s.png' % label.replace('.', '_'))
    sheet.save(out)
    print('   saved', out)
