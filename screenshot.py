# -*- coding: utf-8 -*-
"""QQ 风格截图：全局热键 → 全屏灰罩 → 框选 → 标注 → 复制/保存/钉图/长图。

- 遮罩与标注全部自绘；工具条是遮罩窗的子控件，QSS 由 PALETTES 按面板主题
  （nocturne 深色磨砂 / mica 浅色磨砂）现拼，不进 themes.py 的面板 QSS 体系。
- 全局热键 HotkeyManager：ctypes RegisterHotKey + QAbstractNativeEventFilter 收
  WM_HOTKEY；配置为空 = 不注册；apply() 即时注销重注册。
- 截长图：遮罩隐藏后由用户自己滚动页面（滚轮事件自然落到目标窗口），
  定时器抓选区帧、按行签名纵向拼接；✓ 完成导出，Esc/✕ 取消。
"""
import ctypes
from ctypes import wintypes
from datetime import datetime

from PySide6.QtCore import (Qt, QRect, QRectF, QPoint, QPointF, QSize, QTimer, QEvent,
                          Signal, QAbstractNativeEventFilter)
from PySide6.QtGui import (QPainter, QColor, QPen, QPixmap, QImage, QFont, QFontMetrics,
                         QKeySequence, QPainterPath, QCursor, QGuiApplication, QIcon)
from PySide6.QtWidgets import (QWidget, QApplication, QFrame, QHBoxLayout, QToolButton,
                             QLabel, QLineEdit, QPushButton, QFileDialog)

import app as ui          # sc / ui_scale / pick_fonts / resolve_theme
import pinshot

_u32 = ctypes.windll.user32
_u32.RegisterHotKey.restype = wintypes.BOOL
_u32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_u32.UnregisterHotKey.restype = wintypes.BOOL
_u32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]

MASK_COLOR = QColor(0, 0, 0, 120)          # 灰罩
DOT_COLORS = ['#ff4d4f', '#ff9f1a', '#ffd54a', '#35c759', '#2f9bff', '#ffffff']
SHAPE_W = {'s': 2.0, 'm': 3.5, 'l': 5.0}   # 矩形/椭圆线宽（逻辑 px）
TEXT_PX = {'s': 13, 'm': 16, 'l': 20}      # 文字字号（逻辑 px）
HANDLES = ('nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w')
MIN_SEL = 4                                # 小于这个尺寸视为误点，不成选区
LONG_MAX_H = 30000                         # 长图物理像素上限，超出自动完成

# 两套调色板：随面板主题切换（resolve_theme 把 auto 解析成真主题）
PALETTES = {
    'nocturne': {
        'accent': '#e8a33d', 'accent_text': '#1a1610', 'accent_soft': 'rgba(232,163,61,40)',
        'accent_border': 'rgba(232,163,61,128)', 'bar_solid': '#1b1d24',
        'bar_bg': 'rgba(27,29,36,242)', 'bar_border': 'rgba(255,255,255,18)',
        'icon': '#7d7a72', 'icon_hov_bg': 'rgba(255,255,255,20)',
        'sep': 'rgba(255,255,255,26)', 'hint': '#a8a49a',
        'dot_ring': 'rgba(255,255,255,30)', 'dot_ring_on': '#e8a33d',
        'label_bg': 'rgba(27,29,36,235)', 'label_border': 'rgba(232,163,61,102)',
        'sel': '#e8a33d', 'handle_bg': '#1b1d24',
    },
    'mica': {
        'accent': '#0067c0', 'accent_text': '#ffffff', 'accent_soft': 'rgba(0,103,192,30)',
        'accent_border': 'rgba(0,103,192,115)', 'bar_solid': '#f7f8fa',
        'bar_bg': 'rgba(247,248,250,245)', 'bar_border': 'rgba(0,0,0,23)',
        'icon': '#8a8a90', 'icon_hov_bg': 'rgba(0,0,0,15)',
        'sep': 'rgba(0,0,0,30)', 'hint': '#5b5b60',
        'dot_ring': 'rgba(0,0,0,26)', 'dot_ring_on': '#0067c0',
        'label_bg': 'rgba(247,248,250,242)', 'label_border': 'rgba(0,103,192,89)',
        'sel': '#0067c0', 'handle_bg': '#ffffff',
    },
}


def _icon(kind, color, fill=None):
    """工具条线性图标：24 虚拟网格矢量绘制（对齐 app.make_cal_icon 的画法）。"""
    s = ui.sc(20)
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(s / 24.0, s / 24.0)
    pen = QPen(QColor(color), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if kind == 'rect':
        p.drawRoundedRect(QRectF(4, 6, 16, 12), 1.5, 1.5)
    elif kind == 'ellipse':
        p.drawEllipse(QRectF(3.5, 5.5, 17, 13))
    elif kind == 'text':
        p.drawLine(QPointF(5, 6.5), QPointF(19, 6.5))
        p.drawLine(QPointF(12, 6.5), QPointF(12, 18))
        p.drawLine(QPointF(9, 18), QPointF(15, 18))
    elif kind == 'undo':
        path = QPainterPath(QPointF(8.5, 7))
        path.lineTo(QPointF(4.5, 11))
        path.lineTo(QPointF(8.5, 15))
        p.drawPath(path)
        path = QPainterPath(QPointF(4.5, 11))
        path.lineTo(QPointF(13, 11))
        path.arcTo(QRectF(7.5, 11, 11, 11), 90, -180)
        path.lineTo(QPointF(10, 22))
        p.drawPath(path)
    elif kind == 'long':
        p.drawRoundedRect(QRectF(8, 3.5, 8, 6), 1, 1)
        p.drawRoundedRect(QRectF(8, 14.5, 8, 6), 1, 1)
        p.setPen(QPen(QColor(color), 1.5, Qt.DashLine, Qt.RoundCap))
        p.drawLine(QPointF(9, 12), QPointF(15, 12))
    elif kind == 'pin':
        path = QPainterPath(QPointF(9.5, 4))
        path.lineTo(QPointF(14.5, 4))
        path.lineTo(QPointF(13.7, 9.2))
        path.lineTo(QPointF(16.5, 12))
        path.lineTo(QPointF(16.5, 14))
        path.lineTo(QPointF(7.5, 14))
        path.lineTo(QPointF(7.5, 12))
        path.lineTo(QPointF(10.3, 9.2))
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(12, 14), QPointF(12, 20))
    elif kind == 'save':
        p.drawLine(QPointF(12, 4), QPointF(12, 13.5))
        p.drawLine(QPointF(7.5, 10), QPointF(12, 14.5))
        p.drawLine(QPointF(16.5, 10), QPointF(12, 14.5))
        p.drawLine(QPointF(5, 19.5), QPointF(19, 19.5))
    elif kind == 'copy':
        p.drawRoundedRect(QRectF(4, 4, 11, 11), 1.5, 1.5)
        if fill:
            p.setBrush(QColor(fill))
        p.drawRoundedRect(QRectF(9, 9, 11, 11), 1.5, 1.5)
    elif kind == 'close':
        p.drawLine(QPointF(6.5, 6.5), QPointF(17.5, 17.5))
        p.drawLine(QPointF(17.5, 6.5), QPointF(6.5, 17.5))
    elif kind == 'check':
        p.setPen(QPen(QColor(color), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(5, 12.5), QPointF(10, 17))
        p.drawLine(QPointF(10, 17), QPointF(19, 7))
    p.end()
    return pm


def _qss(pal, cn, num):
    """遮罩子控件（工具条/二级条/尺寸标签/长图条）的局部 QSS，按调色板现拼。"""
    return """
QFrame#shotBar { background: %(bar_bg)s; border: 1px solid %(bar_border)s; border-radius: 10px; }
QToolButton#shotBtn { background: transparent; border: none; border-radius: 6px; color: %(icon)s; }
QToolButton#shotBtn:hover { background: %(icon_hov_bg)s; }
QToolButton#shotBtn[on="true"] { background: %(accent_soft)s; }
QToolButton#shotClose { background: transparent; border: none; border-radius: 6px; color: %(icon)s; }
QToolButton#shotClose:hover { background: #c42b1c; }
QPushButton#shotConfirm {
    background: %(accent)s; border: none; border-radius: 6px;
    color: %(accent_text)s; font: 600 12px "%(cn)s"; padding: 0 14px;
}
QFrame#shotSep { background: %(sep)s; }
QToolButton#shotDot { border-radius: 8px; border: 2px solid %(dot_ring)s; }
QToolButton#shotDot[on="true"] { border-color: %(dot_ring_on)s; }
QToolButton#shotSz { background: transparent; border: none; border-radius: 4px; color: %(icon)s; font: 600 11px "%(num)s"; }
QToolButton#shotSz[on="true"] { background: %(accent_soft)s; color: %(accent)s; }
QToolButton#shotInvert {
    background: transparent; border: 1px solid %(accent_border)s; border-radius: 11px;
    color: %(accent)s; font: 600 11px "%(cn)s"; padding: 0 10px;
}
QToolButton#shotInvert[on="true"] { background: %(accent)s; color: %(accent_text)s; }
QToolButton#shotInvert:disabled { color: %(icon)s; border-color: %(bar_border)s; }
QLabel#shotSize {
    background: %(label_bg)s; color: %(accent)s; border: 1px solid %(label_border)s;
    border-radius: 4px; font: 12px "%(num)s"; padding: 4px 10px;
}
QLabel#shotHint { color: %(hint)s; font: 12px "%(cn)s"; padding: 0 6px; }
""" % dict({'cn': cn, 'num': num}, **pal)


def _contrast(color):
    """反色文字的字色：色块亮则用深字，暗则用白字。"""
    c = QColor(color)
    lum = (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255.0
    return '#1a1610' if lum > 0.55 else '#ffffff'

# ---------------- 长图拼接：行签名匹配 ----------------

_SIG_ROW = 2   # 行签名每 2 行取一行
_SIG_COL = 4   # 行内每 4 列取一个像素


def _row_sig(img):
    """灰度行签名：每行采样像素的均值列表，用于相邻帧找纵向位移。"""
    g = img.convertToFormat(QImage.Format_Grayscale8)
    w, h = g.width(), g.height()
    bpl = g.bytesPerLine()
    ptr = g.bits()
    ptr.setsize(g.byteCount())
    buf = bytes(ptr.asarray())   # voidptr.asarray 的对象不支持步长切片，转成真 bytes
    sig = []
    for y in range(0, h, _SIG_ROW):
        row = buf[y * bpl:y * bpl + w:_SIG_COL]
        sig.append(sum(row) // max(1, len(row)))
    return sig


def _find_shift(prev, cur):
    """prev 向下滚动后变成 cur：找位移 s（签名行数）使 prev[s:] 与 cur[:n-s] 最吻合。
    返回 (s, 平均灰度差)。差值大 = 画面动画/跳变，不可信。"""
    n = min(len(prev), len(cur))
    best_s, best_d = 0, 1e9
    for s in range(0, n - 2):
        d, cnt = 0, 0
        for i in range(0, n - s, 2):
            d += abs(prev[s + i] - cur[i])
            cnt += 1
        if cnt:
            m = d / cnt
            if m < best_d:
                best_d, best_s = m, s
    return best_s, best_d


# ---------------- 长图控制条 ----------------

class _LongBar(QWidget):
    """长图模式的悬浮控制条：遮罩隐藏后它是会话唯一的可见 UI。"""

    done = Signal()
    canceled = Signal()

    def __init__(self, qss, parent=None):
        super(_LongBar, self).__init__(parent, Qt.FramelessWindowHint | Qt.Tool
                                       | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        card = QFrame(self)
        card.setObjectName('shotBar')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(card)
        row = QHBoxLayout(card)
        row.setContentsMargins(ui.sc(10), ui.sc(6), ui.sc(6), ui.sc(6))
        row.setSpacing(ui.sc(6))
        self._hint = QLabel('滚动鼠标滚轮拼接长图')
        self._hint.setObjectName('shotHint')
        row.addWidget(self._hint)
        ok = QPushButton('✓ 完成')
        ok.setObjectName('shotConfirm')
        ok.setFixedHeight(ui.sc(28))
        ok.setCursor(Qt.PointingHandCursor)
        ok.setFocusPolicy(Qt.NoFocus)
        ok.clicked.connect(self.done)
        row.addWidget(ok)
        no = QToolButton()
        no.setObjectName('shotClose')
        no.setText('✕')
        no.setFixedSize(ui.sc(28), ui.sc(28))
        no.setCursor(Qt.PointingHandCursor)
        no.setFocusPolicy(Qt.NoFocus)
        no.setToolTip('取消长图')
        no.clicked.connect(self.canceled)
        row.addWidget(no)
        self.setStyleSheet(qss)

    def set_status(self, text):
        self._hint.setText(text)
        self.adjustSize()

    def showEvent(self, e):
        super(_LongBar, self).showEvent(e)
        self.activateWindow()
        self.raise_()
        self.grabKeyboard()   # Tool 窗未必拿得到焦点，Esc/Enter 靠抢键盘保证

    def closeEvent(self, e):
        self.releaseKeyboard()
        super(_LongBar, self).closeEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.canceled.emit()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.done.emit()
        else:
            super(_LongBar, self).keyPressEvent(e)


# ---------------- 截图会话 ----------------

class ShotOverlay(QWidget):
    """全屏灰罩 + 框选 + 标注 + 工具条。构造时先抓屏再显示，遮罩不会入镜。"""

    finished = Signal()   # 会话结束（无论结果），入口用来清引用

    def __init__(self, cfg):
        super(ShotOverlay, self).__init__(None, Qt.FramelessWindowHint | Qt.Tool
                                          | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self._cfg = cfg
        self.pal = PALETTES.get(ui.resolve_theme(cfg.data.get('theme')), PALETTES['nocturne'])
        self._cn, self._num = ui.pick_fonts()

        vg = QRect()
        for s in QGuiApplication.screens():
            vg = vg.united(s.geometry())
        self._tl = vg.topLeft()
        # 先抓底图（遮罩还没 show，抓到的就是真实桌面）
        self._screens = []
        for s in QGuiApplication.screens():
            pm = s.grabWindow(0)
            self._screens.append((QRect(s.geometry().topLeft() - self._tl, s.geometry().size()),
                                  pm, pm.devicePixelRatio()))
        self.setGeometry(vg)

        self._mode = 'idle'        # idle / creating / ready
        self._drag = None          # (种类, 附加数据)
        self._sel = QRect()
        self._shapes = []          # 已完成的标注
        self._cur = None           # 绘制中的矩形/椭圆
        self._tool = None          # None / rect / ellipse / text
        self._color = DOT_COLORS[0]
        self._size = 'm'
        self._invert = False
        self._editor = None        # (QLineEdit, QPointF 落点)
        self._long = None          # 长图模式状态 dict

        self._build_chrome()
        self.setStyleSheet(_qss(self.pal, self._cn, self._num))

    # ---------- 子控件 ----------

    def _build_chrome(self):
        self.size_label = QLabel(self)
        self.size_label.setObjectName('shotSize')
        self.size_label.hide()

        self.bar = QFrame(self)
        self.bar.setObjectName('shotBar')
        lay = QHBoxLayout(self.bar)
        lay.setContentsMargins(ui.sc(6), ui.sc(6), ui.sc(6), ui.sc(6))
        lay.setSpacing(2)
        self._tool_btns = {}
        for kind, tip in (('rect', '矩形'), ('ellipse', '椭圆'), ('text', '文字'),
                          ('undo', '撤销 (Ctrl+Z)')):
            b = self._mk_btn(kind, tip, lay)
            if kind != 'undo':
                self._tool_btns[kind] = b
                b.clicked.connect(lambda _=False, k=kind: self._set_tool(k))
            else:
                b.clicked.connect(self._undo)
        lay.addWidget(self._sep())
        for kind, tip, fn in (('long', '截长图', self._start_long),
                              ('pin', '钉在桌面', self._finish_pin),
                              ('save', '保存', self._finish_save),
                              ('copy', '复制到剪贴板', self._finish_copy)):
            b = self._mk_btn(kind, tip, lay)
            b.clicked.connect(fn)
        lay.addWidget(self._sep())
        close = self._mk_btn('close', '取消 (Esc)', lay, obj='shotClose')
        close.clicked.connect(self._cancel)
        ok = QPushButton('完成')
        ok.setObjectName('shotConfirm')
        ok.setFixedHeight(ui.sc(30))
        ok.setCursor(Qt.PointingHandCursor)
        ok.setFocusPolicy(Qt.NoFocus)
        ok.setToolTip('复制到剪贴板并关闭 (Enter)')
        ok.clicked.connect(self._finish_copy)
        lay.addWidget(ok)
        self.bar.hide()

        # 二级条：颜色 / 粗细(字号) / 反色（激活绘图工具时出现）
        self.sub = QFrame(self)
        self.sub.setObjectName('shotBar')
        sl = QHBoxLayout(self.sub)
        sl.setContentsMargins(ui.sc(10), ui.sc(7), ui.sc(10), ui.sc(7))
        sl.setSpacing(ui.sc(7))
        self._dots = []
        for c in DOT_COLORS:
            d = QToolButton()
            d.setObjectName('shotDot')
            d.setStyleSheet('background: %s;' % c)
            d.setFixedSize(ui.sc(16), ui.sc(16))
            d.setCursor(Qt.PointingHandCursor)
            d.setFocusPolicy(Qt.NoFocus)
            d.setProperty('on', 'true' if c == self._color else 'false')
            d.clicked.connect(lambda _=False, cc=c: self._set_color(cc))
            sl.addWidget(d)
            self._dots.append((c, d))
        sl.addWidget(self._sep())
        self._sz_btns = {}
        for k, t in (('s', 'S'), ('m', 'M'), ('l', 'L')):
            b = QToolButton()
            b.setObjectName('shotSz')
            b.setText(t)
            b.setFixedSize(ui.sc(24), ui.sc(22))
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setProperty('on', 'true' if k == self._size else 'false')
            b.clicked.connect(lambda _=False, kk=k: self._set_size(kk))
            sl.addWidget(b)
            self._sz_btns[k] = b
        sl.addWidget(self._sep())
        self._invert_btn = QToolButton()
        self._invert_btn.setObjectName('shotInvert')
        self._invert_btn.setText('Aa 反色')
        self._invert_btn.setFixedHeight(ui.sc(23))
        self._invert_btn.setCursor(Qt.PointingHandCursor)
        self._invert_btn.setFocusPolicy(Qt.NoFocus)
        self._invert_btn.setToolTip('文字垫色块、字色取反（仅文字工具可用）')
        self._invert_btn.setProperty('on', 'false')
        self._invert_btn.clicked.connect(self._toggle_invert)
        sl.addWidget(self._invert_btn)
        self.sub.hide()

    def _sep(self):
        s = QFrame()
        s.setObjectName('shotSep')
        s.setFixedSize(1, ui.sc(16))
        return s

    def _mk_btn(self, kind, tip, lay, obj='shotBtn'):
        b = QToolButton()
        b.setObjectName(obj)
        b.setFixedSize(ui.sc(30), ui.sc(30))
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        b.setToolTip(tip)
        lay.addWidget(b)
        b._icon_kind = kind
        return b

    def _refresh_icons(self):
        """图标颜色随状态变化（on 用主题色）：重新生成各按钮图标。"""
        p = self.pal
        for b in self.bar.findChildren(QToolButton):
            kind = getattr(b, '_icon_kind', None)
            if not kind:
                continue
            on = b.property('on') == 'true'
            color = p['accent'] if on else p['icon']
            b.setIcon(QIcon(_icon(kind, color, fill=p['bar_solid'])))
            b.setIconSize(QSize(ui.sc(16), ui.sc(16)))

    # ---------- 状态操作 ----------

    def _set_tool(self, t):
        if self._editor:
            self._commit_editor()
        self._tool = None if self._tool == t else t
        for k, b in self._tool_btns.items():
            b.setProperty('on', 'true' if k == self._tool else 'false')
            b.style().unpolish(b)
            b.style().polish(b)
        self._invert_btn.setEnabled(self._tool == 'text')
        self._refresh_icons()
        self._update_chrome()
        self._update_cursor(QCursor.pos())

    def _set_color(self, c):
        self._color = c
        for cc, d in self._dots:
            d.setProperty('on', 'true' if cc == c else 'false')
            d.style().unpolish(d)
            d.style().polish(d)

    def _set_size(self, k):
        self._size = k
        for kk, b in self._sz_btns.items():
            b.setProperty('on', 'true' if kk == k else 'false')
            b.style().unpolish(b)
            b.style().polish(b)

    def _toggle_invert(self):
        self._invert = not self._invert
        self._invert_btn.setProperty('on', 'true' if self._invert else 'false')
        self._invert_btn.style().unpolish(self._invert_btn)
        self._invert_btn.style().polish(self._invert_btn)

    def _undo(self):
        if self._shapes:
            self._shapes.pop()
            self.update()

    # ---------- 绘制 ----------

    def paintEvent(self, e):
        p = QPainter(self)
        for rect, pm, _d in self._screens:
            p.drawPixmap(rect, pm)
        p.fillRect(self.rect(), MASK_COLOR)
        if self._sel.isValid() and not self._sel.isNull():
            # 选区镂空：把底图在选区内再画一遍（盖住灰罩），再画标注
            p.save()
            p.setClipRect(self._sel)
            for rect, pm, _d in self._screens:
                p.drawPixmap(rect, pm)
            p.setRenderHint(QPainter.Antialiasing)
            for sh in self._shapes:
                self._draw_shape(p, sh)
            if self._cur:
                self._draw_shape(p, self._cur)
            p.restore()
            p.setPen(QPen(QColor(self.pal['sel']), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(self._sel).adjusted(0.5, 0.5, -0.5, -0.5))
            if self._mode == 'ready' and self._long is None:
                p.setBrush(QColor(self.pal['handle_bg']))
                for h in HANDLES:
                    p.drawRect(self._handle_rect(h))
        p.end()

    def _draw_shape(self, p, sh):
        col = QColor(sh['color'])
        if sh['kind'] in ('rect', 'ellipse'):
            p.setPen(QPen(col, sh['w'], Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            if sh['kind'] == 'rect':
                p.drawRect(sh['rect'])
            else:
                p.drawEllipse(sh['rect'])
        else:
            f = QFont(self._cn)
            f.setPixelSize(TEXT_PX[sh['size']])
            p.setFont(f)
            fm = QFontMetrics(f)
            text = sh['text']
            w = fm.horizontalAdvance(text)
            pos = sh['pos']          # 文字外框左上角
            if sh['invert']:
                pad, rad = 5.0, 4.0
                r = QRectF(pos.x() - pad, pos.y() - pad, w + pad * 2, fm.height() + pad * 2)
                path = QPainterPath()
                path.addRoundedRect(r, rad, rad)
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawPath(path)
                p.setPen(QColor(_contrast(sh['color'])))
            else:
                # 亮色文字垫一层错位暗影，压在亮内容上也可读
                if _contrast(sh['color']) == '#1a1610':
                    p.setPen(QColor(0, 0, 0, 170))
                    p.drawText(QPointF(pos.x() + 1, pos.y() + fm.ascent() + 1), text)
                p.setPen(col)
            p.drawText(QPointF(pos.x(), pos.y() + fm.ascent()), text)

    def _handle_rect(self, h):
        s = ui.sc(7)
        r = self._sel
        xm = {'w': r.left(), 'e': r.right(), 'n': r.center().x(), 's': r.center().x()}
        ym = {'n': r.top(), 's': r.bottom(), 'w': r.center().y(), 'e': r.center().y()}
        if len(h) == 2:
            x = xm[h[1]]   # nw/ne/sw/se：x 由 w/e 段定，y 由 n/s 段定
            y = ym[h[0]]
        else:
            x = xm[h]      # n/s/e/w：另一轴取中线
            y = ym[h]
        return QRect(int(x - s / 2), int(y - s / 2), s, s)

    def _hit_handle(self, pos):
        if self._mode != 'ready':
            return None
        grow = ui.sc(5)
        for h in HANDLES:
            if self._handle_rect(h).adjusted(-grow, -grow, grow, grow).contains(pos):
                return h
        return None

    # ---------- 鼠标 ----------

    def mousePressEvent(self, e):
        if self._long is not None:
            return
        pos = e.pos()
        if e.button() == Qt.RightButton:
            if self._editor:
                self._cancel_editor()
            elif self._mode == 'ready':
                self._reset_sel()
            else:
                self._cancel()
            return
        if e.button() != Qt.LeftButton:
            return
        if self._editor:
            self._commit_editor()
        if self._mode == 'ready':
            h = self._hit_handle(pos)
            if h:
                self._drag = ('resize', (h, self._fixed_point(h)))
                return
            if self._tool and self._sel.contains(pos):
                if self._tool == 'text':
                    self._open_editor(pos)
                else:
                    self._cur = {'kind': self._tool, 'rect': QRectF(QPointF(pos), QPointF(pos)),
                                 'color': self._color, 'w': SHAPE_W[self._size]}
                    self._drag = ('draw', QPointF(pos))
                return
            if self._sel.contains(pos):
                self._drag = ('move', pos - self._sel.topLeft())
                return
        # 空闲或点在选区外：重新框选（旧标注随旧选区一起作废）
        self._shapes = []
        self._cur = None
        self._sel = QRect(pos, QSize(0, 0))
        self._mode = 'creating'
        self._drag = ('create', pos)
        self._update_chrome()
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.pos()
        if self._drag is None:
            self._update_cursor(QCursor.pos())
            return
        kind, data = self._drag
        if kind == 'create':
            self._sel = QRect(data, pos).normalized()
        elif kind == 'move':
            tl = pos - data
            tl.setX(min(max(tl.x(), 0), max(0, self.width() - self._sel.width())))
            tl.setY(min(max(tl.y(), 0), max(0, self.height() - self._sel.height())))
            self._sel = QRect(tl, self._sel.size())
        elif kind == 'resize':
            h, fixed = data
            self._sel = self._resized(h, fixed, pos)
        elif kind == 'draw':
            self._cur['rect'] = QRectF(data, QPointF(pos)).normalized()
        self._update_chrome()
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._drag is None:
            return
        kind, _d = self._drag
        self._drag = None
        if kind == 'create':
            if self._sel.width() < MIN_SEL or self._sel.height() < MIN_SEL:
                self._sel = QRect()
                self._mode = 'idle'
            else:
                self._mode = 'ready'
        elif kind == 'draw' and self._cur:
            r = self._cur['rect']
            if r.width() >= 3 and r.height() >= 3:
                self._shapes.append(self._cur)
            self._cur = None
        self._update_chrome()
        self.update()

    def _fixed_point(self, h):
        r = self._sel
        fx = r.right() if 'w' in h else (r.left() if 'e' in h else r.center().x())
        fy = r.bottom() if 'n' in h else (r.top() if 's' in h else r.center().y())
        return QPoint(fx, fy)

    def _resized(self, h, fixed, pos):
        if len(h) == 2:
            return QRect(fixed, pos).normalized()
        r = QRect(self._sel)
        if h == 'n':
            r.setTop(min(pos.y(), r.bottom() - MIN_SEL))
        elif h == 's':
            r.setBottom(max(pos.y(), r.top() + MIN_SEL))
        elif h == 'w':
            r.setLeft(min(pos.x(), r.right() - MIN_SEL))
        else:
            r.setRight(max(pos.x(), r.left() + MIN_SEL))
        return r

    def _update_cursor(self, gpos):
        pos = self.mapFromGlobal(gpos)
        h = self._hit_handle(pos)
        if h in ('nw', 'se'):
            cur = Qt.SizeFDiagCursor
        elif h in ('ne', 'sw'):
            cur = Qt.SizeBDiagCursor
        elif h in ('n', 's'):
            cur = Qt.SizeVerCursor
        elif h in ('e', 'w'):
            cur = Qt.SizeHorCursor
        elif self._tool == 'text' and self._mode == 'ready' and self._sel.contains(pos):
            cur = Qt.IBeamCursor
        elif self._mode == 'ready' and self._sel.contains(pos) and not self._tool:
            cur = Qt.SizeAllCursor
        else:
            cur = Qt.CrossCursor
        self.setCursor(cur)

    # ---------- 键盘 ----------

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Escape:
            self._cancel()
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            if self._mode == 'ready':
                self._finish_copy()
        elif k == Qt.Key_Z and e.modifiers() & Qt.ControlModifier:
            self._undo()
        else:
            super(ShotOverlay, self).keyPressEvent(e)

    def showEvent(self, e):
        super(ShotOverlay, self).showEvent(e)
        self.activateWindow()
        self.raise_()
        self.grabKeyboard()   # 全屏 Tool 窗不一定有焦点，Esc/Enter/Ctrl+Z 靠抢键盘保证

    def closeEvent(self, e):
        self.releaseKeyboard()
        super(ShotOverlay, self).closeEvent(e)

    # ---------- 文字工具 ----------

    def _open_editor(self, pos):
        ed = QLineEdit(self)
        f = QFont(self._cn)
        f.setPixelSize(TEXT_PX[self._size])
        ed.setFont(f)
        if self._invert:
            ed.setStyleSheet('QLineEdit { background: %s; color: %s; border: none;'
                             ' border-radius: 3px; padding: 2px 5px; }'
                             % (self._color, _contrast(self._color)))
        else:
            ed.setStyleSheet('QLineEdit { background: rgba(0,0,0,50); color: %s; border: none;'
                             ' border-radius: 3px; padding: 2px 5px; }' % self._color)
        fm = QFontMetrics(f)
        w, h = ui.sc(200), fm.height() + 6
        x = min(max(pos.x(), self._sel.left()), max(self._sel.left(), self._sel.right() - w))
        y = min(max(pos.y(), self._sel.top()), max(self._sel.top(), self._sel.bottom() - h))
        ed.setGeometry(x, y, w, h)
        ed.installEventFilter(self)
        self._editor = (ed, QPointF(x, y))
        ed.show()
        ed.setFocus()

    def _commit_editor(self):
        if not self._editor:
            return
        ed, pos = self._editor
        self._editor = None
        text = ed.text().strip()
        ed.removeEventFilter(self)
        ed.close()
        ed.deleteLater()
        if text:
            self._shapes.append({'kind': 'text', 'pos': pos, 'text': text,
                                 'color': self._color, 'size': self._size,
                                 'invert': self._invert})
        self.update()

    def _cancel_editor(self):
        if not self._editor:
            return
        ed, _pos = self._editor
        self._editor = None
        ed.removeEventFilter(self)
        ed.close()
        ed.deleteLater()

    def eventFilter(self, obj, ev):
        if self._editor and obj is self._editor[0]:
            if ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
                self._cancel_editor()
                return True
            if ev.type() == QEvent.FocusOut:
                self._commit_editor()
                return True
        return super(ShotOverlay, self).eventFilter(obj, ev)

    # ---------- 工具条摆位 ----------

    def _update_chrome(self):
        if self._mode != 'ready':
            self.bar.hide()
            self.sub.hide()
            self.size_label.hide()
            return
        r = self._sel
        self.size_label.setText('%d × %d' % (r.width(), r.height()))
        self.size_label.adjustSize()
        lx = min(r.left(), self.width() - self.size_label.width())
        ly = r.top() - self.size_label.height() - ui.sc(6)
        if ly < 0:
            ly = r.top() + ui.sc(6)
        self.size_label.move(max(0, lx), ly)
        self.size_label.show()

        show_sub = self._tool in ('rect', 'ellipse', 'text')
        self.bar.adjustSize()
        self.sub.adjustSize()
        bw, bh = self.bar.width(), self.bar.height()
        sub_h = self.sub.height() if show_sub else 0
        bx = min(max(r.right() - bw, 0), max(0, self.width() - bw))
        by = r.bottom() + ui.sc(8)
        if by + bh + (sub_h + ui.sc(6) if show_sub else 0) > self.height():
            by = r.top() - bh - ui.sc(8) - (sub_h + ui.sc(6) if show_sub else 0)
        if by < 0:
            by = max(0, r.bottom() - bh - ui.sc(8))   # 贴边选区：收进选区内右下角
        self.bar.move(bx, by)
        self.bar.show()
        if show_sub:
            if by > r.bottom():
                sy = by + bh + ui.sc(6)
            else:
                sy = by - sub_h - ui.sc(6)
            sx = min(max(r.right() - self.sub.width(), 0), max(0, self.width() - self.sub.width()))
            self.sub.move(sx, max(0, sy))
            self.sub.show()
        else:
            self.sub.hide()

    # ---------- 导出与收尾 ----------

    def _global_sel(self):
        return QRect(self._tl + self._sel.topLeft(), self._sel.size())

    def _result_image(self):
        """选区（含标注）矢量重绘成图：dpr 取覆盖屏幕的最大值，保证高清屏导出清晰。"""
        dpr = 1.0
        for rect, _pm, d in self._screens:
            if rect.intersects(self._sel):
                dpr = max(dpr, d)
        img = QImage(QSize(max(1, int(self._sel.width() * dpr + 0.5)),
                           max(1, int(self._sel.height() * dpr + 0.5))), QImage.Format_ARGB32)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(-QPointF(self._sel.topLeft()))
        for rect, pm, _d in self._screens:
            p.drawPixmap(rect, pm)
        for sh in self._shapes:
            self._draw_shape(p, sh)
        p.end()
        return img

    def _finish_copy(self):
        if self._editor:
            self._commit_editor()
        if not (self._mode == 'ready' and self._sel.isValid()):
            return
        QApplication.clipboard().setImage(self._result_image())
        self._close()

    def _finish_save(self):
        if self._editor:
            self._commit_editor()
        if not (self._mode == 'ready' and self._sel.isValid()):
            return
        img = self._result_image()
        self.hide()   # 置顶遮罩不收起，文件对话框会被压在下面
        path, _f = QFileDialog.getSaveFileName(None, '保存截图', self._default_name(),
                                               'PNG 图片 (*.png)')
        if path:
            img.save(path)
        self._close()

    def _finish_pin(self):
        if self._editor:
            self._commit_editor()
        if not (self._mode == 'ready' and self._sel.isValid()):
            return
        pinshot.pin(self._result_image(), self._global_sel().topLeft(), self.pal['sel'])
        self._close()

    def _default_name(self):
        return '截图_%s.png' % datetime.now().strftime('%Y%m%d_%H%M%S')

    def _reset_sel(self):
        self._sel = QRect()
        self._shapes = []
        self._cur = None
        self._mode = 'idle'
        self._update_chrome()
        self.update()

    def _cancel(self):
        self._close()

    def _close(self):
        if self._long is not None:
            self._stop_long(save=False)
        self.finished.emit()
        self.close()

    # ---------- 截长图 ----------

    def _start_long(self):
        """进入长图模式：锁选区、藏遮罩，用户自己滚动页面，定时器抓帧纵向拼接。"""
        if self._editor:
            self._commit_editor()
        if not (self._mode == 'ready' and self._sel.isValid()):
            return
        g = self._global_sel()
        scr = QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()
        self._long = {'screen': scr, 'chunks': [], 'prev_img': None, 'prev_sig': None,
                      'stall': 0, 'bad': 0, 'timer': QTimer(self)}
        self.hide()   # 遮罩自身盖在屏幕上，抓帧前必须藏起来
        bar = _LongBar(_qss(self.pal, self._cn, self._num))
        bar.done.connect(lambda: self._stop_long(save=True))
        bar.canceled.connect(lambda: self._stop_long(save=False))
        bar.adjustSize()
        vg = self.geometry()
        bx = min(max(g.right() - bar.width(), vg.left()),
                 max(vg.left(), vg.right() - bar.width() + 1))
        by = g.bottom() + ui.sc(8)
        if by + bar.height() > vg.bottom() + 1:
            by = g.top() - bar.height() - ui.sc(8)
        bar.move(bx, max(vg.top(), by))
        self._long['bar'] = bar
        bar.show()
        self._long['timer'].timeout.connect(self._long_tick)
        self._long['timer'].start(280)

    def _long_tick(self):
        L = self._long
        if L is None:
            return
        scr = L['screen']
        full = scr.grabWindow(0).toImage()
        dpr = scr.devicePixelRatio() or 1.0
        g = self._global_sel().translated(-scr.geometry().topLeft())
        px = QRect(int(g.x() * dpr + 0.5), int(g.y() * dpr + 0.5),
                   int(g.width() * dpr + 0.5), int(g.height() * dpr + 0.5))
        px = px.intersected(QRect(QPoint(0, 0), full.size()))
        if px.width() < 8 or px.height() < 8:
            return
        frame = full.copy(px)
        bar = L['bar']
        if L['prev_img'] is None:
            L['chunks'].append(frame)
            L['prev_img'] = frame
            L['prev_sig'] = _row_sig(frame)
            bar.set_status('已捕获首屏，向下滚动页面继续拼接')
            return
        sig = _row_sig(frame)
        s, d = _find_shift(L['prev_sig'], sig)
        shift = s * _SIG_ROW
        if 0 < shift < frame.height() and d <= 10:
            # 向下滚动了 shift 物理像素：帧的底部 shift 高是新内容，接上去
            L['chunks'].append(frame.copy(0, frame.height() - shift, frame.width(), shift))
            L['prev_img'] = frame
            L['prev_sig'] = sig
            L['stall'] = L['bad'] = 0
            total = sum(c.height() for c in L['chunks'])
            bar.set_status('已拼接约 %d px，继续滚动…' % int(total / dpr))
            if total >= LONG_MAX_H:
                bar.set_status('已到长度上限，自动完成')
                self._stop_long(save=True)
        elif d > 10:
            L['bad'] += 1
            if L['bad'] >= 3:
                bar.set_status('画面匹配不上：请缓慢匀速向下滚动（到底了就点 ✓ 完成）')
        else:
            L['stall'] += 1
            if L['stall'] >= 8:
                bar.set_status('画面未动：继续向下滚动，或点 ✓ 完成')

    def _stop_long(self, save):
        L = self._long
        if L is None:
            return
        self._long = None
        L['timer'].stop()
        L['bar'].close()
        if save and L['chunks']:
            dpr = L['screen'].devicePixelRatio() or 1.0
            w = L['chunks'][0].width()
            total = sum(c.height() for c in L['chunks'])
            img = QImage(w, total, QImage.Format_RGB32)
            p = QPainter(img)
            y = 0
            for c in L['chunks']:
                p.drawImage(0, y, c)
                y += c.height()
            p.end()
            img.setDevicePixelRatio(dpr)
            QApplication.clipboard().setImage(img)   # 完成即进剪贴板，保存可选
            path, _f = QFileDialog.getSaveFileName(None, '保存长图', self._default_name(),
                                                   'PNG 图片 (*.png)')
            if path:
                img.save(path)
        self._close()


# ---------------- 全局热键 ----------------

class _MSG(ctypes.Structure):
    _fields_ = [('hwnd', wintypes.HWND), ('message', wintypes.UINT),
                ('wParam', wintypes.WPARAM), ('lParam', wintypes.LPARAM),
                ('time', wintypes.DWORD), ('pt', wintypes.POINT)]

_WM_HOTKEY = 0x0312
_MOD_NOREPEAT = 0x4000

# Qt::Key → Win32 VK（字母/数字/F1-F12 同码或按公式换算，其余查表）
_QT_VK = {
    Qt.Key_Tab: 0x09, Qt.Key_Backspace: 0x08, Qt.Key_Return: 0x0D, Qt.Key_Enter: 0x0D,
    Qt.Key_Escape: 0x1B, Qt.Key_Space: 0x20, Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22,
    Qt.Key_End: 0x23, Qt.Key_Home: 0x24, Qt.Key_Left: 0x25, Qt.Key_Up: 0x26,
    Qt.Key_Right: 0x27, Qt.Key_Down: 0x28, Qt.Key_Print: 0x2C, Qt.Key_Insert: 0x2D,
    Qt.Key_Delete: 0x2E,
}


def _qt_to_win(keyval):
    """QKeySequence[0] 的 int（修饰键|键码）→ (win32 修饰, VK)。识别不了返回 (mods, None)。"""
    mods = 0
    if keyval & Qt.ShiftModifier:
        mods |= 0x0004
    if keyval & Qt.ControlModifier:
        mods |= 0x0002
    if keyval & Qt.AltModifier:
        mods |= 0x0001
    if keyval & Qt.MetaModifier:
        mods |= 0x0008
    key = keyval & 0x01FFFFFF
    if 0x41 <= key <= 0x5A or 0x30 <= key <= 0x39:   # A-Z / 0-9 与 VK 同码
        return mods, key
    if Qt.Key_F1 <= key <= Qt.Key_F12:
        return mods, 0x70 + (key - Qt.Key_F1)
    return mods, _QT_VK.get(key)


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, cb):
        super(_HotkeyFilter, self).__init__()
        self._cb = cb

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType in (b'windows_generic_MSG', b'windows_dispatcher_MSG'):
                msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
                if msg.message == _WM_HOTKEY:
                    self._cb()
        except Exception:
            pass
        return False, 0


class HotkeyManager(object):
    """截图全局热键：RegisterHotKey（用户态，不占钩子线程，HWND=None 走线程消息队列）。
    配置为空 = 不注册；apply() 可反复调，先注销旧的再注册新的。"""

    _ID = 0x5A01

    def __init__(self, qapp, on_trigger):
        self._on_trigger = on_trigger
        self._registered = False
        self._filter = _HotkeyFilter(self._fire)
        qapp.installNativeEventFilter(self._filter)

    def _fire(self):
        try:
            self._on_trigger()
        except Exception:
            pass   # 过滤器链不能断；真正的异常有 _debug_excepthook 兜底

    def apply(self, text):
        """按 QKeySequence 字符串重注册；返回错误文案（None = 注册成功或留空禁用）。"""
        if self._registered:
            _u32.UnregisterHotKey(None, self._ID)
            self._registered = False
        text = (text or '').strip()
        if not text:
            return None
        seq = QKeySequence(text)
        if seq.isEmpty() or seq.count() != 1:
            return '无法识别的快捷键'
        mods, vk = _qt_to_win(seq[0])
        if vk is None:
            return '无法识别的按键'
        # 裸键只放行 F1-F12 / PrintScreen，其余必须带修饰键，避免抢正常输入
        if not mods and not (0x70 <= vk <= 0x7B or vk == 0x2C):
            return '快捷键需要修饰键（Ctrl/Alt/Shift）'
        if not _u32.RegisterHotKey(None, self._ID, mods | _MOD_NOREPEAT, vk):
            return '快捷键被其他程序占用'
        self._registered = True
        return None

    def shutdown(self):
        if self._registered:
            _u32.UnregisterHotKey(None, self._ID)
            self._registered = False


# ---------------- 入口 ----------------

_active = []   # 进行中的会话：防止热键连按叠第二个遮罩


def start_session(cfg):
    """开一次截图会话；已在截图中则忽略。返回 ShotOverlay 或 None。"""
    if _active:
        try:
            if _active[0].isVisible():
                return None
        except RuntimeError:
            pass
    o = ShotOverlay(cfg)
    _active[:] = [o]
    o.finished.connect(lambda: _active.clear())
    o.show()
    return o
