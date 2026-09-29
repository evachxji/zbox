# -*- coding: utf-8 -*-
"""Zviber 桌面悬浮面板：日历 + 待办。PyQt5，兼容 Win7/10/11、Python 3.8+。"""
import ctypes
import json
import os
import sys
from datetime import date, datetime, timedelta

from PyQt5.QtCore import (Qt, QTimer, QSize, QPoint, QPointF, QRectF, QDate, QTime, QUrl,
                          pyqtSignal, QEvent, QPropertyAnimation, QEasingCurve)
from PyQt5.QtGui import (QFont, QFontDatabase, QPainter, QColor, QPixmap, QIcon, QPainterPath,
                         QRegion, QPen, QLinearGradient, QDesktopServices)
from PyQt5.QtWidgets import (QWidget, QFrame, QLabel, QToolButton, QVBoxLayout, QHBoxLayout,
                             QGridLayout, QStackedLayout, QListWidget,
                             QListWidgetItem, QLineEdit, QMenu, QApplication, QDialog,
                             QFormLayout, QCheckBox, QRadioButton, QPushButton, QCalendarWidget)

import calendar_data as cd
import sysutil
from themes import THEMES, THEME_ORDER, THEME_CHOICES, AUTO, build_qss

SHADOW = 0  # 不透明窗口：无边距，圆角由 DWM/遮罩实现
SINGLE_W, DUAL_W, PANEL_H = 344, 700, 428


_UI_SCALE = None


def ui_scale():
    """系统 DPI 缩放比（125% → 1.25）。设计尺寸按 100% 基准，运行时放大到物理像素。"""
    global _UI_SCALE
    if _UI_SCALE is None:
        try:
            _UI_SCALE = ctypes.windll.user32.GetDpiForSystem() / 96.0
        except Exception:
            _UI_SCALE = 1.0
        _UI_SCALE = max(0.75, min(_UI_SCALE, 3.0))
    return _UI_SCALE


def sc(v):
    return int(round(v * ui_scale()))


def pick_fonts():
    fams = set(QFontDatabase().families())
    cn = next((f for f in ['Microsoft YaHei UI', 'Microsoft YaHei', 'SimHei', 'SimSun'] if f in fams), 'sans-serif')
    num = next((f for f in ['Segoe UI Variable Text', 'Bahnschrift', 'Segoe UI', 'Consolas'] if f in fams), cn)
    return cn, num


def make_icon(sizes=(16, 24, 32, 48, 64)):
    """托盘/菜单图标：深靛底 + 白色横杠 + 琥珀斜杠的极简 Z"""
    icon = QIcon()
    for s in sizes:       # 逐尺寸矢量绘制，托盘小尺寸不糊
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(s / 64.0, s / 64.0)      # 设计稿基于 64x64 虚拟坐标
        bg = QLinearGradient(0, 0, 64, 64)
        bg.setColorAt(0, QColor('#262b45'))
        bg.setColorAt(1, QColor('#161a2b'))
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(2, 2, 60, 60), 15, 15)
        p.setPen(QPen(QColor('#f5f6fa'), 5.5, Qt.SolidLine, Qt.FlatCap))
        p.drawLine(QPointF(18, 20), QPointF(46, 20))
        p.drawLine(QPointF(18, 44), QPointF(46, 44))
        g = QLinearGradient(46, 20, 18, 44)   # 斜杠：琥珀渐变
        g.setColorAt(0, QColor('#ffc531'))
        g.setColorAt(1, QColor('#ff7a18'))
        pen = QPen(QColor('#f5f6fa'), 5.5, Qt.SolidLine, Qt.FlatCap)
        pen.setBrush(g)
        p.setPen(pen)
        p.drawLine(QPointF(46, 20), QPointF(18, 44))
        p.end()
        icon.addPixmap(pm)
    return icon




def _indicator_icons():
    """设置窗口 checkbox 对勾 / radio 圆点：矢量绘制到运行数据目录供 QSS image 引用
    （QSS 的 data URI 支持不稳定，文件路径最可靠）。每次启动重绘，DPI 变化尺寸自动跟随。"""
    scale = ui_scale()
    box = sc(13)                       # 与 QSS 中 indicator 边长一致
    d = os.path.join(sysutil.appdata_dir(), 'icons')
    os.makedirs(d, exist_ok=True)
    for name, kind, color in (('tick_dark', 'tick', '#1a1610'), ('tick_light', 'tick', '#ffffff'),
                              ('dot_dark', 'dot', '#e8a33d'), ('dot_light', 'dot', '#0067c0')):
        pm = QPixmap(int(round(box * scale)), int(round(box * scale)))
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        if kind == 'tick':
            pen = QPen(QColor(color))
            pen.setWidthF(box * 0.16)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawLine(QPointF(box * 0.24, box * 0.56), QPointF(box * 0.44, box * 0.74))
            p.drawLine(QPointF(box * 0.44, box * 0.74), QPointF(box * 0.80, box * 0.28))
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(QPointF(box / 2.0, box / 2.0), box * 0.26, box * 0.26)
        p.end()
        pm.save(os.path.join(d, name + '.png'))
    return d.replace('\\', '/')


DUE_ICON_COLORS = {'nocturne': '#8d8a82', 'mica': '#8a8a90'}
ACCENT_COLORS = {'nocturne': '#e8a33d', 'mica': '#0067c0'}   # 与主题强调色一致（同 _indicator_icons）

# 固定按钮三档：0 未固定（可拖动、置顶）→ 1 钉在桌面（不可移动、可被覆盖）→ 2 始终置顶（不可移动）
PIN_TIPS = (
    '未固定（可拖动）\n点击：钉在桌面，不可移动、可被其它窗口覆盖',
    '已钉在桌面（不可移动、可被其它窗口覆盖）\n点击：始终显示在最上层',
    '已始终置顶（不可移动）\n点击：取消固定',
)


def make_cal_icon(color):
    """编辑器右侧的日历小图标（emoji 在 Win7 上不可靠，直接画）。"""
    s = sc(16)
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.0, 1.3 * ui_scale()))
    p.setPen(pen)
    m = s / 16.0
    p.drawRoundedRect(QRectF(2 * m, 3 * m, 12 * m, 11 * m), 2 * m, 2 * m)
    p.drawLine(QPointF(2 * m, 6.5 * m), QPointF(14 * m, 6.5 * m))
    p.drawLine(QPointF(5.5 * m, 1.5 * m), QPointF(5.5 * m, 4.5 * m))
    p.drawLine(QPointF(10.5 * m, 1.5 * m), QPointF(10.5 * m, 4.5 * m))
    p.end()
    return QIcon(pm)


def make_clock_icon(color):
    """时间框右侧的时钟小图标（对齐 make_cal_icon 的画法，emoji 在 Win7 上不可靠）。"""
    s = sc(16)
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.0, 1.3 * ui_scale()))
    p.setPen(pen)
    m = s / 16.0
    p.drawEllipse(QRectF(2 * m, 2 * m, 12 * m, 12 * m))
    p.drawLine(QPointF(8 * m, 8 * m), QPointF(8 * m, 4.8 * m))    # 分针
    p.drawLine(QPointF(8 * m, 8 * m), QPointF(11 * m, 9.6 * m))   # 时针
    p.end()
    return QIcon(pm)


def make_pin_icon(color, filled=False):
    """固定按钮的图钉（画法对齐 make_cal_icon）：空心 = 钉在桌面，实心 = 始终置顶。"""
    s = sc(16)
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    col = QColor(color)
    m = s / 16.0
    pen = QPen(col)
    pen.setWidthF(max(1.0, 1.3 * ui_scale()))
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    head = QRectF(4 * m, 3 * m, 8 * m, 3 * m)        # 钉帽
    body = QRectF(6 * m, 6 * m, 4 * m, 3.5 * m)      # 钉身
    p.setBrush(col if filled else Qt.NoBrush)
    p.drawRoundedRect(head, 1 * m, 1 * m)
    p.drawRoundedRect(body, 0.8 * m, 0.8 * m)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(8 * m, 9.5 * m), QPointF(8 * m, 13 * m))   # 针尖
    p.end()
    return QIcon(pm)


def fmt_due_date(d):
    """截止日期统一显示成 M-d（如 10-9）：行内 tag 与编辑器按钮共用这一处格式，避免两边不一致。"""
    return '%d-%d' % (d.month, d.day)


def due_chip(due_str):
    """截止日期 -> (标签文本, 是否逾期)。
    一周内报还剩天数、逾期报逾期天数、今天报今天，更远只报日期。"""
    try:
        d = datetime.strptime(due_str, '%Y-%m-%d').date()
    except Exception:
        return None, False
    delta = (d - date.today()).days
    if delta < 0:
        return ('逾期 %d 天' % -delta, True)
    if delta == 0:
        return ('今天', False)
    if delta <= 7:
        return ('还剩 %d 天' % delta, False)
    return (fmt_due_date(d), False)


class Config(object):
    def __init__(self, path):
        self.path = path
        self.data = {'theme': THEME_ORDER[0], 'dual': False, 'tab': 0, 'pos': None, 'pin': 0,
                     'off_noon': '12:00-13:00', 'off_evening': '18:00'}
        self.load()

    def load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                self.data.update(json.load(f))
        except Exception:
            pass
        if self.data.get('theme') not in THEME_CHOICES:
            self.data['theme'] = THEME_ORDER[0]

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False)
        except Exception:
            pass

    def __getattr__(self, k):
        return self.data.get(k)

    def set(self, k, v):
        self.data[k] = v
        self.save()


def resolve_theme(key):
    """用户选择 → 实际主题名：auto 跟随系统「应用模式」（浅色用 mica，深色用 nocturne）。"""
    if key == AUTO:
        return 'mica' if sysutil.system_uses_light_theme() else 'nocturne'
    return key


# ---------------- 日历 ----------------

# 日历数字字体：Qt 用 pixelSize + weight 精确控制，对齐 Win11 日历（字形高 21px / Medium）
_NUM_FONT = {'name': None, 'size': 19, 'weight': 50}


def set_num_font(name):
    _NUM_FONT['name'] = name


class _CornerBadge(QWidget):
    """休息日角标：贴格子右上角的直角三角形（仿 Excel 批注标记）。
    形状用 QPainter 画，颜色取主题 QSS 给的 color —— QSS 的 border / 渐变都画不出可靠的三角。"""

    def __init__(self, parent=None):
        super(_CornerBadge, self).__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, e):
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.moveTo(0, 0)
        path.lineTo(w, 0)
        path.lineTo(w, h)
        path.closeSubpath()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillPath(path, self.palette().color(self.foregroundRole()))


class DayCell(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super(DayCell, self).__init__(parent)
        self.setObjectName('dayCell')
        self.date = None
        self.num = QLabel(self)
        self.num.setObjectName('dayNum')
        self.num.setAlignment(Qt.AlignCenter)
        self.num.setFixedSize(sc(38), sc(38))
        if _NUM_FONT['name']:
            f = QFont(_NUM_FONT['name'])
            f.setPixelSize(sc(_NUM_FONT['size']))
            f.setWeight(_NUM_FONT['weight'])
            self.num.setFont(f)
        self.sub = QLabel(self)
        self.sub.setObjectName('daySub')
        self.sub.setAlignment(Qt.AlignCenter)
        self.badge = _CornerBadge(self)
        self.badge.setObjectName('badge')
        self.badge.setFixedSize(sc(7), sc(7))
        self.badge.hide()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, sc(2), 0, sc(2))
        lay.setSpacing(0)
        lay.addStretch(1)
        lay.addWidget(self.num, 0, Qt.AlignHCenter)
        lay.addWidget(self.sub, 0, Qt.AlignHCenter)
        lay.addStretch(1)
        for w in (self.num, self.sub, self.badge):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)  # 点击穿透到格子本身

    def resizeEvent(self, e):
        super(DayCell, self).resizeEvent(e)
        w = self.badge.width()
        self.badge.setGeometry(self.width() - w, 0, w, w)  # 贴右上角：Excel 批注标记的位置

    def set_day(self, d, dim, store, sel=False):
        today = date.today()
        self.date = d
        self.setProperty('dim', 'true' if dim else 'false')
        self.setProperty('sel', 'true' if sel else 'false')
        self.setProperty('we', 'true' if d.weekday() >= 5 else 'false')
        self.setProperty('today', 'true' if d == today else 'false')
        self.num.setText(str(d.day))
        name, kind = store.info(d)
        show_name = name if kind == 'off' else None  # 调休班日不显示“班”，只显示农历
        fest = bool(show_name or cd.festival_name(d))
        self.sub.setText(show_name or cd.lunar_text(d))
        self.sub.setProperty('fest', 'true' if fest else 'false')
        # 红点 = 休息日：法定节假日，或非调休的双休日；调休上班日（班）不标
        off = (kind == 'off') or (d.weekday() >= 5 and kind != 'work')
        if off:
            self.badge.setProperty('kind', 'off')
            self.badge.show()
        else:
            self.badge.hide()
        for w in (self, self.num, self.sub, self.badge):
            w.style().unpolish(w)
            w.style().polish(w)


def _page_pixmap(page):
    """抓取页面为透明底位图。QWidget.grab() 对非半透明控件会用调色板底色（浅色）填充，
    深色主题下平移时会闪白，所以手动预填透明再 render。"""
    dpr = page.devicePixelRatioF()
    pm = QPixmap(page.size() * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    page.setAttribute(Qt.WA_TranslucentBackground)  # 否则 render 按不透明控件填系统底色
    page.render(pm)
    page.setAttribute(Qt.WA_TranslucentBackground, False)
    return pm


class _GridViewport(QWidget):
    """日历网格视口：裁剪滑动中的月页面。平移期间改画页面位图缓存，
    每帧只 blit 三张图（亚毫秒），避免 126 个 QSS 格子逐帧重绘。"""

    def __init__(self, parent=None):
        super(_GridViewport, self).__init__(parent)
        self.on_resize = None
        self.pixmaps = None  # {页序: QPixmap}；None = 显示活页面（可悬停/点击）
        self.pan_off = 0.0

    def paintEvent(self, e):
        if self.pixmaps is None:
            super(_GridViewport, self).paintEvent(e)
            return
        p = QPainter(self)
        h = self.height()
        for d, pm in self.pixmaps.items():
            p.drawPixmap(0, int(round(d * h + self.pan_off)), pm)
        p.end()

    def resizeEvent(self, e):
        super(_GridViewport, self).resizeEvent(e)
        if self.on_resize:
            self.on_resize()


class _GridPage(QWidget):
    """六周条带：连续周序列上 42 个 DayCell 组成的一段。条带间首尾相接、无重复周，
    平移停在任意位置都不会出现跨页重复行。可原地重建内容。"""

    def __init__(self, store, parent=None):
        super(_GridPage, self).__init__(parent)
        self.store = store
        self.on_day_click = None
        self.start = None  # 本段第一周的周一
        self._grid = QGridLayout(self)
        self._grid.setSpacing(0)
        self._grid.setContentsMargins(0, 0, 0, 0)

    def build(self, start, selected=None, dim_month=None):
        self.start = start
        while self._grid.count():
            it = self._grid.takeAt(0)
            if it.widget():
                it.widget().hide()  # 立即隐藏，避免等待 deleteLater 期间与新格子重叠
                it.widget().deleteLater()
        if dim_month is None:  # 无显示月上下文时的临时基准，随后由 _update_sub 统一校正
            ref = start + timedelta(days=17)
            dim_month = (ref.year, ref.month)
        for i in range(42):
            d = start + timedelta(days=i)
            cell = DayCell()
            cell.set_day(d, (d.year, d.month) != dim_month, self.store, d == selected)
            if self.on_day_click:
                cell.clicked.connect(lambda c=cell: self.on_day_click(c.date))
            self._grid.addWidget(cell, i // 7, i % 7)


class CalendarWidget(QWidget):
    def __init__(self, store, cfg, theme_key, parent=None):
        super(CalendarWidget, self).__init__(parent)
        self.store = store
        self.cfg = cfg
        self.theme_key = theme_key
        t = date.today()
        self.year, self.month = t.year, t.month

        root = QVBoxLayout(self)
        root.setContentsMargins(sc(16), 0, sc(16), 0)
        root.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(sc(2), sc(4), sc(2), sc(6))
        head.setSpacing(sc(8))
        left = QVBoxLayout()
        left.setSpacing(sc(1))
        clock_row = QHBoxLayout()
        clock_row.setSpacing(sc(8))
        bar = QFrame()
        bar.setObjectName('clockBar')
        bar.setFixedWidth(sc(3))
        self.clock_hm = QLabel()
        self.clock_hm.setObjectName('clockBig')
        self.sub = QLabel()
        self.sub.setObjectName('calSub')
        clock_row.addWidget(bar)
        clock_row.addWidget(self.clock_hm)
        clock_row.addWidget(self.sub, 0, Qt.AlignBottom)
        clock_row.addStretch(1)
        left.addLayout(clock_row)
        head.addLayout(left, 0)
        head.addStretch(1)
        self.btn_today = QToolButton()
        self.btn_today.setObjectName('todayBtn')
        self.btn_today.setText('今天')
        self.btn_today.setFixedSize(sc(46), sc(24))
        self.btn_today.clicked.connect(self.go_today)
        head.addWidget(self.btn_today, 0, Qt.AlignVCenter)
        root.addLayout(head)

        week = QGridLayout()
        week.setContentsMargins(0, 0, 0, sc(4))
        week.setSpacing(0)
        self.week_labels = []
        for i in range(7):
            lb = QLabel()
            lb.setObjectName('weekLabel')
            lb.setAlignment(Qt.AlignCenter)
            lb.setProperty('we', 'true' if i >= 5 else 'false')
            week.addWidget(lb, 0, i)
            self.week_labels.append(lb)
        root.addLayout(week)

        self.viewport = _GridViewport()
        root.addWidget(self.viewport, 1)
        self.viewport.on_resize = self._layout_pages
        self._pages = {}      # 上/当前/下三个条带：{-1, 0, 1} -> _GridPage
        self._off = 0.0       # 平移偏移（像素）：>0 内容下移（往上月），<0 内容上移（往下月）
        self._selected = None  # 单击选中的日期
        self._dim_month = None  # 灰色显示当前依据的 (年, 月)，跟随视口显示月
        self._dim_dirty = False  # 置灰滞后标记：平移中只记账，停手时一次性重刷
        self._panning = False  # 平移中（画位图缓存）
        self._drag_y = None    # 鼠标拖拽起点（globalY）；None = 未按下
        self._dragging = False # 是否已越过拖拽阈值
        self._press_y = 0
        self._settle = QTimer(self)  # 滚动停手判定：停手后切回活页面
        self._settle.setSingleShot(True)
        self._settle.setInterval(200)
        self._settle.timeout.connect(self._end_pan)
        self._glide_left = 0.0  # 滚轮平滑动画的剩余待滑距离（像素，与偏移回绕无关）
        self._glide_vel = 0.0   # 当前滑动速度（像素/帧），起步加速段 = 阻尼感
        self._glide = QTimer(self)  # 普通滚轮离散步进 -> 带阻尼的连续滑动（触摸板不走动画）
        self._glide.setInterval(15)
        self._glide.timeout.connect(self._glide_step)

        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick)
        self._clock.start(1000)

        self.set_theme(theme_key)
        self.refresh()
        self._tick()

    def _tick(self):
        now = datetime.now()
        self.clock_hm.setText(now.strftime('%H:%M:%S'))
        self._update_sub()

    def _apply_dim(self):
        """按 _dim_month 统一刷新所有格子的灰色显示（非当月置灰）。"""
        self._dim_dirty = False
        y, m = self._dim_month
        for page in self._pages.values():
            for cell in page.findChildren(DayCell):
                dim = 'true' if (cell.date.year, cell.date.month) != (y, m) else 'false'
                if cell.property('dim') != dim:
                    cell.setProperty('dim', dim)
                    for w in (cell, cell.num, cell.sub):  # 子孙选择器依赖祖先属性，需一并重刷
                        w.style().unpolish(w)
                        w.style().polish(w)

    def _visible_month(self):
        """视口垂直中线所在周的年月（以该周周四定月），随平移位置变化。"""
        h = self.viewport.height()
        if not self._pages or self._pages[0].start is None or h <= 0:
            return self.year, self.month
        r = int((h / 2.0 - self._off) // (h / 6.0))  # 中线所在行（相对当前段首周）
        d = self._pages[0].start + timedelta(days=7 * r + 3)
        return d.year, d.month

    def _update_sub(self):
        t = date.today()
        y, m = self._visible_month()
        if (y, m) != self._dim_month:  # 显示月变化：置灰滞后到停手（平移中逐帧重刷样式会卡）
            self._dim_month = (y, m)
            self._dim_dirty = True
            if not self._panning:
                self._apply_dim()
        vis = (y, m) != (t.year, t.month)
        if self.btn_today.isVisible() != vis:
            self.btn_today.setVisible(vis)
        txt = ('%d年%d月' % (y, m)) if vis else self._countdown_text(t)
        if self.sub.text() != txt:
            self.sub.setText(txt)
        accent = 'true' if vis else 'false'
        if self.sub.property('accent') != accent:
            self.sub.setProperty('accent', accent)
            self.sub.style().unpolish(self.sub)
            self.sub.style().polish(self.sub)

    def _countdown_text(self, t):
        """距离下一个节点的倒计时：午休前→距午休，午休区间内→距上班（午休结束），之后→距下班。
        休息日不显示。"""
        _, kind = self.store.info(t)
        if kind == 'off' or (t.weekday() >= 5 and kind != 'work'):
            return '今天休息'
        now = datetime.now()

        def at(hhmm):
            return now.replace(hour=int(hhmm[:2]), minute=int(hhmm[3:]), second=0, microsecond=0)

        noon_a, noon_b = parse_noon_range(self.cfg.data.get('off_noon')) or NOON_DEFAULT
        noon_a = at(noon_a)
        noon_b = at(noon_b)
        off = parse_time_text(self.cfg.data.get('off_evening') or '18:00')
        off = at(off) if off else None
        if now < noon_a:
            target, label = noon_a, '午休'
        elif noon_b > noon_a and now < noon_b:   # 区间反了就跳过「上班」这一档
            target, label = noon_b, '上班'
        elif off is not None and now < off:
            target, label = off, '下班'
        else:
            return '今天已下班'
        total_min = -(-(target - now).seconds // 60)  # 向上取整
        return '距%s %d:%02d' % (label, total_min // 60, total_min % 60)

    def set_theme(self, key):
        self.theme_key = key
        for lb, txt in zip(self.week_labels, THEMES[key]['week']):
            lb.setText(txt)

    def refresh(self):
        """即时重建三个条带页面并归零偏移（节假日更新、跨天、回到今天），无动画。"""
        self._settle.stop()
        self._glide.stop()
        self._end_pan()
        self._off = 0.0
        self._glide_left = 0.0
        self._glide_vel = 0.0
        if not self._pages:
            for d in (-1, 0, 1):
                page = _GridPage(self.store, self.viewport)
                page.on_day_click = self._select_day
                page.show()
                self._pages[d] = page
        first = date(self.year, self.month, 1)
        anchor = first - timedelta(days=first.weekday())  # 当前月 1 日所在周的周一
        for d in (-1, 0, 1):
            self._pages[d].build(anchor + timedelta(days=42 * d), self._selected, self._dim_month)
        self._update_sub()
        self._layout_pages()

    def _layout_pages(self):
        """按当前偏移摆放三个条带：上一段在视口上方，下一段在下方。"""
        if not self._pages:
            return
        w, h = self.viewport.width(), self.viewport.height()
        for d, page in self._pages.items():
            page.setGeometry(0, int(round(d * h + self._off)), w, h)

    def _recenter(self, n):
        """向 n 方向滚动一个条带（n=+1 向后 / -1 向前），轮换并回收页面。"""
        if n > 0:
            gone = self._pages[-1]
            self._pages = {-1: self._pages[0], 0: self._pages[1], 1: gone}
            gone.build(self._pages[0].start + timedelta(days=42), self._selected, self._dim_month)
        else:
            gone = self._pages[1]
            self._pages = {-1: gone, 0: self._pages[-1], 1: self._pages[0]}
            gone.build(self._pages[0].start - timedelta(days=42), self._selected, self._dim_month)
        if self._panning:
            # 页面编号整体挪了一位，位图缓存必须跟着换位；只补新段会让画面错开一整段
            pm = _page_pixmap(gone)
            px = self.viewport.pixmaps
            self.viewport.pixmaps = ({-1: px[0], 0: px[1], 1: pm} if n > 0
                                     else {-1: pm, 0: px[-1], 1: px[0]})

    def _select_day(self, d):
        """单击日期：记录选中并刷新现有格子的选中态（滚动/重建后由 build 保持）。"""
        self._selected = d
        for page in self._pages.values():
            for cell in page.findChildren(DayCell):
                sel = 'true' if cell.date == d else 'false'
                if cell.property('sel') != sel:
                    cell.setProperty('sel', sel)
                    for w in (cell, cell.num, cell.sub):  # 子孙选择器依赖祖先属性，需一并重刷
                        w.style().unpolish(w)
                        w.style().polish(w)

    # --- 自由平移（滚轮 / 触摸板 / 鼠标拖拽，停在哪就留在哪，不吸附） ---
    def _pan_by(self, dy):
        """平移 dy 像素：>0 内容下移（往上月），<0 内容上移（往下月）。越界换月回绕。"""
        self._begin_pan()
        self._off += dy
        h = self.viewport.height()
        while h > 0 and self._off >= h:      # 上一段已滚到正中：换段并回绕偏移
            self._recenter(-1)
            self._off -= h
        while h > 0 and self._off <= -h:     # 下一段已滚到正中
            self._recenter(1)
            self._off += h
        self._update_sub()
        self.viewport.pan_off = self._off
        self.viewport.update()

    def _begin_pan(self):
        """进入平移：抓取三个月页面为位图并隐藏活页面，之后每帧只 blit。"""
        if self._panning or not self._pages:
            return
        self._panning = True
        self.viewport.pan_off = self._off
        self.viewport.pixmaps = {d: _page_pixmap(page) for d, page in self._pages.items()}
        for page in self._pages.values():
            page.hide()
        self.viewport.update()

    def _end_pan(self):
        """结束平移：活页面同步到当前偏移并显示，恢复悬停/点击。位置保持不变。"""
        if not self._panning:
            return
        self._panning = False
        if self._dim_dirty:
            self._apply_dim()
        self.viewport.pixmaps = None
        self._layout_pages()
        for page in self._pages.values():
            page.show()
        self.viewport.update()

    def wheelEvent(self, e):
        # 触摸板给像素级增量：直接 1:1 跟手；普通滚轮只给角度增量（一格 120）：累积目标偏移，
        # 由 _glide 按 ~66fps 指数趋近，离散步进变成连续滑动
        pd = e.pixelDelta()
        if not pd.isNull():
            self._glide.stop()
            self._glide_left = 0.0
            self._glide_vel = 0.0
            self._pan_by(pd.y())
            self._settle.start()  # 停手 200ms 后切回活页面
        else:
            dy = e.angleDelta().y()
            if dy:
                h = self.viewport.height()
                self._glide_left += dy
                if h > 0:  # 限制累计距离，避免快速滚动时冲过太远
                    self._glide_left = max(-2 * h, min(2 * h, self._glide_left))
                if not self._glide.isActive():
                    self._glide.start()
        e.accept()

    def _glide_step(self):
        """平滑动画每帧：速度向"剩余距离 x 0.22"阻尼趋近（起步渐快 = 阻尼感，
        剩余距离耗尽自然减速停稳）；剩余距离与偏移回绕无关，滚动再远也能收敛。"""
        d = self._glide_left
        if abs(d) < 0.5:  # 收尾：补足残差后停
            if d:
                self._pan_by(d)
                self._glide_left = 0.0
            self._glide_vel = 0.0
            self._glide.stop()
            self._settle.start()
            return
        self._glide_vel += (d * 0.22 - self._glide_vel) * 0.35
        step = self._glide_vel
        if abs(step) > abs(d):  # 单步不超过剩余距离，防过冲
            step = d
            self._glide_vel = d
        self._glide_left -= step
        self._pan_by(step)
        self._settle.start()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._glide.stop()
            self._glide_left = 0.0
            self._glide_vel = 0.0
            self._drag_y = self._press_y = e.globalPos().y()
            self._dragging = False
            e.accept()
        else:
            super(CalendarWidget, self).mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_y is not None:
            y = e.globalPos().y()
            if self._dragging or abs(y - self._press_y) > 4:  # 阈值内仍算点击
                self._dragging = True
                self._pan_by(y - self._drag_y)
                self._drag_y = y
            e.accept()
        else:
            super(CalendarWidget, self).mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag_y is not None:
            if self._dragging:
                self._end_pan()  # 拖拽结束立即切回活页面
            else:
                cell = QApplication.widgetAt(e.globalPos())  # 未拖动 = 单击，手动分发
                if isinstance(cell, DayCell) and self.viewport.isAncestorOf(cell):
                    cell.clicked.emit()
            self._drag_y = None
            self._dragging = False
            e.accept()
        else:
            super(CalendarWidget, self).mouseReleaseEvent(e)

    def go_today(self):
        t = date.today()
        self.year, self.month = t.year, t.month
        self.refresh()


# ---------------- 待办 ----------------

class TodoStore(object):
    def __init__(self, path):
        self.path = path
        self.items = []
        self.load()

    def load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                self.items = [i for i in json.load(f) if i.get('text')]
        except Exception:
            self.items = []

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.items, f, ensure_ascii=False, indent=1)

    def add(self, text, due=None):
        ids = [i['id'] for i in self.items] or [0]
        it = {'id': max(ids) + 1, 'text': text, 'done': False}
        if due:
            it['due'] = due
        self.items.insert(0, it)
        self.save()

    def set_due(self, item_id, due):
        for it in self.items:
            if it['id'] == item_id:
                if due:
                    it['due'] = due
                else:
                    it.pop('due', None)
                break
        self.save()

    def toggle(self, item_id, done):
        for it in self.items:
            if it['id'] == item_id:
                it['done'] = done
                self.items.remove(it)
                if done:
                    self.items.append(it)       # 完成置底
                else:
                    self.items.insert(0, it)    # 取消完成回到顶部
                break
        self.save()

    def remove(self, item_id):
        self.items = [i for i in self.items if i['id'] != item_id]
        self.save()

    def update_text(self, item_id, text):
        for it in self.items:
            if it['id'] == item_id:
                it['text'] = text
                break
        self.save()

    def pending_count(self):
        return sum(1 for i in self.items if not i['done'])


class TodoList(QListWidget):
    emptyDoubleClicked = pyqtSignal()
    itemEditRequested = pyqtSignal(int)

    def __init__(self, parent=None):
        super(TodoList, self).__init__(parent)
        self.on_resize = None   # 行宽变化时重算各条高度（文字换行后行高不固定）

    def resizeEvent(self, e):
        super(TodoList, self).resizeEvent(e)
        if self.on_resize:
            self.on_resize()

    def mouseDoubleClickEvent(self, e):
        li = self.itemAt(e.pos())
        if li is None:
            self.emptyDoubleClicked.emit()
        else:
            item_id = li.data(Qt.UserRole)
            if item_id is not None:  # 双击已有条目 = 编辑（编辑器行无 UserRole，忽略）
                self.itemEditRequested.emit(item_id)


class DuePopup(QFrame):
    """截止时间选择弹层：月历 + 快捷按钮。Qt.Popup，点外侧自动关闭。"""

    def __init__(self, parent, current, on_pick, on_close):
        super(DuePopup, self).__init__(parent, Qt.Popup | Qt.WindowStaysOnTopHint)
        self.setObjectName('duePopup')
        self._on_pick = on_pick
        self._on_close = on_close
        lay = QVBoxLayout(self)
        lay.setContentsMargins(sc(8), sc(8), sc(8), sc(8))
        lay.setSpacing(sc(6))
        cal = QCalendarWidget(self)
        cal.setGridVisible(False)
        cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        cal.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        cal.setFirstDayOfWeek(Qt.Monday)
        if current:
            qd = QDate.fromString(current, 'yyyy-MM-dd')
            if qd.isValid():
                cal.setSelectedDate(qd)
        for name, t in (('qt_calendar_prevmonth', '<'), ('qt_calendar_nextmonth', '>')):
            b = cal.findChild(QToolButton, name)
            if b:
                b.setIcon(QIcon())   # 默认箭头图标在深色主题下看不清，改用字符
                b.setText(t)
        cal.clicked.connect(lambda qd: self._choose(qd.toPyDate()))
        lay.addWidget(cal)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(sc(6))
        for label, days in (('今天', 0), ('明天', 1)):
            b = QToolButton(self)
            b.setObjectName('todayBtn')
            b.setText(label)
            b.clicked.connect(lambda _=False, n=days: self._choose(date.today() + timedelta(days=n)))
            row.addWidget(b)
        row.addStretch(1)
        clr = QToolButton(self)
        clr.setObjectName('todayBtn')
        clr.setText('清除')
        clr.clicked.connect(lambda: self._choose(None))
        row.addWidget(clr)
        lay.addLayout(row)

    def _choose(self, d):
        self._on_pick(d)
        self.close()

    def closeEvent(self, e):
        self._on_close()
        super(DuePopup, self).closeEvent(e)


class TimePickerPopup(QFrame):
    """时间选择弹层：时/分两列滚动列表（仿 Element 时间选择器）。Qt.Popup，点外侧自动关闭。"""

    def __init__(self, parent, current, on_pick):
        super(TimePickerPopup, self).__init__(parent, Qt.Popup | Qt.WindowStaysOnTopHint)
        self.setObjectName('timePopup')
        self._on_pick = on_pick
        cur = QTime.fromString(current, 'HH:mm')
        if not cur.isValid():
            cur = QTime(12, 0)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(sc(6), sc(6), sc(6), sc(6))
        lay.setSpacing(0)
        self._cols = []
        for i, (n, row) in enumerate(((24, cur.hour()), (60, cur.minute()))):
            lst = QListWidget(self)
            lst.setObjectName('timeCol')
            if i == 1:
                lst.setProperty('sep', True)   # 分钟列带左侧分隔线
            lst.setVerticalScrollMode(QListWidget.ScrollPerPixel)
            for v in range(n):
                it = QListWidgetItem('%02d' % v, lst)
                it.setTextAlignment(Qt.AlignCenter)
            lst.setCurrentRow(row)
            lst.setFixedSize(sc(52), sc(28) * 6 + sc(10))
            lay.addWidget(lst)
            self._cols.append(lst)
        self._cols[1].itemClicked.connect(self._minute_picked)  # 点小时仅选中，点分钟即提交

    def showEvent(self, e):
        super(TimePickerPopup, self).showEvent(e)
        for lst in self._cols:   # 显示后把当前值滚到中间
            lst.scrollToItem(lst.currentItem(), QListWidget.PositionAtCenter)

    def _minute_picked(self, it):
        h = self._cols[0].currentRow()
        self._on_pick(QTime(max(h, 0), self._cols[1].row(it)))
        self.close()


class TodoWidget(QWidget):
    def __init__(self, store, parent=None):
        super(TodoWidget, self).__init__(parent)
        self.store = store
        self.theme_key = THEME_ORDER[0]
        self._editing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.pane = QFrame()
        self.pane.setObjectName('todoPane')
        pl = QVBoxLayout(self.pane)
        pl.setContentsMargins(sc(8), sc(8), sc(8), sc(8))
        pl.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(sc(10), 0, sc(10), sc(2))
        title = QLabel('待办清单')
        title.setObjectName('todoTitle')
        self.count = QLabel()
        self.count.setObjectName('todoCount')
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.count)
        pl.addLayout(head)

        self.list = TodoList()
        self.list.setObjectName('todoList')
        self.list.on_resize = self._sync_row_heights
        self.list.setSpacing(sc(3))
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.emptyDoubleClicked.connect(self.start_add)
        self.list.itemEditRequested.connect(self._edit_item)
        pl.addWidget(self.list, 1)

        hint = QToolButton()
        hint.setObjectName('addHint')
        hint.setText('＋ 双击空白处新建待办')
        hint.setSizePolicy(hint.sizePolicy().Expanding, hint.sizePolicy().Fixed)
        hint.clicked.connect(self.start_add)
        pl.addWidget(hint)

        root.addWidget(self.pane)
        self.rebuild()

    def set_solo(self, solo):
        """单栏模式下去掉双栏分隔样式。"""
        self.pane.setStyleSheet('QFrame#todoPane { border: none; background: transparent; }' if solo else '')

    def set_theme(self, key):
        self.theme_key = key
        self._update_count()

    def _update_count(self):
        self.count.setText(THEMES[self.theme_key].get('count_fmt', '{:d} 未完成').format(self.store.pending_count()))

    def _make_row(self, it):
        row = QFrame()
        row.setObjectName('todoRow')
        row.setMinimumHeight(sc(36))
        row.setProperty('done', 'true' if it['done'] else 'false')
        lay = QHBoxLayout(row)
        lay.setContentsMargins(sc(9), sc(4), sc(10), sc(4))
        lay.setSpacing(sc(9))
        cb = QToolButton()
        cb.setObjectName('todoCheck')
        cb.setText('✓')
        cb.setCheckable(True)
        cb.setChecked(it['done'])
        cb.setFixedSize(sc(18), sc(18))
        cb.clicked.connect(lambda checked, i=it['id']: self._toggle(i, checked))
        lay.addWidget(cb)
        tx = QLabel(it['text'])
        tx.setObjectName('todoText')
        tx.setWordWrap(True)   # 文本长时占多行（高度由 _sync_row_heights 汇报给列表）
        f = tx.font()
        f.setStrikeOut(it['done'])
        tx.setFont(f)
        lay.addWidget(tx, 1)
        if it.get('due') and not it['done']:
            text, late = due_chip(it['due'])
            if text:
                dl = QLabel(text)
                dl.setObjectName('todoDue')
                dl.setProperty('late', 'true' if late else 'false')
                lay.addWidget(dl)
        return row

    def rebuild(self):
        self.list.clear()
        self._editing = False
        self._editor = None
        for it in self.store.items:
            li = QListWidgetItem(self.list)
            li.setData(Qt.UserRole, it['id'])
            li.setSizeHint(QSize(10, sc(36)))
            self.list.addItem(li)
            self.list.setItemWidget(li, self._make_row(it))
        self._sync_row_heights()
        self._update_count()

    def _sync_row_heights(self):
        """按当前行宽重算每条的高度：文字换行后可能占多行，item 的 sizeHint 必须跟着长高，
        否则列表会把行压扁、文字被裁。编辑器行的高度由 _open_editor 定，跳过。
        跑两遍：第一遍定出的新高度可能让滚动条出现/消失，行宽随之变化，第二遍按最终宽度重算。"""
        if self.list.viewport().width() <= 0:
            return
        for _ in range(2):
            self._apply_row_heights()

    def _apply_row_heights(self):
        """按各行当前实得的宽度重算高度并写回 item。
        列表情景下 item 几何是延迟摆的，先 doItemsLayout() 让它按新行宽摆好，
        再问文字标签「这个宽度下你要多高」——按别人的宽度估算会少算一行。"""
        self.list.doItemsLayout()
        editor = getattr(self, '_editor', None)   # 首次布局早于 rebuild()，属性可能还没有
        edit_li = editor[0] if editor else None
        for i in range(self.list.count()):
            li = self.list.item(i)
            row = self.list.itemWidget(li)
            lay = row.layout() if row is not None else None
            if li is edit_li or lay is None:
                continue
            tx = row.findChild(QLabel, 'todoText')
            m = lay.contentsMargins()
            h = (tx.heightForWidth(tx.width()) if tx is not None else 0) + m.top() + m.bottom()
            h = max(h, sc(36))
            if li.sizeHint().height() != h:
                li.setSizeHint(QSize(10, h))

    def _toggle(self, item_id, checked):
        self.store.toggle(item_id, checked)
        self.rebuild()

    def start_add(self):
        if self._editing:
            return
        self._open_editor(None, '')

    def _edit_item(self, item_id):
        if self._editing:
            return
        for it in self.store.items:
            if it['id'] == item_id:
                self._open_editor(item_id, it['text'])
                break

    def _open_editor(self, item_id, text):
        self._editing = True
        self._picking = False
        self._just_picked = False
        self._edit_due = None
        if item_id is not None:
            # 编辑：原地替换原条目（原行不再显示）
            li = None
            for r in range(self.list.count()):
                if self.list.item(r).data(Qt.UserRole) == item_id:
                    li = self.list.item(r)
                    break
            if li is None:
                self._editing = False
                return
            li.setSizeHint(QSize(10, sc(48)))
            for it in self.store.items:
                if it['id'] == item_id:
                    self._edit_due = it.get('due')
                    break
        else:
            li = QListWidgetItem()
            li.setSizeHint(QSize(10, sc(48)))
            self.list.insertItem(0, li)
        box = QFrame()
        box.setObjectName('todoEditRow')
        hl = QHBoxLayout(box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(sc(5))
        ed = QLineEdit(text)
        ed.setObjectName('todoEdit')
        ed.setMinimumHeight(sc(42))
        ed.setPlaceholderText('输入待办，回车保存，Esc 取消')
        ed.installEventFilter(self)
        ed.returnPressed.connect(lambda: self._commit(li, ed, item_id))
        # ????? eventFilter ???????????????????? clicked ??????
        hl.addWidget(ed, 1)
        btn = QToolButton()
        btn.setObjectName('todoDateBtn')
        btn.setFocusPolicy(Qt.NoFocus)   # 不接受焦点：弹层关闭后焦点交还编辑框（失焦提交由延迟兜底拦截）
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip('设置截止时间')
        btn.setFixedSize(sc(32), sc(30))
        btn.setIcon(make_cal_icon(DUE_ICON_COLORS.get(self.theme_key, '#8a8a90')))
        btn.setIconSize(QSize(sc(17), sc(17)))
        btn.clicked.connect(lambda: self._pick_due(btn))
        hl.addWidget(btn)
        old_w = self.list.itemWidget(li)
        if old_w is not None:  # 替换前先移除并隐藏旧行，避免残留重影
            self.list.removeItemWidget(li)
            old_w.hide()
            old_w.deleteLater()
        self.list.setItemWidget(li, box)
        self._editor = (li, ed, item_id)
        self._due_btn = btn
        self._refresh_due_btn()
        ed.setFocus()

    def _refresh_due_btn(self):
        """已选截止日期时按钮显示紧凑日期，否则显示日历图标。"""
        if self._edit_due:
            try:
                d = datetime.strptime(self._edit_due, '%Y-%m-%d').date()
                self._due_btn.setIcon(QIcon())
                self._due_btn.setText(fmt_due_date(d))
                self._due_btn.setFixedWidth(sc(46))
                return
            except Exception:
                pass
        self._due_btn.setText('')

    def _pick_due(self, btn):
        if not self._editing or getattr(self, '_picking', False):
            return
        self._picking = True
        pop = DuePopup(self, self._edit_due, self._due_picked, self._popup_closed)
        self._popup = pop   # 持有引用，避免 PyQt 包装层被 GC 回收
        pop.show()
        pop.raise_()        # 面板是置顶 Tool 窗，确保弹层压在其上
        pos = btn.mapToGlobal(QPoint(0, btn.height() + sc(4)))
        ag = QApplication.primaryScreen().availableGeometry()
        x = min(pos.x(), ag.right() - pop.width() - sc(4))
        y = min(pos.y(), ag.bottom() - pop.height() - sc(4))
        pop.move(x, max(y, ag.top()))

    def _due_picked(self, d):
        if not self._editing:
            return   # 编辑会话已结束（编辑器控件已随 rebuild 销毁），忽略迟到回调
        self._edit_due = d.isoformat() if d else None
        self._just_picked = True
        self._refresh_due_btn()

    def _popup_closed(self):
        self._picking = False
        if getattr(self, '_just_picked', False):
            # 刚选了日期：保持编辑态，焦点交还输入框继续编辑
            self._just_picked = False
            if self._editing and getattr(self, '_editor', None):
                self._editor[1].setFocus()
            return
        # 点弹窗外侧关闭：若焦点没回到编辑框，视为放弃编辑，兜底提交
        QTimer.singleShot(0, self._commit_if_unfocused)

    def _commit_if_unfocused(self):
        if self._editing and getattr(self, '_editor', None) and not self._editor[1].hasFocus():
            self._commit_current()

    def eventFilter(self, obj, ev):
        if isinstance(obj, QLineEdit):
            if ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
                obj.setProperty('cancelled', True)
                obj.clearFocus()
                self.rebuild()
                return True
            if ev.type() == QEvent.FocusOut and not obj.property('cancelled') \
                    and not getattr(self, '_picking', False):
                # 窗口失焦时 editingFinished 不一定触发，这里兜底提交
                QTimer.singleShot(0, self._commit_current)
        return super(TodoWidget, self).eventFilter(obj, ev)

    def _commit_current(self):
        if not self._editing or not getattr(self, '_editor', None):
            return
        if QApplication.mouseButtons() != Qt.NoButton:
            # 鼠标仍按着：点击链路（如日期按钮）尚未走完，等抬起后再判，
            # 否则 0ms 兜底会在 clicked 之前触发，误提交并销毁编辑器
            QTimer.singleShot(60, self._commit_current)
            return
        li, ed, item_id = self._editor
        self._commit(li, ed, item_id)

    def _commit(self, li, ed, item_id):
        if not self._editing or ed.property('cancelled') or getattr(self, '_picking', False):
            return
        self._editing = False
        text = ed.text().strip()
        if text:
            if item_id is None:
                self.store.add(text, self._edit_due)
            else:
                self.store.update_text(item_id, text)
                self.store.set_due(item_id, self._edit_due)
        self.rebuild()

    def _menu(self, pos):
        li = self.list.itemAt(pos)
        if li is None:
            return
        item_id = li.data(Qt.UserRole)
        m = QMenu(self)
        act_edit = m.addAction('编辑')
        act_del = m.addAction('删除')
        act = m.exec_(self.list.viewport().mapToGlobal(pos))
        if act is act_edit:
            for it in self.store.items:
                if it['id'] == item_id:
                    self._open_editor(item_id, it['text'])
                    break
        elif act is act_del:
            self.store.remove(item_id)
            self.rebuild()


# ---------------- 设置窗口 ----------------

def round_corners(win):
    """无边框窗口圆角：Win11 用 DWM（DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND），
    Win7/10 降级为圆角遮罩。"""
    try:
        if sys.getwindowsversion().build >= 22000:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                int(win.winId()), 33, ctypes.byref(ctypes.c_int(2)), 4)
        elif win.width() > 0:
            path = QPainterPath()
            path.addRoundedRect(0.0, 0.0, float(win.width()), float(win.height()), 14.0, 14.0)
            win.setMask(QRegion(path.toFillPolygon().toPolygon()))
    except Exception:
        pass


def parse_time_text(text):
    """把时间输入框里的自由文本解析成 'HH:mm'，解析不了返回 None。
    中文冒号按英文冒号处理（中文输入法下常打出「：」）；允许省前导零与时/分之间的冒号：
    '9' → 09:00，'930' → 09:30，'9:30' / '9：30' → 09:30。全角数字也认（int 能直接解析）。"""
    s = (text or '').strip().replace('：', ':')
    if ':' in s:
        parts = s.split(':')
        if len(parts) != 2:
            return None
        hh, mm = parts
    elif len(s) <= 2:
        hh, mm = s, '0'
    elif len(s) <= 4:
        hh, mm = s[:-2], s[-2:]
    else:
        return None
    if not (hh.isdigit() and mm.isdigit()):
        return None
    h, m = int(hh), int(mm)
    if h > 23 or m > 59:
        return None
    return '%02d:%02d' % (h, m)


NOON_DEFAULT = ('12:00', '13:00')   # 午休区间默认值（开始, 结束）


def parse_noon_range(text):
    """午休区间文本 -> (开始, 结束) 的 'HH:mm' 二元组，解析不了返回 None。
    分隔符宽松（- ~ ～ — － 都认）；只给一个时间时按旧版单值处理，结束 = 开始 + 1 小时。"""
    s = (text or '').strip()
    for sep in ('～', '~', '—', '－', '–'):
        s = s.replace(sep, '-')
    parts = [p for p in s.split('-') if p.strip()]
    if not parts:
        return None
    start = parse_time_text(parts[0])
    if start is None:
        return None
    if len(parts) > 1:
        end = parse_time_text(parts[1])
        return (start, end) if end else None
    total = (int(start[:2]) * 60 + int(start[3:]) + 60) % 1440   # 旧配置只存了开始点
    return start, '%02d:%02d' % (total // 60, total % 60)


class HolidayImportDialog(QDialog):
    """导入节假日 JSON 的引导窗口：先告诉用户去哪拿数据，再选文件。
    文件选择 / 解析 / 托盘通知都由入口的 on_pick 负责，本窗口只管引导。"""

    def __init__(self, panel, on_pick):
        super(HolidayImportDialog, self).__init__(panel)
        self.setObjectName('settingsDlg')
        self.setWindowTitle('导入节假日数据')
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowModality(Qt.NonModal)  # 与设置窗口一致：不阻塞面板
        self._drag = None
        url = cd.API_URL % date.today().year

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = QWidget()
        card.setObjectName('settingsPanel')
        root.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(sc(16), sc(6), sc(14), sc(14))
        lay.setSpacing(sc(9))

        # 标题栏（可拖动）
        self.titlebar = QFrame()
        self.titlebar.setFixedHeight(sc(34))
        tb = QHBoxLayout(self.titlebar)
        tb.setContentsMargins(0, 0, 0, 0)
        title = QLabel('导入节假日数据')
        title.setObjectName('setTitle')
        tb.addWidget(title)
        tb.addStretch(1)
        close = QToolButton()
        close.setObjectName('closeBtn')
        close.setText('✕')
        close.setFixedSize(sc(28), sc(24))
        close.setToolTip('关闭')
        close.clicked.connect(self.close)
        tb.addWidget(close)
        lay.addWidget(self.titlebar)

        def note(text):
            lb = QLabel(text)
            lb.setObjectName('setLabel')
            lb.setWordWrap(True)
            lay.addWidget(lb)

        note('本程序导入的是「年份 JSON」，与内置数据同源，共三步：')
        note('① 用浏览器打开下面的网址，把页面内容另存为 .json 文件\n'
             '（网址末尾是年份，要别的年份直接改它）')

        self.url = QLabel(url)
        self.url.setObjectName('setUrl')
        self.url.setTextInteractionFlags(Qt.TextSelectableByMouse)  # 方便复制
        lay.addWidget(self.url)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, sc(4))
        open_btn = QPushButton('打开网址')
        open_btn.setObjectName('setBtn')
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        row.addWidget(open_btn)
        row.addStretch(1)
        lay.addLayout(row)

        note('② 回到这里，选择刚保存的文件即可导入')
        row2 = QHBoxLayout()
        pick = QPushButton('选择文件…')
        pick.setObjectName('setBtn')
        pick.clicked.connect(lambda: (self.close(), on_pick()))
        row2.addWidget(pick)
        row2.addStretch(1)
        lay.addLayout(row2)

        note('内网无法访问上述网址时，可用 jiejiariapi.com 的同格式接口。')
        self.setFixedWidth(sc(388))

    # 无边框窗口：拖标题栏移动
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.pos().y() < self.titlebar.height():
            self._drag = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()
        else:
            super(HolidayImportDialog, self).mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag)
            e.accept()
        else:
            super(HolidayImportDialog, self).mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        super(HolidayImportDialog, self).mouseReleaseEvent(e)


class SettingsDialog(QDialog):
    """齿轮按钮弹出的无边框设置窗口，样式跟随当前主题（themes.py #settingsPanel 区段）。
    on_fetch/on_import 为节假日数据回调（由入口提供，以便复用托盘通知）。
    改动即时生效并写入 config.json。"""
    def __init__(self, panel, on_fetch, on_import):
        super(SettingsDialog, self).__init__(panel)
        self.setObjectName('settingsDlg')
        self.setWindowTitle('设置')
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        # QDialog 默认 ApplicationModal，会连面板一起冻结；设置窗口开着时面板仍可拖拽 / 点日历
        self.setWindowModality(Qt.NonModal)
        self._drag = None
        cfg = panel.cfg

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = QWidget()
        card.setObjectName('settingsPanel')
        root.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(sc(16), sc(6), sc(10), sc(14))
        lay.setSpacing(0)

        # 标题栏（可拖动）
        self.titlebar = QFrame()
        self.titlebar.setFixedHeight(sc(34))
        tb = QHBoxLayout(self.titlebar)
        tb.setContentsMargins(0, 0, 0, 0)
        title = QLabel('设置')
        title.setObjectName('setTitle')
        tb.addWidget(title)
        tb.addStretch(1)
        close = QToolButton()
        close.setObjectName('closeBtn')
        close.setText('✕')
        close.setFixedSize(sc(28), sc(24))
        close.setToolTip('关闭')
        close.clicked.connect(self.reject)
        tb.addWidget(close)
        lay.addWidget(self.titlebar)

        form = QFormLayout()
        form.setContentsMargins(sc(2), sc(6), sc(6), 0)
        form.setHorizontalSpacing(sc(14))
        form.setVerticalSpacing(sc(12))
        lay.addLayout(form)

        def row_label(text):
            lb = QLabel(text)
            lb.setObjectName('setLabel')
            return lb

        # 主题
        theme_row = QHBoxLayout()
        theme_row.setSpacing(sc(14))
        for key in THEME_CHOICES:
            r = QRadioButton('跟随系统' if key == AUTO else THEMES[key]['name'])
            r.setChecked(key == panel._theme)
            r.toggled.connect(lambda on, k=key: panel.apply_theme(k) if on else None)
            theme_row.addWidget(r)
        theme_row.addStretch(1)
        form.addRow(row_label('主题'), theme_row)

        # 双栏
        dual = QCheckBox('日历 + 待办同屏显示')
        dual.setChecked(panel._dual)
        dual.toggled.connect(panel.set_dual)
        form.addRow(row_label('双栏'), dual)

        # 下班倒计时（自由文本输入 + 时钟弹层）
        # 用 QLineEdit 而非 QTimeEdit：QTimeEdit 是按时/分分段校验的，全选后直接打字会被
        # 校验器拒掉（要么必须先选中某一段，要么根本打不进冒号）
        self._time_rows = []

        def time_field(text):
            """一个时间输入框 + 时钟按钮，返回 (外框, 输入框)。外框顺带接好 hover/焦点描边。"""
            ed = QLineEdit(text)
            field = QWidget()
            field.setObjectName('timeField')
            field.setFocusProxy(ed)
            field.setFixedSize(sc(96), sc(30))
            fb = QHBoxLayout(field)
            fb.setContentsMargins(0, 0, sc(3), 0)
            fb.setSpacing(0)
            fb.addWidget(ed, 1)
            btn = QToolButton()
            btn.setObjectName('timeBtn')
            btn.setIcon(make_clock_icon(DUE_ICON_COLORS.get(resolve_theme(panel._theme), '#8a8a90')))
            btn.setIconSize(QSize(sc(14), sc(14)))
            btn.setFixedSize(sc(24), sc(24))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip('选择时间')
            btn.clicked.connect(lambda _=False, e=ed, b=btn: self._pick_time(e, b))
            fb.addWidget(btn)
            ed.installEventFilter(self)    # hover/focus 态同步到外框描边
            btn.installEventFilter(self)
            self._time_rows.append((ed, btn, field))
            return field, ed

        def commit_single(ed, key, dflt, normalize):
            """单值框：输入过程中即时落盘；normalize（失焦/回车）时归一化，解析不了回退上次的值。"""
            v = parse_time_text(ed.text())
            if v is None:
                if not normalize:
                    return
                v = cfg.data.get(key) or dflt
            cfg.set(key, v)
            if normalize and ed.text() != v:
                ed.setText(v)

        def commit_noon(finishing=None):
            """午休两个框合并成一个 'HH:mm-HH:mm' 落盘；finishing 是失焦的那个框，
            它解析不了就退回已存区间的对应端，避免半截输入把整个区间写坏。"""
            a, b = parse_time_text(noon_a.text()), parse_time_text(noon_b.text())
            if finishing is not None:
                cur = parse_noon_range(cfg.data.get('off_noon')) or NOON_DEFAULT
                a, b = a or cur[0], b or cur[1]
            if not (a and b):
                return
            cfg.set('off_noon', '%s-%s' % (a, b))
            if finishing is not None:
                for ed, v in ((noon_a, a), (noon_b, b)):
                    if ed.text() != v:
                        ed.setText(v)

        # 午休：开始 – 结束
        rng = parse_noon_range(cfg.data.get('off_noon')) or NOON_DEFAULT
        noon_row = QWidget()
        rb = QHBoxLayout(noon_row)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(sc(6))
        f_a, noon_a = time_field(rng[0])
        f_b, noon_b = time_field(rng[1])
        dash = QLabel('–')
        dash.setObjectName('setLabel')     # 借用表单标签的弱化色
        rb.addWidget(f_a)
        rb.addWidget(dash)
        rb.addWidget(f_b)
        rb.addStretch(1)
        form.addRow(row_label('午休时间'), noon_row)
        noon_a.textChanged.connect(lambda _t: commit_noon())
        noon_b.textChanged.connect(lambda _t: commit_noon())
        noon_a.editingFinished.connect(lambda: commit_noon(noon_a))
        noon_b.editingFinished.connect(lambda: commit_noon(noon_b))

        # 下班
        evening_row, evening = time_field(parse_time_text(cfg.data.get('off_evening') or '18:00') or '18:00')
        form.addRow(row_label('下班时间'), evening_row)
        evening.textChanged.connect(lambda _t: commit_single(evening, 'off_evening', '18:00', False))
        evening.editingFinished.connect(lambda: commit_single(evening, 'off_evening', '18:00', True))

        # 开机自启
        auto = QCheckBox('登录 Windows 后自动启动')
        auto.setChecked(bool(sysutil.autostart_get()))
        auto.toggled.connect(lambda on: sysutil.autostart_set() if on else sysutil.autostart_remove())
        form.addRow(row_label('开机自启'), auto)

        # 节假日数据
        sep = QFrame()
        sep.setObjectName('setSep')
        sep.setFixedHeight(1)
        form.addRow(sep)
        holiday_row = QHBoxLayout()
        holiday_row.setSpacing(sc(8))
        for text, fn in (('联网更新', on_fetch), ('导入 JSON…', on_import)):
            b = QPushButton(text)
            b.setObjectName('setBtn')
            b.clicked.connect(fn)
            holiday_row.addWidget(b)
        form.addRow(row_label('节假日'), holiday_row)

        # 保存按钮（改动即时生效，点击即确认并关闭）
        save_row = QHBoxLayout()
        save_row.setContentsMargins(0, sc(12), sc(4), 0)
        save_row.addStretch(1)
        save = QPushButton('保存')
        save.setObjectName('setSave')
        save.setCursor(Qt.PointingHandCursor)
        save.setDefault(True)
        save.clicked.connect(self.accept)
        save_row.addWidget(save)
        lay.addLayout(save_row)

        # 默认停靠在主面板上方右对齐，溢出屏幕上方则改到下方
        self.adjustSize()
        ag = QApplication.primaryScreen().availableGeometry()
        geo = panel.frameGeometry()
        x = min(max(geo.right() - self.width(), ag.left()), ag.right() - self.width())
        y = geo.top() - self.height() - sc(8)
        if y < ag.top():
            y = min(geo.bottom() + sc(8), ag.bottom() - self.height())
        self.move(x, y)

    def _pick_time(self, te, anchor):
        """在时间输入框下方弹出时/分选择层，选中的时间写回输入框（textChanged 即落盘）。"""
        old = getattr(self, '_time_pop', None)
        if old is not None and old.isVisible():   # 弹层已开时再点时钟按钮 = 收起
            old.close()
            return
        pop = TimePickerPopup(self, parse_time_text(te.text()) or '12:00',
                              lambda qt, e=te: e.setText(qt.toString('HH:mm')))
        self._time_pop = pop   # 持有引用，避免 PyQt 包装层被 GC 回收
        pop.show()
        pop.raise_()           # 设置窗是置顶 Tool 窗，确保弹层压在其上
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + sc(4)))
        ag = QApplication.primaryScreen().availableGeometry()
        x = min(pos.x(), ag.right() - pop.width() - sc(4))
        y = min(pos.y(), ag.bottom() - pop.height() - sc(4))
        pop.move(max(x, ag.left()), max(y, ag.top()))

    def eventFilter(self, obj, ev):
        """时间输入框的 hover/焦点态同步到外框，驱动描边与底色变化。"""
        for te, btn, field in getattr(self, '_time_rows', []):
            if obj is te or obj is btn:
                t = ev.type()
                if t == QEvent.Enter or t == QEvent.Leave:
                    hov = field.underMouse() or te.underMouse() or btn.underMouse()
                    field.setProperty('hov', 'true' if hov else 'false')
                elif t == QEvent.FocusIn or t == QEvent.FocusOut:
                    field.setProperty('focus', 'true' if te.hasFocus() else 'false')
                else:
                    break
                field.style().unpolish(field)
                field.style().polish(field)
                break
        return super(SettingsDialog, self).eventFilter(obj, ev)

    def showEvent(self, e):
        super(SettingsDialog, self).showEvent(e)
        round_corners(self)

    def resizeEvent(self, e):
        super(SettingsDialog, self).resizeEvent(e)
        round_corners(self)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.pos().y() < self.titlebar.height():
            self._drag = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()
        else:
            super(SettingsDialog, self).mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag)
            e.accept()
        else:
            super(SettingsDialog, self).mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        super(SettingsDialog, self).mouseReleaseEvent(e)


# ---------------- 主窗口 ----------------

class _SlideStack(QWidget):
    """横向滑动切换的堆叠容器：换页时旧页滑出、新页滑入。
    接口与 QStackedWidget 的子集兼容：addWidget / removeWidget / currentWidget / currentIndex。"""

    def __init__(self, parent=None):
        super(_SlideStack, self).__init__(parent)
        self._pages = []
        self._current = None
        self._anims = []

    def addWidget(self, w):
        self._pages.append(w)
        w.setParent(self)
        if self._current is None:
            self._current = w
            w.setGeometry(self.rect())
            w.show()
        else:
            w.hide()

    def removeWidget(self, w):
        self._end_transition()
        if w in self._pages:
            self._pages.remove(w)
        if self._current is w:
            self._current = self._pages[0] if self._pages else None
            if self._current is not None:
                self._current.setGeometry(self.rect())
                self._current.show()

    def currentWidget(self):
        return self._current

    def currentIndex(self):
        return self._pages.index(self._current) if self._current in self._pages else -1

    def slide_to(self, w):
        """动画切换到指定页面：前进向左推入，后退向右推入。"""
        if w is self._current or w not in self._pages:
            return
        self._end_transition()
        old = self._current
        self._current = w
        if old is None or not self.isVisible():
            w.setGeometry(self.rect())
            w.show()
            if old is not None:
                old.hide()
            return
        forward = self._pages.index(w) > self._pages.index(old)
        width = max(self.width(), 1)
        w.setGeometry(width if forward else -width, 0, width, self.height())
        w.show()
        for page, end_x in ((w, 0), (old, -width if forward else width)):
            anim = QPropertyAnimation(page, b'pos', self)
            anim.setDuration(220)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.setStartValue(page.pos())
            anim.setEndValue(QPoint(end_x, 0))
            anim.start()
            self._anims.append(anim)
        self._anims[-1].finished.connect(lambda: self._on_slide_done(old))

    def _on_slide_done(self, old):
        old.hide()
        self._anims = []

    def _end_transition(self):
        """终止进行中的滑动：当前页归位，其余页立即隐藏（快速连点时直接吸附）。"""
        for anim in self._anims:
            anim.stop()
        self._anims = []
        for page in self._pages:
            if page is self._current:
                page.setGeometry(self.rect())
                page.show()
            else:
                page.hide()

    def resizeEvent(self, e):
        super(_SlideStack, self).resizeEvent(e)
        for page in self._pages:
            if page.parent() is self:
                page.resize(self.size())


class FloatingPanel(QWidget):
    toggled = pyqtSignal()
    settingsRequested = pyqtSignal()

    def __init__(self, cfg, hstore, tstore):
        super(FloatingPanel, self).__init__()
        self.cfg = cfg
        self.cn_font, self.num_font = pick_fonts()
        set_num_font(self.num_font)
        # 不用 WA_TranslucentBackground：分层窗口禁用 ClearType，文字灰糊。
        # 不透明窗口 + Win11 DWM 圆角（Win7/10 降级为圆角遮罩），文字锐利度对齐系统组件。
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self._pin = 0   # 固定档位，稍后由 set_pin 按配置恢复（见「固定」一节）
        self.setObjectName('panelRoot')

        root = QVBoxLayout(self)
        root.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        root.setSpacing(0)

        # 不用 QGraphicsDropShadowEffect：Qt5 下会破坏半透明顶层窗的屏幕合成。
        # 阴影改为 FloatingPanel.paintEvent 手绘（见下）。
        self.panel = QWidget()
        self.panel.setObjectName('panel')
        root.addWidget(self.panel)

        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)

        # 标题栏
        self.titlebar = QFrame()
        self.titlebar.setObjectName('titlebar')
        self.titlebar.setFixedHeight(sc(42))
        tb = QHBoxLayout(self.titlebar)
        tb.setContentsMargins(sc(14), sc(8), sc(10), sc(2))
        tb.setSpacing(6)

        self.tab_box = QFrame()
        self.tab_box.setObjectName('tabBox')
        bx = QHBoxLayout(self.tab_box)
        bx.setContentsMargins(sc(3), sc(3), sc(3), sc(3))
        bx.setSpacing(sc(6 if resolve_theme(cfg.theme) == 'nocturne' else 2))
        self.tabs = []
        for i, name in enumerate(['日历', '待办']):
            b = QToolButton()
            b.setObjectName('tab')
            b.setText(name)
            b.setProperty('active', 'false')
            b.clicked.connect(lambda _=False, i=i: self.set_tab(i))
            bx.addWidget(b)
            self.tabs.append(b)
        tb.addWidget(self.tab_box)
        tb.addStretch(1)

        self.btn_pin = QToolButton()
        self.btn_pin.setObjectName('iconBtn')
        self.btn_pin.setFixedSize(sc(30), sc(26))
        self.btn_pin.setIconSize(QSize(sc(14), sc(14)))
        self.btn_pin.clicked.connect(self._cycle_pin)
        tb.addWidget(self.btn_pin)
        self.btn_settings = QToolButton()
        self.btn_settings.setObjectName('iconBtn')
        self.btn_settings.setText('⚙')
        self.btn_settings.setFixedSize(sc(30), sc(26))
        self.btn_settings.setToolTip('设置')
        self.btn_settings.clicked.connect(lambda: self.settingsRequested.emit())
        self.btn_close = QToolButton()
        self.btn_close.setObjectName('closeBtn')
        self.btn_close.setText('✕')
        self.btn_close.setFixedSize(sc(30), sc(26))
        self.btn_close.setToolTip('关闭（托盘可重新打开）')
        self.btn_close.clicked.connect(self.hide)
        tb.addWidget(self.btn_settings)
        tb.addWidget(self.btn_close)
        pl.addWidget(self.titlebar)

        # 内容：单栏（堆叠）/ 双栏（并排）
        self.cal = CalendarWidget(hstore, cfg, resolve_theme(cfg.theme))
        self.todo = TodoWidget(tstore)
        self.todo.set_theme(resolve_theme(cfg.theme))

        self.single_stack = _SlideStack()
        self.single_page = QWidget()
        sl = QVBoxLayout(self.single_page)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.single_stack)
        self.dual_page = QWidget()
        self.dual_box = QHBoxLayout(self.dual_page)
        self.dual_box.setContentsMargins(0, 0, 0, 0)
        self.dual_box.setSpacing(0)

        self.content = QStackedLayout()
        self.content.addWidget(self.single_page)
        self.content.addWidget(self.dual_page)
        pl.addLayout(self.content, 1)

        self._today = date.today()
        self._midnight = QTimer(self)
        self._midnight.timeout.connect(self._check_date)
        self._midnight.start(30000)

        self._dual = None  # None 而非 False：避免 set_dual 的“无变化短路”跳过首次布局/定尺寸
        self._theme = cfg.theme
        self._icon_dir = _indicator_icons()
        self.apply_theme(cfg.theme, save=False)
        self.set_pin(cfg.pin or 0, save=False)   # 恢复上次的固定档位
        if cfg.dual:
            self.set_dual(True, save=False)
        else:
            self.set_dual(False, save=False)
            self.set_tab(int(cfg.tab or 0), save=False)

    # --- 布局模式 ---
    def set_tab(self, idx, save=True):
        if self._dual:
            self.set_dual(False, save=False)
        self.single_stack.slide_to(self.cal if idx == 0 else self.todo)
        for i, b in enumerate(self.tabs):
            b.setProperty('active', 'true' if i == idx else 'false')
            b.style().unpolish(b)
            b.style().polish(b)
        if save:
            self.cfg.set('tab', idx)

    def set_dual(self, dual, save=True):
        if dual == self._dual:
            if save:
                self.cfg.set('dual', dual)
            return
        self._dual = dual
        if dual:
            self.single_stack.removeWidget(self.cal)
            self.single_stack.removeWidget(self.todo)
            self.dual_box.addWidget(self.cal, 344)
            self.dual_box.addWidget(self.todo, 356)
            self.todo.set_solo(False)
            self.cal.show()
            self.todo.show()
            self.content.setCurrentWidget(self.dual_page)
        else:
            self.dual_box.removeWidget(self.cal)
            self.dual_box.removeWidget(self.todo)
            self.single_stack.addWidget(self.cal)
            self.single_stack.addWidget(self.todo)
            self.todo.set_solo(True)
            self.content.setCurrentWidget(self.single_page)
            self.set_tab(self.single_stack.currentIndex() if self.single_stack.currentWidget() in (self.cal, self.todo) else 0, save=False)
        self.tab_box.setVisible(not dual)  # 双栏已同屏显示日历 + 待办，tab 栏没有意义
        self.setFixedSize(sc(DUAL_W if dual else SINGLE_W), sc(PANEL_H))
        self._clamp_to_screen()
        if save:
            self.cfg.set('dual', dual)

    # --- 固定 ---
    def _cycle_pin(self):
        self.set_pin(self._pin + 1)

    def set_pin(self, state, save=True):
        """三档循环：0 未固定（可拖动、置顶）→ 1 钉在桌面（不可移动、可被其它窗口覆盖）
        → 2 始终置顶（不可移动）。切换档位要改窗口标志，而改标志会销毁并重建原生窗口，
        所以这里自己负责按原位置、原显隐状态重新 show（showEvent 会重贴圆角）。"""
        try:
            self._pin = int(state) % 3
        except (TypeError, ValueError):
            self._pin = 0
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self._pin != 1:
            flags |= Qt.WindowStaysOnTopHint    # 「钉在桌面」这一档不置顶，才会被别的窗口盖住
        pos, was_visible = self.pos(), self.isVisible()
        self.setWindowFlags(flags)
        self.move(pos)
        if was_visible:
            self.show()
        self._refresh_pin_icon()
        self.btn_pin.setToolTip(PIN_TIPS[self._pin])
        if save:
            self.cfg.set('pin', self._pin)

    def _refresh_pin_icon(self):
        """图钉配色跟着主题走：未固定用弱化色，钉住用强调色，实心表示始终置顶。"""
        real = resolve_theme(self._theme)
        if self._pin == 0:
            self.btn_pin.setIcon(make_pin_icon(DUE_ICON_COLORS.get(real, '#8a8a90')))
        else:
            self.btn_pin.setIcon(make_pin_icon(ACCENT_COLORS.get(real, '#e8a33d'), self._pin == 2))

    # --- 主题 ---
    def apply_theme(self, key, save=True):
        self._theme = key  # 用户选择，可能是 auto
        real = resolve_theme(key)
        QApplication.instance().setStyleSheet(build_qss(real, self.cn_font, self.num_font, ui_scale(), self._icon_dir))
        self.cal.set_theme(real)
        self.todo.set_theme(real)
        self._refresh_pin_icon()
        if save:
            self.cfg.set('theme', key)


    def showEvent(self, e):
        super(FloatingPanel, self).showEvent(e)
        self._round_corners()

    def resizeEvent(self, e):
        super(FloatingPanel, self).resizeEvent(e)
        self._round_corners()

    def _round_corners(self):
        round_corners(self)

    # --- 位置 ---
    def _default_pos(self):
        ag = QApplication.primaryScreen().availableGeometry()
        return QPoint(ag.right() - self.width() - sc(20), ag.bottom() - self.height() - sc(20))

    def place_initial(self):
        ag = QApplication.primaryScreen().availableGeometry()
        pos = self.cfg.pos
        if pos and self.cfg.data.get('pos_screen') == [ag.width(), ag.height()]:
            self.move(QPoint(pos[0], pos[1]))
        else:
            self.move(self._default_pos())
        self._clamp_to_screen()

    def _clamp_to_screen(self):
        ag = QApplication.primaryScreen().availableGeometry()
        x = min(max(self.x(), ag.left() - self.width() + 120), ag.right() - 120)
        y = min(max(self.y(), ag.top()), ag.bottom() - 60)
        self.move(x, y)

    def mousePressEvent(self, e):
        # 固定后不可移动（固定档位由标题栏的图钉按钮切换）
        if e.button() == Qt.LeftButton and not self._pin \
                and e.pos().y() < SHADOW + self.titlebar.height():
            self._drag = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()
        else:
            super(FloatingPanel, self).mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if getattr(self, '_drag', None) is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag)
            e.accept()
        else:
            super(FloatingPanel, self).mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if getattr(self, '_drag', None) is not None:
            self._drag = None
            ag = QApplication.primaryScreen().availableGeometry()
            self.cfg.data['pos_screen'] = [ag.width(), ag.height()]
            self.cfg.set('pos', [self.x(), self.y()])
        super(FloatingPanel, self).mouseReleaseEvent(e)

    # --- 其他 ---
    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def refresh_holidays(self):
        self.cal.refresh()

    def _check_date(self):
        if date.today() != self._today:
            self._today = date.today()
            self.cal.refresh()
            self.todo.rebuild()
        if self._theme == AUTO and self.cal.theme_key != resolve_theme(AUTO):
            self.apply_theme(AUTO, save=False)  # 系统「应用模式」改了，跟着切


























