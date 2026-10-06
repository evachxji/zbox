# -*- coding: utf-8 -*-
"""钉图：把截图钉在桌面上的无边框贴图窗（Snipaste F3 / QQ 钉在桌面同款）。
拖拽移动、双击关闭；置顶 Tool 窗——故意不挂桌面带（挂带会被应用窗口压住，
贴图的意义就是浮在最上面随时对照）；不持久化，进程退出即消失。"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QColor, QPen
from PyQt5.QtWidgets import QWidget

_pins = []   # 存活引用：贴图窗无父对象，靠它防 GC；窗口销毁时移除


class PinWindow(QWidget):
    """一张钉住的截图：按 image 的 devicePixelRatio 还原逻辑尺寸 1:1 显示。"""

    def __init__(self, image, pos, border_color):
        super(PinWindow, self).__init__(None, Qt.FramelessWindowHint | Qt.Tool
                                        | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip('拖拽移动 · 双击关闭')
        self._img = image
        self._border = QColor(border_color)
        dpr = image.devicePixelRatio() or 1.0
        self.resize(max(1, int(round(image.width() / dpr))),
                    max(1, int(round(image.height() / dpr))))
        self.move(pos)
        self._drag = None
        self.destroyed.connect(self._forget)

    def _forget(self, *_):
        if self in _pins:
            _pins.remove(self)

    def paintEvent(self, e):
        p = QPainter(self)
        p.drawImage(self.rect(), self._img)
        p.setPen(QPen(self._border, 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()
        else:
            super(PinWindow, self).mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag)
            e.accept()
        else:
            super(PinWindow, self).mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        super(PinWindow, self).mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.close()   # 双击关闭（QQ 同款）
        else:
            super(PinWindow, self).mouseDoubleClickEvent(e)


def pin(image, pos, border_color):
    """钉一张图到桌面。image 为 QImage（含 dpr）；pos 为全局逻辑坐标（选区原位）。"""
    w = PinWindow(image, pos, border_color)
    _pins.append(w)
    w.show()
    return w