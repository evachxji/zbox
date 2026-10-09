# -*- coding: utf-8 -*-
"""QQ 风格截图：全局热键 → 全屏灰罩 → 框选 → 标注 → 复制/保存/钉图/长图。

- 遮罩与标注全部自绘；工具条是遮罩窗的子控件，QSS 由 PALETTES 按面板主题
  （nocturne 深色磨砂 / mica 浅色磨砂）现拼，不进 themes.py 的面板 QSS 体系。
- 全局热键 HotkeyManager：ctypes RegisterHotKey + QAbstractNativeEventFilter 收
  WM_HOTKEY；配置为空 = 不注册；apply() 即时注销重注册。
- 截长图：灰罩不切走——选区外保持灰罩、选区留空透出活页面（抓帧抓合成屏，
  选区内画任何东西都会污染拼接帧）；自动滚动（PostMessageW 直投 WM_MOUSEWHEEL）
  驱动页面，滚轮被守卫全部吞掉只作调速；定时器抓选区帧、按行签名纵向拼接；
  ✓ 完成导出，Esc 退出（键盘钩子拦截）。
"""
import ctypes
import io
import os
import threading
import time
import traceback
from ctypes import wintypes
from datetime import datetime

from PySide6.QtCore import (Qt, QRect, QRectF, QPoint, QPointF, QSize, QTimer, QEvent,
                          Signal, QAbstractNativeEventFilter, QPropertyAnimation, QEasingCurve, Property)
from PySide6.QtGui import (QPainter, QColor, QPen, QPixmap, QImage, QFont, QFontMetrics,
                         QKeySequence, QPainterPath, QCursor, QGuiApplication, QIcon, QRegion)
from PySide6.QtWidgets import (QWidget, QApplication, QFrame, QHBoxLayout, QToolButton,
                             QLabel, QLineEdit, QPushButton, QFileDialog)

import app as ui          # sc / ui_scale / pick_fonts / resolve_theme
import pinshot
import sysutil

_u32 = ctypes.windll.user32
_u32.RegisterHotKey.restype = wintypes.BOOL
_u32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_u32.UnregisterHotKey.restype = wintypes.BOOL
_u32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_u32.PostMessageW.restype = wintypes.BOOL
_u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
_u32.GetTopWindow.restype = wintypes.HWND
_u32.GetWindow.restype = wintypes.HWND
_u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
_u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_u32.IsWindowVisible.argtypes = [wintypes.HWND]
_u32.IsWindowEnabled.argtypes = [wintypes.HWND]
_u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_u32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
_u32.ChildWindowFromPointEx.restype = wintypes.HWND
_u32.ChildWindowFromPointEx.argtypes = [wintypes.HWND, wintypes.POINT, wintypes.UINT]
_u32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, ctypes.c_size_t]
_u32.SetWindowsHookExW.restype = ctypes.c_void_p
_u32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_u32.CallNextHookEx.restype = wintypes.LPARAM
_u32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t]
_u32.GetMessageW.restype = ctypes.c_int
_u32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                    ctypes.c_size_t, ctypes.c_ssize_t]

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
        'sep': 'rgba(255,255,255,26)',
        'dot_ring': 'rgba(255,255,255,30)', 'dot_ring_on': '#e8a33d',
        'label_bg': 'rgba(27,29,36,235)', 'label_border': 'rgba(232,163,61,102)',
        'sel': '#e8a33d', 'handle_bg': '#1b1d24',
    },
    'mica': {
        'accent': '#0067c0', 'accent_text': '#ffffff', 'accent_soft': 'rgba(0,103,192,30)',
        'accent_border': 'rgba(0,103,192,115)', 'bar_solid': '#f7f8fa',
        'bar_bg': 'rgba(247,248,250,245)', 'bar_border': 'rgba(0,0,0,23)',
        'icon': '#8a8a90', 'icon_hov_bg': 'rgba(0,0,0,15)',
        'sep': 'rgba(0,0,0,30)',
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
QPushButton#shotGhost {
    background: transparent; border: 1px solid %(bar_border)s; border-radius: 6px;
    color: %(icon)s; font: 12px "%(cn)s"; padding: 0 12px;
}
QPushButton#shotGhost:hover { background: %(icon_hov_bg)s; }
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
""" % dict({'cn': cn, 'num': num}, **pal)


def _contrast(color):
    """反色文字的字色：色块亮则用深字，暗则用白字。"""
    c = QColor(color)
    lum = (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255.0
    return '#1a1610' if lum > 0.55 else '#ffffff'

# ---------------- 长图拼接：行签名匹配 ----------------

_SIG_ROW = 2      # 行签名每 2 行取一行
_SIG_COL = 4      # 行内每 4 列取一个像素
_SIG_BUCKETS = 8  # 行内分桶数（复核用）


def _row_sig(img):
    """灰度行签名：每 2 行取一行，算 (整行均值, 行内 8 桶均值)。
    列表页行高一致、配色相同，整行均值会周期性撞车；桶均值带横向分布，
    供 _find_shift 复核区分「真对齐」与「错开整数个行高」。"""
    g = img.convertToFormat(QImage.Format_Grayscale8)
    w, h = g.width(), g.height()
    bpl = g.bytesPerLine()
    buf = bytes(g.bits())   # PySide6 的 bits() 直接给带尺寸的 memoryview，转真 bytes 支持步长切片
    bw = max(1, w // _SIG_BUCKETS)
    sig = []
    for y in range(0, h, _SIG_ROW):
        row = buf[y * bpl:y * bpl + w]
        buckets = []
        for b in range(_SIG_BUCKETS):
            seg = row[b * bw:(b + 1) * bw if b + 1 < _SIG_BUCKETS else w:_SIG_COL]
            buckets.append(sum(seg) // max(1, len(seg)))
        sig.append((sum(buckets) // len(buckets), tuple(buckets)))
    return sig


def _find_shift(prev, cur):
    """prev 向下滚动后变成 cur：找位移 s（签名行数）使 prev[s:] 与 cur[:n-s] 最吻合。
    返回 (s, 复核灰度差)。差值大 = 画面动画/跳变，不可信。
    两阶段：整行均值粗筛出前 5 个候选位移，再用行内桶均值复核定案——
    只按整行均值会在列表页锁错对齐，把已拼内容当成新内容拼出重复段。
    搜索范围限制在半帧以内：滚动一 tick 超半帧本就拼不可靠，且大位移对应
    的重叠区只有几行，周期内容上零星星几行撞车就会拿满分骗过复核。"""
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
            for x in range(_SIG_BUCKETS):
                d += abs(pa[x] - ca[x])
                cnt += 1
        if cnt:
            scores.append((d / cnt, s))
    if not scores:
        return 0, 1e9
    best_d = min(d for d, _s in scores)
    # 同分取最小位移：重叠区越大越可信，周期内容撞出的次优对齐靠这条排掉
    best_s = min(s for d, s in scores if d <= best_d * 1.1 + 0.5)
    return best_s, best_d


# ---------------- 长图控制条 ----------------

class _LongBar(QWidget):
    """截长图模式的悬浮控制条：遮罩隐藏后它是会话唯一的可见 UI——
    「自动下滚」+「✓ 完成」，摆在选区底部（空间不够换顶部）；取消走 Esc（_WheelGuard 拦截）。"""

    done = Signal()
    canceled = Signal()
    auto_clicked = Signal()

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
        row.setContentsMargins(ui.sc(6), ui.sc(6), ui.sc(6), ui.sc(6))
        row.setSpacing(ui.sc(6))
        self._auto_btn = QPushButton('自动下滚')
        self._auto_btn.setObjectName('shotGhost')
        self._auto_btn.setFixedHeight(ui.sc(28))
        self._auto_btn.setCursor(Qt.PointingHandCursor)
        self._auto_btn.setFocusPolicy(Qt.NoFocus)
        self._auto_btn.setToolTip('自动匀速向下滚动；期间往回滚或点击截图区域即停')
        self._auto_btn.clicked.connect(self.auto_clicked)
        row.addWidget(self._auto_btn)
        ok = QPushButton('✓ 完成')
        ok.setObjectName('shotConfirm')
        ok.setFixedHeight(ui.sc(28))
        ok.setCursor(Qt.PointingHandCursor)
        ok.setFocusPolicy(Qt.NoFocus)
        ok.setToolTip('完成并复制到剪贴板 (Enter)')
        ok.clicked.connect(self.done)
        row.addWidget(ok)
        self.setStyleSheet(qss)

    def set_auto_on(self, on):
        self._auto_btn.setText('停止下滚' if on else '自动下滚')

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


class _LongChrome(QWidget):
    """截长图期间的全屏灰罩 + 取景框轮廓 + 缩略预览：纯展示（鼠标穿透、不抢焦点）。
    灰罩把选区裁剪留空，活页面直接透出——抓帧抓的是合成屏，选区内画任何东西都会
    污染拼接帧；轮廓描边外扩 2px 完全落在选区外；预览放选区右侧
    （放不下换左侧，两侧都放不下则不显示预览），顶到屏幕底边或完成按钮条顶边
    （按钮与缩略图不能互相遮挡，让不出空间就不显示预览）后截顶只展示最新部分。
    窗口几何固定（轮廓 ∪ 预览满高区域），延伸动画只 repaint 不动窗口——
    逐帧 setGeometry 会让分层窗口晃动。"""

    _TW = 160          # 预览宽（逻辑 px）
    _GAP = 8           # 预览与选区间距（逻辑 px）

    def __init__(self, sel_g, pal, avoid_g=None, vg=None, parent=None):
        super(_LongChrome, self).__init__(parent, Qt.FramelessWindowHint | Qt.Tool
                                          | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._pal = pal
        self._thumb = None       # 已拼接预览（物理 px，dpr 与本窗一致）
        self._ring_g = sel_g.adjusted(-2, -2, 2, 2)
        tw, gap = ui.sc(self._TW), ui.sc(self._GAP)
        scr = QGuiApplication.screenAt(sel_g.center()) or QGuiApplication.primaryScreen()
        sa = scr.availableGeometry()
        self._max_h = max(ui.sc(80), sa.bottom() - self._ring_g.top())   # 向下延伸到屏幕底边
        if sa.right() - sel_g.right() >= tw + gap:
            self._side = 'r'
        elif sel_g.left() - sa.left() >= tw + gap:
            self._side = 'l'
        else:
            self._side = None
        if self._side:
            x = (self._ring_g.right() + 1 + gap) if self._side == 'r' \
                else (self._ring_g.left() - gap - tw)
            if avoid_g is not None and avoid_g.intersects(QRect(x, self._ring_g.top(),
                                                                tw, self._max_h)):
                # 完成按钮条不能被缩略图遮挡：预览底边让到按钮条顶边之上
                self._max_h = avoid_g.top() - gap - self._ring_g.top()
                if self._max_h < ui.sc(60):
                    self._side = None   # 让完太小：不显示预览
        # 几何一次算死后不再变：全屏虚拟桌面（灰罩要罩住选区外所有区域）
        if vg is None:
            vg = QRect()
            for scr_ in QGuiApplication.screens():
                vg = vg.united(scr_.geometry())
        geo = QRect(vg)
        self._prev = None
        if self._side:
            self._prev = QRect(x, self._ring_g.top(), tw, self._max_h)
        self.setGeometry(geo)
        self._ring = self._ring_g.translated(-geo.topLeft())
        if self._prev is not None:
            self._prev = self._prev.translated(-geo.topLeft())
        self._cur_h = 0          # 当前展示高（动画驱动，平顺延伸到 _target_h）
        self._anim = QPropertyAnimation(self, b'disp_h', self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def append_chunk(self, chunk):
        """拼进来的新内容同步缩一份进预览。"""
        if self._side is None:
            return
        dpr = self.devicePixelRatio() or 1.0
        tw = max(8, int(ui.sc(self._TW) * dpr))
        part = chunk.scaledToWidth(tw, Qt.SmoothTransformation)
        if self._thumb is None:
            self._thumb = part
        else:
            img = QImage(tw, self._thumb.height() + part.height(), QImage.Format_RGB32)
            p = QPainter(img)
            p.drawImage(0, 0, self._thumb)
            p.drawImage(0, self._thumb.height(), part)
            p.end()
            self._thumb = img
        self._thumb.setDevicePixelRatio(dpr)
        target = self._target_h()
        if target != self._cur_h:
            self._anim.stop()
            self._anim.setStartValue(self._cur_h)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self.update()   # 已顶到屏幕底：高度不变，内容滚进最新部分

    def _target_h(self):
        """预览目标高（逻辑 px）：随内容向下延伸，顶到屏幕底边后截顶。"""

        if self._thumb is None:
            return 0
        dpr = self._thumb.devicePixelRatio() or 1.0
        return min(int(self._thumb.height() / dpr), self._max_h)

    def _get_disp(self):
        return self._cur_h

    def _set_disp(self, h):
        self._cur_h = h
        self.update()   # 只重绘，不动窗口几何

    disp_h = Property(int, _get_disp, _set_disp)

    def paintEvent(self, e):
        p = QPainter(self)
        # 选区外灰罩；选区留空透出活页面（抓帧区域，这里画任何东西都会入镜）
        p.setClipRegion(QRegion(self.rect()).subtracted(
            QRegion(self._ring.adjusted(2, 2, -2, -2))))
        p.fillRect(self.rect(), MASK_COLOR)
        p.setClipping(False)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(self._pal['sel']), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(self._ring).adjusted(1, 1, -1, -1))
        if self._prev is not None and self._thumb is not None and self._cur_h > 0:
            r = QRectF(self._prev.x(), self._prev.y(), self._prev.width(), self._cur_h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self._pal['bar_bg']))
            p.drawRoundedRect(r, 6, 6)
            dpr = self._thumb.devicePixelRatio() or 1.0
            full = self._thumb.height()
            src_h = min(int(self._cur_h * dpr), full)
            if full <= int(self._max_h * dpr):
                src = QRect(0, 0, self._thumb.width(), src_h)          # 生长期：顶对齐向下延伸
            else:
                src = QRect(0, full - src_h, self._thumb.width(), src_h)   # 顶到屏底：底对齐滚进新内容
            dst = self._prev.adjusted(1, 1, -1, -1)
            dst.setHeight(max(1, self._cur_h - 2))
            p.drawImage(dst, self._thumb, src)
            p.setPen(QPen(QColor(self._pal['bar_border']), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        p.end()



# ---------------- 截长图自动滚动 ----------------

_WM_MOUSEWHEEL = 0x020A
_MOUSEEVENTF_WHEEL = 0x0800
_WHEEL_MAGIC = 0x5A09     # 自补发事件的 dwExtraInfo 标记，钩子见到直接放行
_WHEEL_MAX = 120          # 手动期滚轮限速：令牌桶容量（一格）
_WHEEL_RATE = 400.0       # 令牌桶回补速度（delta/秒）≈ 一格/300ms，与 280ms 抓帧节奏匹配
_GWL_EXSTYLE = -20
_WS_EX_PASS_THROUGH = 0x00080020   # WS_EX_LAYERED | WS_EX_TRANSPARENT
_CWP_SKIP = 0x0007                 # CWP_SKIPINVISIBLE | SKIPDISABLED | SKIPTRANSPARENT


def _find_wheel_target(pt):
    """屏幕物理坐标 pt 处最上层的可滚窗口（借鉴 SnowShot 的 scrollinput.cpp）：
    沿 z 序跳过本进程窗口与 layered+transparent 穿透遮罩，再逐级下钻子窗口。"""
    hwnd = _u32.GetTopWindow(None)
    while hwnd:
        pid = wintypes.DWORD()
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rc = wintypes.RECT()
        styles = _u32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
        if (pid.value != os.getpid() and _u32.IsWindowVisible(hwnd)
                and _u32.IsWindowEnabled(hwnd)
                and (styles & _WS_EX_PASS_THROUGH) != _WS_EX_PASS_THROUGH
                and _u32.GetWindowRect(hwnd, ctypes.byref(rc))
                and rc.left <= pt.x() <= rc.right and rc.top <= pt.y() <= rc.bottom):
            break
        hwnd = _u32.GetWindow(hwnd, 2)   # GW_HWNDNEXT
    if not hwnd:
        return None
    for _ in range(16):   # 下钻子窗口，圈数兜底防异常窗口树
        cpt = wintypes.POINT(pt.x(), pt.y())
        if not _u32.ScreenToClient(hwnd, ctypes.byref(cpt)):
            break
        child = _u32.ChildWindowFromPointEx(hwnd, cpt, _CWP_SKIP)
        if not child or child == hwnd:
            break
        hwnd = child
    return hwnd


def _post_wheel(hwnd, pt, delta=-120):
    """向目标窗口投递一次滚轮消息：不动用户光标、不装全局钩子，滚速完全由我们控制。"""
    lp = ((pt.y() & 0xFFFF) << 16) | (pt.x() & 0xFFFF)
    return bool(_u32.PostMessageW(hwnd, _WM_MOUSEWHEEL, (delta & 0xFFFF) << 16, lp))




# ---------------- 截长图滚轮守卫 ----------------


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('pt', wintypes.POINT), ('mouseData', wintypes.DWORD),
                ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.c_size_t)]


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('vkCode', wintypes.DWORD), ('scanCode', wintypes.DWORD),
                ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.c_size_t)]


def _guard_log():
    """ctypes 回调不走 sys.excepthook，异常就地落盘（同 boxes.py 钩子的处置）。"""
    try:
        with io.open(os.path.join(sysutil.appdata_dir(), 'debug_due.log'),
                     'a', encoding='utf-8') as f:
            f.write('\n--- WheelGuard ---\n%s\n' % traceback.format_exc())
    except Exception:
        pass


class _WheelGuard(object):
    """截长图期间的输入守卫（WH_MOUSE_LL + WH_KEYBOARD_LL，仅截长图期间安装）：
    - 手动期（默认）：滚轮令牌桶限速（容量一格，~一格/300ms 回补）——
      滚得再快页面也只慢慢走（快了 280ms 一帧的签名匹配跟不上）；
      预算够原样放行（慢滚零延迟），超预算吞掉原事件按余量立即补发
      （即时补发不迟滞；自补发带 dwExtraInfo 标记放行）；
    - 自动下滚期：滚轮不滚页面（页面由 PostMessageW 驱动）——向下吞掉，
      向上吞掉并置 stop_auto（用户想接管）；点击落在截图区域内也置 stop_auto，
      点击本身放行；
    - Esc 拦截（WM_KEYDOWN 吞掉）：截长图是模态，Esc 立即退出整个截图会话。
      用户点进目标窗口后焦点在别人家，_LongBar 的抢键盘不可靠，钩子才兜得住。
    约束同 boxes.py 钩子教训：阻塞式 GetMessage 泵派发、回调绝不向外抛异常。"""

    _PROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int,
                               wintypes.WPARAM, wintypes.LPARAM)

    def __init__(self):
        self.manual = True       # 主线程维护：True = 手动期（滚轮限速）
        self._budget = float(_WHEEL_MAX)
        self._last_t = 0.0
        self.stop_auto = False   # 钩子线程置位（往回滚/点击截图区域），主线程消费
        self.esc = False         # Esc 标志（钩子线程置位，主线程消费）
        self.sel_phys = None     # 截图区域物理坐标 (l, t, r, b)，点击命中判定用
        self._hook = None
        self._khook = None
        self._tid = None
        self._cb = None          # 防 GC
        self._kcb = None
        self._ready = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(2)

    def stop(self):
        if self._tid:
            _u32.PostThreadMessageW(self._tid, 0x0012, 0, 0)   # WM_QUIT

    def _run(self):
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        self._cb = self._PROC(self._wheel_callback)
        self._hook = _u32.SetWindowsHookExW(14, self._cb, None, 0)      # WH_MOUSE_LL
        self._kcb = self._PROC(self._key_callback)
        self._khook = _u32.SetWindowsHookExW(13, self._kcb, None, 0)    # WH_KEYBOARD_LL
        self._ready.set()
        if not self._hook and not self._khook:
            return
        try:
            msg = wintypes.MSG()
            while _u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass   # LL 钩子回调靠本线程消息泵派发
        finally:
            if self._hook:
                _u32.UnhookWindowsHookEx(self._hook)
            if self._khook:
                _u32.UnhookWindowsHookEx(self._khook)
            self._hook = self._khook = self._tid = None

    def _throttle(self, amount, now=None):
        """令牌桶限速：返回本次允许放行的滚动量（delta）。容量一格，按速率回补。"""
        now = time.monotonic() if now is None else now
        self._budget = min(float(_WHEEL_MAX),
                           self._budget + (now - self._last_t) * _WHEEL_RATE)
        self._last_t = now
        take = min(amount, self._budget)
        self._budget -= take
        return int(round(take))

    def _wheel_callback(self, nCode, wParam, lParam):
        try:
            if nCode == 0 and wParam == _WM_MOUSEWHEEL:
                st = _MSLLHOOKSTRUCT.from_address(lParam)
                if st.dwExtraInfo != _WHEEL_MAGIC:
                    delta = ctypes.c_short(st.mouseData >> 16).value
                    if self.manual:
                        allow = self._throttle(abs(delta))
                        if allow < abs(delta):   # 超预算：吞掉原事件，按余量立即补发
                            if allow > 0:
                                emit = allow if delta > 0 else -allow
                                _u32.mouse_event(_MOUSEEVENTF_WHEEL, 0, 0,
                                                 emit & 0xFFFFFFFF, _WHEEL_MAGIC)
                            return 1
                    else:
                        if delta > 0:
                            self.stop_auto = True   # 往回滚：用户想接管
                        return 1   # 自动下滚期滚轮不滚页面
            elif nCode == 0 and wParam in (0x0201, 0x0204) and not self.manual:
                # 左/右键按下落在截图区域内：回退手动（点击本身放行给目标窗口）
                sp = self.sel_phys
                if sp is not None:
                    st = _MSLLHOOKSTRUCT.from_address(lParam)
                    if sp[0] <= st.pt.x <= sp[2] and sp[1] <= st.pt.y <= sp[3]:
                        self.stop_auto = True
        except Exception:
            _guard_log()
        return _u32.CallNextHookEx(None, nCode, wParam, lParam)

    def _key_callback(self, nCode, wParam, lParam):
        try:
            if nCode == 0 and wParam == 0x0100:   # WM_KEYDOWN
                if _KBDLLHOOKSTRUCT.from_address(lParam).vkCode == 0x1B:   # VK_ESCAPE
                    self.esc = True
                    return 1   # 吞掉：别让目标窗口也响应 Esc
        except Exception:
            _guard_log()
        return _u32.CallNextHookEx(None, nCode, wParam, lParam)


class ShotOverlay(QWidget):
    """全屏灰罩 + 框选 + 标注 + 工具条。构造时先抓屏再显示，遮罩不会入镜。"""

    finished = Signal()   # 会话结束（无论结果），入口用来清引用

    def __init__(self, cfg):
        super(ShotOverlay, self).__init__(None, Qt.FramelessWindowHint | Qt.Tool
                                          | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_AlwaysShowToolTips)   # 热键唤起时窗口常非活动，默认不弹 tooltip
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

        self._idle_timer = QTimer(self)   # 无框选兜底：灰罩晾着 IDLE_TIMEOUT_MS 自动退出
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._cancel)

        self._build_chrome()
        self._refresh_icons()
        self.setStyleSheet(_qss(self.pal, self._cn, self._num))

    IDLE_TIMEOUT_MS = 20000

    def _arm_idle_timer(self):
        """按当前状态校准兜底定时器：还在 idle（没框选出有效选区）就重新计时，
        已框选（ready）/ 进长图就销毁——成功框选后不再自动退出。"""
        if self._mode == 'idle' and self._long is None:
            self._idle_timer.start(self.IDLE_TIMEOUT_MS)
        else:
            self._idle_timer.stop()

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
        self._arm_idle_timer()
        self._update_chrome()
        self.update()

    def mouseDoubleClickEvent(self, e):
        if (e.button() == Qt.LeftButton and self._long is None
                and self._mode == 'ready' and self._sel.contains(e.pos())):
            self._finish_copy()

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
            if self._long is not None:
                self._stop_long(save=True)
            elif self._mode == 'ready':
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
        self._arm_idle_timer()

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
        self._arm_idle_timer()
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
        """进入长图模式：锁选区、本体藏起（灰罩由 _LongChrome 贴出）。默认用户手动滚轮（守卫限长），点「自动下滚」才自动滚。"""
        if self._editor:
            self._commit_editor()
        if not (self._mode == 'ready' and self._sel.isValid()):
            return
        g = self._global_sel()
        scr = QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()
        self._long = {'screen': scr, 'chunks': [], 'prev_img': None, 'prev_sig': None,
                      'timer': QTimer(self)}
        self.hide()   # 遮罩本体藏起（画的是冻结底图，留着会污染抓帧）；灰罩由 _LongChrome 贴出
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
        chrome = _LongChrome(g, self.pal, avoid_g=bar.geometry(), vg=vg)
        self._long['chrome'] = chrome
        chrome.show()   # 灰罩先上，完成按钮条后上才不会被罩住
        bar.show()
        guard = _WheelGuard()
        dpr = scr.devicePixelRatio() or 1.0
        # 守卫用物理坐标判定「点击落在截图区域内」（自动期回退手动的条件之一）
        guard.sel_phys = (int(g.left() * dpr), int(g.top() * dpr),
                          int(g.right() * dpr), int(g.bottom() * dpr))
        self._long['guard'] = guard
        guard.start()
        bar.auto_clicked.connect(self._toggle_auto)
        self._long['timer'].timeout.connect(self._long_tick)
        self._long['timer'].start(280)

    def _toggle_auto(self):
        """自动下滚开关：开 = 向选区中心下的窗口定时投递滚轮消息（借鉴 SnowShot，
        滚速固定拼接才可靠）；关 = 回手动（按钮/往回滚/点击截图区域都走这里）。"""
        L = self._long
        if L is None:
            return
        if 'auto' in L:
            L['auto'].stop()
            del L['auto']
            L['bar'].set_auto_on(False)
            L['guard'].manual = True
            return
        g = self._global_sel()
        dpr = L['screen'].devicePixelRatio() or 1.0
        pt = QPoint(int(g.center().x() * dpr), int(g.center().y() * dpr))
        target = _find_wheel_target(pt)
        if not target:
            return   # 找不到可滚窗口：保持手动
        auto = QTimer(self)
        auto.setInterval(320)
        auto.timeout.connect(lambda: self._auto_scroll_tick(target, pt))
        L['auto'] = auto
        auto.start()
        L['bar'].set_auto_on(True)
        L['guard'].manual = False

    def _auto_scroll_tick(self, target, pt):
        L = self._long
        if L is None:
            return
        if not _post_wheel(target, pt):
            self._toggle_auto()   # 目标窗口没了：回退手动

    def _long_tick(self):
        L = self._long
        if L is None:
            return
        guard = L.get('guard')
        if guard is not None:
            if guard.esc:   # 截长图期间 Esc = 立即退出整个截图会话
                self._stop_long(save=False)
                return
            if guard.stop_auto and 'auto' in L:   # 往回滚/点击截图区域 = 回退手动
                self._toggle_auto()
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
        if L['prev_img'] is None:
            L['chunks'].append(frame)
            L['chrome'].append_chunk(frame)
            L['prev_img'] = frame
            L['prev_sig'] = _row_sig(frame)
            return
        sig = _row_sig(frame)
        s, d = _find_shift(L['prev_sig'], sig)
        shift = s * _SIG_ROW
        if 0 < shift < frame.height() and d <= 10:
            # 向下滚动了 shift 物理像素：帧的底部 shift 高是新内容，接上去
            new = frame.copy(0, frame.height() - shift, frame.width(), shift)
            L['chunks'].append(new)
            L['chrome'].append_chunk(new)
            L['prev_img'] = frame
            L['prev_sig'] = sig
            total = sum(c.height() for c in L['chunks'])
            if total >= LONG_MAX_H:
                self._stop_long(save=True)
        # 匹配不上（动画/跳变/反向）与画面未动都只跳过本帧，不提示也不硬拼

    def _stop_long(self, save):
        L = self._long
        if L is None:
            return
        self._long = None
        L['timer'].stop()
        if L.get('auto'):
            L['auto'].stop()
        L['guard'].stop()
        L['bar'].close()
        L['chrome'].close()
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
            QApplication.clipboard().setImage(img)   # 完成即进剪贴板
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
_QT_VK = {int(k): v for k, v in _QT_VK.items()}   # PySide6 枚举哈希与 int 不等，统一 int 键


def _qt_to_win(keyval):
    """QKeySequence[0]（PySide6 起是 QKeyCombination，先转 int）→ (win32 修饰, VK)。
    识别不了返回 (mods, None)。"""
    keyval = keyval.toCombined() if hasattr(keyval, 'toCombined') else int(keyval)
    mods = 0
    if keyval & Qt.ShiftModifier.value:
        mods |= 0x0004
    if keyval & Qt.ControlModifier.value:
        mods |= 0x0002
    if keyval & Qt.AltModifier.value:
        mods |= 0x0001
    if keyval & Qt.MetaModifier.value:
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
            prev = _active[0]
            if prev.isVisible() or prev._long is not None:
                prev._cancel()   # 截图中再按热键 = 退出截图（热键走线程消息队列，
                return None      # 即便遮罩输入被模态挡住，nativeEventFilter 照样能收到）
        except RuntimeError:
            pass
    # 应用级模态弹窗（exec() 的 QDialog：cookie 引导 / 关于 / 传输与视频说明窗等）
    # 开着时直接盖全屏遮罩 = 死锁：Qt 模态过滤把遮罩的键鼠事件全部吃掉
    # （grabKeyboard 也救不了），弹窗又被遮罩挡住点不到，Esc 进不来，只能杀进程。
    # 进截图前先把模态弹窗关掉——QDialog.close() = reject，弹窗按「取消」正常收尾。
    # exec() 的模态状态要等事件循环回卷才解除，activeModalWidget() 可能仍返回
    # 刚关掉的弹窗，用 closed 集合防死循环；嵌套模态每层关一次。
    closed = set()
    while True:
        mw = QApplication.activeModalWidget()
        if mw is None or id(mw) in closed:
            break
        closed.add(id(mw))
        mw.close()
    o = ShotOverlay(cfg)
    _active[:] = [o]
    o.finished.connect(lambda: _active.clear())
    o.show()
    return o
