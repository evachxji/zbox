# -*- coding: utf-8 -*-
"""导出「旧路线 vs 新路线」的图标并排 PNG，放大目检差异来源。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from PySide6.QtCore import QFileInfo, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QPixmap
from PySide6.QtWidgets import QApplication, QFileIconProvider

app = QApplication.instance() or QApplication([])
import boxes as bx

path = sys.argv[1] if len(sys.argv) > 1 else r'D:\Document\桌面快捷方式\LocalSend.lnk'
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, 'results', 'icon-compare.png')
dpr = app.primaryScreen().devicePixelRatio()
px = max(1, int(round(16 * dpr)))

provider = QFileIconProvider()
old = provider.icon(QFileInfo(path)).pixmap(QSize(16, 16), dpr)
px = max(1, int(round(16 * dpr)))
_img = bx._shell_icon_image(path, False, px)
new = QPixmap.fromImage(_img) if (_img is not None and not _img.isNull()) else QPixmap()

ZOOM = 6
W, H = 520, 210
sheet = QImage(W * dpr, H * dpr, QImage.Format_ARGB32)
sheet.fill(QColor(24, 24, 24))
p = QPainter(sheet)
p.setRenderHint(QPainter.TextAntialiasing)
p.scale(dpr, dpr)
f = QFont('Segoe UI', 9)
p.setFont(f)
p.setPen(QColor(230, 230, 230))
p.drawText(8, 16, 'old (QFileIconProvider.pixmap)  %dx%d' % (old.width(), old.height()))
p.drawText(8, 96, 'new (SHGetFileInfoW+DrawIconEx) %dx%d' % (new.width(), new.height()))
p.drawText(300, 16, os.path.basename(path))
# 原始尺寸
p.drawPixmap(8, 22, old)
p.drawPixmap(8, 102, new)
# 6 倍放大（NearestNeighbor 看像素）
big_old = old.scaled(old.width() * ZOOM, old.height() * ZOOM,
                     Qt.KeepAspectRatio, Qt.FastTransformation)
big_new = new.scaled(new.width() * ZOOM, new.height() * ZOOM,
                     Qt.KeepAspectRatio, Qt.FastTransformation)
p.drawPixmap(150, 22, big_old)
p.drawPixmap(150, 102, big_new)
p.setPen(QColor(120, 200, 255))
p.drawText(300, 40, 'x%d 放大' % ZOOM)
p.end()
sheet.save(out)
print('saved', out, ' dpr=%s px=%s' % (dpr, px))
