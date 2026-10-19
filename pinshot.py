# -*- coding: utf-8 -*-
"""钉图：把截图钉在桌面上的无边框贴图窗（Snipaste F3 / QQ 钉在桌面同款）。
点击/拖拽显示截图工具条、拖拽移动、滚轮等比缩放、双击关闭；置顶 Tool 窗——故意不挂桌面带（挂带会被应用窗口压住，
贴图的意义就是浮在最上面随时对照）；不持久化，进程退出即消失。"""
from datetime import datetime

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

_pins = []   # 存活引用：贴图窗无父对象，靠它防 GC；窗口销毁时移除


class PinWindow(QWidget):
    """一张钉住的截图：按 image 的 devicePixelRatio 还原逻辑尺寸 1:1 显示。"""

    def __init__(self, image, pos, border_color, cfg=None):
        super(PinWindow, self).__init__(None, Qt.FramelessWindowHint | Qt.Tool
                                        | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.SizeAllCursor)
        self._img = image
        self._border = QColor(border_color)
        self._cfg = cfg
        dpr = image.devicePixelRatio() or 1.0
        self._base_w = max(1, int(round(image.width() / dpr)))
        self._base_h = max(1, int(round(image.height() / dpr)))
        self._scale = 1.0
        self.resize(self._base_w, self._base_h)
        self.move(pos)
        self._drag = None
        self._press_global = None
        self._toolbar = None
        self._toolbar_btns = {}
        self._editor = None
        self._closing = False
        self._filter_installed = False
        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._app_state_changed)
        self.destroyed.connect(self._forget)

    def _forget(self, *_):
        if self in _pins:
            _pins.remove(self)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)   # 滚轮缩放后重采样不发虚
        p.drawImage(self.rect(), self._img)
        p.setPen(QPen(self._border, 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_global = e.globalPosition().toPoint()
            self._drag = self._press_global - self.frameGeometry().topLeft()
            self._show_toolbar()
            e.accept()
        else:
            super(PinWindow, self).mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            pos = e.globalPosition().toPoint()
            self.move(pos - self._drag)
            if self._toolbar is not None and self._toolbar.isVisible():
                self._place_toolbar()
            e.accept()
        else:
            super(PinWindow, self).mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        self._press_global = None
        super(PinWindow, self).mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.close()   # 双击关闭（QQ 同款）
        else:
            super(PinWindow, self).mouseDoubleClickEvent(e)

    def wheelEvent(self, e):
        """悬停滚轮 = 以窗口中心为锚点等比缩放（长宽同倍率，不变形）。"""
        d = e.angleDelta().y()
        if not d:
            return
        s = min(max(self._scale * 1.25 ** (d / 120.0), 0.1), 10.0)
        if s == self._scale:
            return
        self._scale = s
        w = max(1, int(round(self._base_w * s)))
        h = max(1, int(round(self._base_h * s)))
        c = self.geometry().center()
        self.setGeometry(c.x() - w // 2, c.y() - h // 2, w, h)
        if self._toolbar is not None and self._toolbar.isVisible():
            self._place_toolbar()
        e.accept()

    def _show_toolbar(self):
        if self._editor is not None:
            return
        if self._toolbar is None:
            self._build_toolbar()
        self._place_toolbar()
        self._toolbar.show()
        self._toolbar.raise_()
        app = QApplication.instance()
        if app is not None and not self._filter_installed:
            app.installEventFilter(self)
            self._filter_installed = True

    def _build_toolbar(self):
        from screenshot import make_shot_toolbar, PIN_TOOLBAR_EXCLUDED

        callbacks = {
            'rect': lambda: self._edit_image('rect'),
            'ellipse': lambda: self._edit_image('ellipse'),
            'arrow': lambda: self._edit_image('arrow'),
            'text': lambda: self._edit_image('text'),
            'marker': lambda: self._edit_image('marker'),
            'save': self._save_image,
            'close': self._hide_toolbar,
            'confirm': self._copy_image,
        }
        self._toolbar, self._toolbar_btns = make_shot_toolbar(
            self, self._cfg, callbacks, exclude=PIN_TOOLBAR_EXCLUDED)
        self._toolbar.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint
                                     | Qt.WindowStaysOnTopHint)
        self._toolbar.setAttribute(Qt.WA_ShowWithoutActivating)
        self._toolbar.setAttribute(Qt.WA_TranslucentBackground)
        self._toolbar.adjustSize()

    def _place_toolbar(self):
        if self._toolbar is None:
            return
        from screenshot import place_shot_toolbar

        place_shot_toolbar(self._toolbar, self.frameGeometry())

    def _hide_toolbar(self):
        if self._toolbar is not None:
            self._toolbar.hide()
        app = QApplication.instance()
        if app is not None and self._filter_installed:
            app.removeEventFilter(self)
            self._filter_installed = False

    def _owned_global_point(self, pos):
        return self.frameGeometry().contains(pos) or (
            self._toolbar is not None
            and self._toolbar.frameGeometry().contains(pos))

    def eventFilter(self, obj, event):
        if (self._toolbar is not None and self._toolbar.isVisible()
                and event.type() in (QEvent.MouseButtonPress,
                                     QEvent.MouseButtonDblClick)):
            if not self._owned_global_point(
                    event.globalPosition().toPoint()):
                self._hide_toolbar()
        return super(PinWindow, self).eventFilter(obj, event)

    def _app_state_changed(self, state):
        if state != Qt.ApplicationActive:
            self._hide_toolbar()

    def _edit_image(self, tool):
        from screenshot import start_pin_edit

        self._hide_toolbar()
        self._editor = start_pin_edit(self._cfg, self._img, self.pos(), tool)
        self._editor.pin_result.connect(self._apply_edited_image)
        self._editor.destroyed.connect(self._editor_closed)
        self.hide()

    def _apply_edited_image(self, image):
        self._img = image
        dpr = image.devicePixelRatio() or 1.0
        self._base_w = max(1, int(round(image.width() / dpr)))
        self._base_h = max(1, int(round(image.height() / dpr)))
        w = max(1, int(round(self._base_w * self._scale)))
        h = max(1, int(round(self._base_h * self._scale)))
        self.resize(w, h)
        self.update()

    def _editor_closed(self, *_):
        self._editor = None
        if not self._closing:
            self.show()
            self.raise_()

    def _copy_image(self):
        QApplication.clipboard().setImage(self._img)
        self._hide_toolbar()

    def _save_image(self):
        name = '截图_%s.png' % datetime.now().strftime('%Y%m%d_%H%M%S')
        path, _f = QFileDialog.getSaveFileName(
            self, '保存截图', name, 'PNG 图片 (*.png)')
        if path:
            self._img.save(path)
            self._hide_toolbar()

    def hideEvent(self, e):
        self._hide_toolbar()
        super(PinWindow, self).hideEvent(e)

    def closeEvent(self, e):
        self._closing = True
        self._hide_toolbar()
        if self._toolbar is not None:
            self._toolbar.close()
        if self._editor is not None:
            editor = self._editor
            self._editor = None
            try:
                editor.close()
            except RuntimeError:
                pass
        super(PinWindow, self).closeEvent(e)


def pin(image, pos, border_color, cfg=None):
    """钉一张图到桌面。image 为 QImage（含 dpr）；pos 为全局逻辑坐标（选区原位）。"""
    w = PinWindow(image, pos, border_color, cfg)
    _pins.append(w)
    w.show()
    return w
