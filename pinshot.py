# -*- coding: utf-8 -*-
"""钉图：把截图钉在桌面上的无边框贴图窗（Snipaste F3 / QQ 钉在桌面同款）。
点击/拖拽显示截图工具条、拖拽移动、滚轮等比缩放、双击复制并关闭；置顶 Tool 窗——故意不挂桌面带（挂带会被应用窗口压住，
贴图的意义就是浮在最上面随时对照）；不持久化，进程退出即消失。"""
import math
from datetime import datetime

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QColor, QImage, QPen
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

from i18n import t

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
        self._tl8n_busy = False     # 翻译中：顶部扫描线 + 底部状态胶囊
        self._tl8n_pair = None      # (原图, 译文图)：工具条翻译键切换
        self._mq_phase = 0.0
        self._mq_timer = QTimer(self)
        self._mq_timer.setInterval(50)           # 20fps 驱动扫描线与旋转指示
        self._mq_timer.timeout.connect(self._mq_tick)
        self._filter_installed = False
        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._app_state_changed)
        self.destroyed.connect(self._forget)

    def _forget(self, *_):
        if self in _pins:
            _pins.remove(self)

    def set_translate_busy(self, on):
        """翻译进行中：顶部扫描线 + 底部状态提示（图片中心不动）。"""
        if on:
            if self._tl8n_busy:
                return
            self._tl8n_busy = True
            self._mq_timer.start()
        else:
            self._tl8n_busy = False
            self._mq_timer.stop()
        self.update()

    def _mq_tick(self):
        self._mq_phase = (self._mq_phase + 0.025) % 1.0
        self.update()

    def _paint_translate_busy(self, p):
        """A 方案：顶部往返扫描，底部居中显示旋转指示和“正在翻译”。"""
        accent = QColor('#6ea8fe')
        phase = self._mq_phase
        scan_w = max(36.0, self.width() * 0.38)
        progress = (1.0 - math.cos(2 * math.pi * phase)) / 2.0
        scan_x = (self.width() - scan_w) * progress
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(110, 168, 254, 45))
        p.drawRect(QRectF(scan_x - 2, 0, scan_w + 4, 5))
        p.setBrush(accent)
        p.drawRect(QRectF(scan_x, 0, scan_w, 3))

        font = p.font()
        font.setPixelSize(12)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        text = fm.elidedText(t('shot.translate.translating'), Qt.ElideRight,
                             max(20, self.width() - 80))
        text_w = fm.horizontalAdvance(text)
        pill_w = min(self.width() - 16.0, 12 + 12 + 7 + text_w + 12)
        pill_h = 30.0
        pill_x = (self.width() - pill_w) / 2.0
        pill_y = max(6.0, self.height() - pill_h - 12.0)
        pill = QRectF(pill_x, pill_y, pill_w, pill_h)
        p.setPen(QPen(QColor(110, 168, 254, 150), 1))
        p.setBrush(QColor(20, 27, 38, 235))
        p.drawRoundedRect(pill, pill_h / 2.0, pill_h / 2.0)

        spinner = QRectF(pill_x + 12, pill_y + 9, 12, 12)
        p.setPen(QPen(QColor(110, 168, 254, 70), 2, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawArc(spinner, 0, 360 * 16)
        p.setPen(QPen(accent, 2, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(spinner, int(phase * 360 * 16), 100 * 16)
        p.setPen(QColor('#ffffff'))
        p.drawText(QRectF(pill_x + 31, pill_y, text_w + 2, pill_h),
                   Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, text)

    def finish_translate(self, layer):
        """翻译成功：译文图层压到图上（保留原图，工具条翻译键可切回原文）。"""
        img = QImage(self._img)
        p = QPainter(img)
        p.drawImage(0, 0, layer)
        p.end()
        self._tl8n_pair = (self._img, img)
        self._img = img
        self.set_translate_busy(False)

    def _translate_clicked(self):
        """工具条翻译键：已有译文 = 切换原文/译文；否则进编辑窗跑翻译。"""
        if self._tl8n_pair is not None:
            orig, translated = self._tl8n_pair
            self._img = translated if self._img is orig else orig
            btn = self._toolbar_btns.get('translate')
            if btn is not None:
                btn.setToolTip(t('shot.translate.show_original'
                                 if self._img is translated
                                 else 'shot.translate.show_translation'))
            self.update()
            return
        self._edit_image('translate')

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)   # 滚轮缩放后重采样不发虚
        p.drawImage(self.rect(), self._img)
        if self._tl8n_busy:
            p.setRenderHint(QPainter.Antialiasing)
            self._paint_translate_busy(p)
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
            self._copy_image()   # 双击 = 复制当前输出图并关闭（QQ 同款）
            self.close()
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
            'pen': lambda: self._edit_image('pen'),
            'text': lambda: self._edit_image('text'),
            'mosaic': lambda: self._edit_image('mosaic'),
            'marker': lambda: self._edit_image('marker'),
            'translate': self._translate_clicked,
            'save': self._save_image,
            'close': self._hide_toolbar,
            'confirm': self._copy_image,
        }
        self._toolbar, self._toolbar_btns = make_shot_toolbar(
            self, self._cfg, callbacks, exclude=PIN_TOOLBAR_EXCLUDED | {'undo'})
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
        self._editor = start_pin_edit(self._cfg, self._img, self.pos(), tool,
                                      pin_host=self)
        self._editor.pin_result.connect(self._apply_edited_image)
        self._editor.destroyed.connect(self._editor_closed)
        if (self._editor._tl8n or {}).get('pin') is not self:
            self.hide()   # 翻译委托态：钉图要露出来做 loading，不藏

    def _apply_edited_image(self, image):
        self._tl8n_pair = None   # 编辑后译文对应的是旧图，作废
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

    def _output_image(self):
        # 原文预览只影响显示；完成/复制/保存优先输出已生成的译文图。
        return self._tl8n_pair[1] if self._tl8n_pair is not None else self._img

    def _copy_image(self):
        QApplication.clipboard().setImage(self._output_image())
        self._hide_toolbar()

    def _save_image(self):
        name = t('shot.default_name', time=datetime.now().strftime('%Y%m%d_%H%M%S'))
        path, _f = QFileDialog.getSaveFileName(
            self, t('shot.save_title'), name, t('shot.save_filter'))
        if path:
            self._output_image().save(path)
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
