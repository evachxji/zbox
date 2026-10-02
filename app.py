# -*- coding: utf-8 -*-
"""Zviber 桌面悬浮面板：日历 + 待办。PyQt5，兼容 Win7/10/11、Python 3.8+。"""
import ctypes
from ctypes import wintypes
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

from PyQt5.QtCore import (Qt, QTimer, QSize, QPoint, QPointF, QRectF, QDate, QTime,
                          pyqtSignal, QEvent, QPropertyAnimation, QVariantAnimation, QEasingCurve)
from PyQt5.QtGui import (QFont, QFontDatabase, QPainter, QColor, QPixmap, QIcon, QPainterPath,
                         QRegion, QPen, QLinearGradient, QCursor)
from PyQt5.QtWidgets import (QWidget, QFrame, QLabel, QToolButton, QVBoxLayout, QHBoxLayout,
                             QGridLayout, QStackedLayout, QListWidget,
                             QListWidgetItem, QLineEdit, QMenu, QApplication, QDialog,
                             QFormLayout, QCheckBox, QRadioButton, QPushButton, QCalendarWidget,
                             QLayout)

import calendar_data as cd
import sysutil
from themes import THEMES, THEME_ORDER, THEME_CHOICES, AUTO, build_qss
from version import APP_VERSION, GITHUB_URL

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
    """菜单/窗口图标：深靛底 + 白色横杠 + 琥珀斜杠的极简 Z"""
    icon = QIcon()
    for s in sizes:       # 逐尺寸矢量绘制，小尺寸不糊
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



def fmt_due_date(d):
    """截止日期统一显示成 M.d（如 10.7）：行内 tag 与编辑器按钮共用这一处格式，避免两边不一致。"""
    return '%d.%d' % (d.month, d.day)


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
        self.data = {'theme': THEME_ORDER[0], 'dual': False, 'tab': 0, 'pos': None,
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


class DayCell(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super(DayCell, self).__init__(parent)
        self.setObjectName('dayCell')
        self.date = None
        self.num = QLabel(self)
        self.num.setObjectName('dayNum')
        self.num.setAlignment(Qt.AlignCenter)
        self.num.setFixedSize(sc(38), sc(30))  # 数字居中，高度收紧让农历贴近数字
        if _NUM_FONT['name']:
            f = QFont(_NUM_FONT['name'])
            f.setPixelSize(sc(_NUM_FONT['size']))
            f.setWeight(_NUM_FONT['weight'])
            self.num.setFont(f)
        self.sub = QLabel(self)
        self.sub.setObjectName('daySub')
        self.sub.setAlignment(Qt.AlignCenter)
        self.badge = QLabel(self)   # 贴右上角的「休」/「班」圆角标签，配色由主题 QSS 按 kind 给
        self.badge.setObjectName('badge')
        self.badge.setAlignment(Qt.AlignCenter)
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
        self._place_badge()

    def _place_badge(self):
        """角标贴格子右上角：先按 QSS 字号自适应尺寸，再摆到设计稿的 top/right 内缩位置。"""
        self.badge.adjustSize()
        self.badge.move(self.width() - self.badge.width() - sc(2), sc(2))

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
        # 右上角标签：法定节假日「休」、调休上班日「班」；普通双休日不标
        if kind:
            self.badge.setText('休' if kind == 'off' else '班')
            self.badge.setProperty('kind', kind)
            self.badge.show()
        else:
            self.badge.hide()
        for w in (self, self.num, self.sub, self.badge):
            w.style().unpolish(w)
            w.style().polish(w)
        self._place_badge()   # QSS 字号在 polish 之后才生效，尺寸自适应要放最后


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
        self._sub_fm_key = None    # _sync_sub_baseline 的缓存：字体没变就不重复量
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

    def _sync_sub_baseline(self):
        """把右边的小字顶到跟左边时分秒同一条文字基线上。
        两个 QLabel 按底边对齐时，字号大的字体 descent 也大，小字看着就沉下去一截 ——
        这里量出两者「基线到控件底边」的距离差，用下边距补回来（`Qt.AlignBaseline` 对 QLabel
        取的并不是文字基线，实测偏得更多，别改回去）。字体由 QSS 按 DPI 缩放，换了就得重量；
        每秒都会被调用，所以先比字体的 height/ascent/descent，没变就直接返回。"""
        fm = self.sub.fontMetrics()
        key = (fm.height(), fm.ascent(), fm.descent())
        if key == self._sub_fm_key:
            return
        self._sub_fm_key = key
        big = self.clock_hm.fontMetrics()

        def inset(f):   # 单行文本在控件内垂直居中时，基线到控件底边的距离
            return (f.height() - f.ascent() + f.descent()) // 2

        self.sub.setContentsMargins(0, 0, 0, max(0, inset(big) - inset(fm)))

    def _update_sub(self):
        self._sync_sub_baseline()
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
        休息日显示「今天休息」；午休与下班时间只要有一个留空，就整块不显示倒计时。"""
        _, kind = self.store.info(t)
        if kind == 'off' or (t.weekday() >= 5 and kind != 'work'):
            return '今天休息'
        noon = parse_noon_range(self.cfg.data.get('off_noon'))
        off_text = parse_time_text(self.cfg.data.get('off_evening'))
        if not noon or not off_text:
            return ''
        now = datetime.now()

        def at(hhmm):
            return now.replace(hour=int(hhmm[:2]), minute=int(hhmm[3:]), second=0, microsecond=0)

        noon_a, noon_b, off = at(noon[0]), at(noon[1]), at(off_text)
        if now < noon_a:
            target, label = noon_a, '午休'
        elif noon_b > noon_a and now < noon_b:   # 区间反了就跳过「上班」这一档
            target, label = noon_b, '上班'
        elif now < off:
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
        # 按锚点所在屏幕的可用区夹取，多显示器下弹层才不会被拉回主屏边缘
        scr = QApplication.screenAt(btn.mapToGlobal(btn.rect().center())) or QApplication.primaryScreen()
        ag = scr.availableGeometry()
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


# ---------------- 桌面层级 ----------------
# 64 位安全的 ctypes 签名（windll 默认按 32 位 int 截断，句柄高位会丢）
_u32 = ctypes.windll.user32
_u32.FindWindowW.restype = ctypes.c_void_p
_u32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
_u32.GetTopWindow.restype = ctypes.c_void_p
_u32.GetTopWindow.argtypes = [ctypes.c_void_p]
_u32.IsWindowVisible.restype = ctypes.c_int
_u32.IsWindowVisible.argtypes = [ctypes.c_void_p]
_u32.GetWindowLongPtrW.restype = ctypes.c_longlong
_u32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
_u32.GetWindowRect.restype = ctypes.c_int
_u32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_u32.GetWindow.restype = ctypes.c_void_p
_u32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_u32.SetWindowPos.restype = ctypes.c_int
_u32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, ctypes.c_uint]
_u32.SetParent.restype = ctypes.c_void_p
_u32.SetParent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_u32.GetParent.restype = ctypes.c_void_p
_u32.GetParent.argtypes = [ctypes.c_void_p]
_u32.WindowFromPoint.restype = ctypes.c_void_p
_u32.WindowFromPoint.argtypes = [wintypes.POINT]
_u32.FindWindowExW.restype = ctypes.c_void_p
_u32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
_u32.GetAncestor.restype = ctypes.c_void_p
_u32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_u32.IsWindow.restype = ctypes.c_int
_u32.IsWindow.argtypes = [ctypes.c_void_p]
_u32.GetClassNameW.restype = ctypes.c_int
_u32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
_u32.GetForegroundWindow.restype = ctypes.c_void_p
_u32.GetForegroundWindow.argtypes = []
_u32.GetWindowThreadProcessId.restype = wintypes.DWORD
_u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_u32.AttachThreadInput.restype = ctypes.c_int
_u32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_u32.SetFocus.restype = ctypes.c_void_p
_u32.SetFocus.argtypes = [ctypes.c_void_p]
_u32.SetWinEventHook.restype = ctypes.c_void_p
_u32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
_u32.UnhookWinEvent.restype = ctypes.c_int
_u32.UnhookWinEvent.argtypes = [ctypes.c_void_p]

# 桌面表层重排事件（桌面整理软件每 ~2.5s 重建表层：HIDE → REORDER → SHOW）
_EVENT_SHOW = 0x8002
_EVENT_REORDER = 0x8004
_WINEVENTPROC = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)

_GW_HWNDPREV = 3
_GW_HWNDNEXT = 2
_GA_ROOT = 2
_GWL_STYLE = -16
_GWL_EXSTYLE = -20
_WS_MINIMIZEBOX = 0x20000
_WS_EX_TOOLWINDOW = 0x80
_SWP_Z_ONLY = 0x1 | 0x2 | 0x10   # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE：只动 z-order


def _dbg(msg):
    """ZVIBER_DEBUG 环境变量开启的调试日志。run.cmd 常开，故带 2MB 轮转（留尾部 1MB）。"""
    if not os.environ.get('ZVIBER_DEBUG'):
        return
    try:
        path = os.path.join(os.environ.get('TEMP', '.'), 'zviber_debug.log')
        if os.path.exists(path) and os.path.getsize(path) > 2 * 1024 * 1024:
            with open(path, 'rb') as f:
                f.seek(-1024 * 1024, os.SEEK_END)
                tail = f.read()
            with open(path, 'wb') as f:
                f.write(b'... older logs truncated ...\n' + tail)
        with open(path, 'a', encoding='utf-8') as f:
            f.write('%.2f %s\n' % (time.time(), msg))
    except Exception:
        pass
_HWND_TOP = 0


def _is_desktop_surface(hwnd, sw, sh):
    """桌面表层判定：盖在桌面上的全屏层（Progman 本体、桌面整理软件的覆盖层等）。
    特征：可见 + 几乎铺满全屏 + 工具窗样式（WS_EX_TOOLWINDOW）+ 不可最小化（无 WS_MINIMIZEBOX）。
    最大化的普通应用窗口带 WS_MINIMIZEBOX，不会被误判。"""
    if not _u32.IsWindowVisible(hwnd):
        return False
    r = wintypes.RECT()
    _u32.GetWindowRect(hwnd, ctypes.byref(r))
    if (r.right - r.left) < sw * 9 // 10 or (r.bottom - r.top) < sh * 4 // 5:
        return False
    st = _u32.GetWindowLongPtrW(hwnd, _GWL_STYLE)
    ex = _u32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
    return bool(ex & _WS_EX_TOOLWINDOW) and not (st & _WS_MINIMIZEBOX)


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(64)
    _u32.GetClassNameW(hwnd, buf, 64)
    return buf.value


_PROG_FAMILY = ('Progman', 'SHELLDLL_DefView', 'WorkerW')


def probe_desktop(skip=(), extra=()):
    """在桌面采样点（外加 extra 点）做命中探测：返回 (第三方桌面表层 hwnd 或 None, 是否摸到桌面本体)。
    命中窗口沿父链向上逐级检查：Progman 家族 = 桌面本体；全屏工具窗 = 桌面整理的覆盖层。
    桌面整理软件的表层窗口嵌套层级会变化（有时是顶层窗口，有时挂在隐藏的辅助窗口下），
    z-order 遍历不可靠，只能用命中探测。采样点全被应用盖住时返回 (None, False) = 无结论。"""
    sw, sh = _u32.GetSystemMetrics(0), _u32.GetSystemMetrics(1)
    points = [(sw // 2, sh // 2), (sw // 4, sh // 3), (sw * 3 // 4, sh // 3),
              (sw // 4, sh * 2 // 3), (sw * 3 // 4, sh * 2 // 3)] + list(extra)
    surface, touched = None, False
    for x, y in points:
        h = _u32.WindowFromPoint(wintypes.POINT(x, y))
        while h:
            if h in skip:
                break
            if _class_name(h) in _PROG_FAMILY:
                touched = True
                break
            if _is_desktop_surface(h, sw, sh):
                surface = h
                break
            h = _u32.GetParent(h)
        if surface:
            break
    return surface, touched


def pin_to_desktop(win):
    """把窗口的属主设为桌面图标窗（SHELLDLL_DefView）：加入「桌面带」，
    Win+D / 显示桌面会跳过桌面带（Win11 24H2 上顶层窗口一律被收，桌面带成员豁免——
    桌面整理软件的全屏覆盖层就是这个结构）。
    保持 WS_POPUP 不改样式：坐标仍是屏幕绝对坐标，绘制/DWM 圆角/键盘焦点全走正常路径。
    成功返回 True。"""
    try:
        hwnd = int(win.winId())
        progman = _u32.FindWindowW('Progman', None)
        dv = _u32.FindWindowExW(progman, None, 'SHELLDLL_DefView', None) if progman else None
        if not hwnd or not dv:
            return False
        if _u32.GetAncestor(hwnd, _GA_ROOT) != progman:
            vis = bool(_u32.IsWindowVisible(hwnd))
            _u32.SetParent(hwnd, dv)
            if vis:
                _u32.ShowWindow(hwnd, 8)   # SW_SHOWNA：SetParent 挂带会丢 WS_VISIBLE，
                                           # Qt 仍认为可见不重绘（boxes._repin 同款坑）
        return _u32.GetAncestor(hwnd, _GA_ROOT) == progman
    except Exception:
        return False


def unpin_from_desktop(win):
    """脱离桌面带，恢复为普通顶层窗口（拖拽期间临时用：普通窗口不会被桌面整理的表层反压）。"""
    try:
        _u32.SetParent(int(win.winId()), None)
    except Exception:
        pass


def sink_to_desktop(win, anchor=None):
    """把窗口压到桌面层：桌面整理软件的全屏覆盖层之上、所有应用窗口之下。
    做法：从 z-order 顶部往下找「最上层的桌面表层」作锚点（找不到就用 Progman），
    把窗口插到锚点正上方。桌面整理软件会频繁重建/重排它的表层窗口，
    从顶部找锚点不受其 z-order 抖动影响；已就位时不动，避免闪烁。"""
    try:
        hwnd = int(win.winId())
        if not hwnd:
            return
        if anchor is None:
            anchor, _t = probe_desktop(skip=(hwnd,))
        if anchor is None:
            anchor = _u32.FindWindowW('Progman', None)
            if not anchor or anchor == hwnd:
                return
        above = _u32.GetWindow(anchor, _GW_HWNDPREV)
        if above == hwnd:
            return   # 已经在桌面层正上方
        _dbg('sink: anchor=%s above=%s' % (anchor, above))
        _u32.SetWindowPos(hwnd, above or _HWND_TOP, 0, 0, 0, 0, _SWP_Z_ONLY)
    except Exception:
        pass


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


def bar_corner_radius(win):
    """栏窗顶角半径（也是底边探进面板的深度）：对齐面板的实际圆角——
    Win11 DWM 圆角约 8 物理像素（换算成逻辑像素），Win7/10 遮罩固定 14（同 round_corners）。"""
    try:
        if sys.getwindowsversion().build >= 22000:
            return 8.0 / win.devicePixelRatioF()
    except Exception:
        pass
    return 14.0


def round_bar_top(win):
    """栏窗遮罩：只圆上面两个角。底边保持方角并探进面板顶边下方（被面板遮住），
    栏窗与面板合成一张完整卡片——没有接缝，面板上角的缺口也被栏窗填掉。"""
    try:
        r = bar_corner_radius(win)
        w, h = float(win.width()), float(win.height())
        path = QPainterPath()
        path.moveTo(0.0, h)
        path.lineTo(0.0, r)
        path.quadTo(0.0, 0.0, r, 0.0)
        path.lineTo(w - r, 0.0)
        path.quadTo(w, 0.0, w, r)
        path.lineTo(w, h)
        path.closeSubpath()
        win.setMask(QRegion(path.toFillPolygon().toPolygon()))
    except Exception:
        pass


def _place_below(win, anchor):
    """把 win 压到 anchor 正下方一档（只动 z-order，不动位置尺寸）。"""
    try:
        _u32.SetWindowPos(int(win.winId()), int(anchor.winId()), 0, 0, 0, 0, _SWP_Z_ONLY)
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
    """导入节假日数据的引导窗口：三个数据源各一行 URL，点「下载并导入」由程序代抓。
    抓取/解析由入口的 on_download 负责（抓到的原文存 sysutil.download_dir()），
    选文件导入由 on_pick 负责，本窗口只管引导与收 URL。"""

    def __init__(self, panel, on_download, on_pick):
        super(HolidayImportDialog, self).__init__(panel)
        self.setObjectName('settingsDlg')
        self.setWindowTitle('导入节假日数据')
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowModality(Qt.NonModal)  # 与设置窗口一致：不阻塞面板
        self._drag = None
        year = date.today().year

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

        note('三个数据源任选，年份 JSON 的格式程序都认。点「下载并导入」由程序直接抓取并导入，'
             '不用再手动另存；抓不到时（内网 / 代理）会自动用浏览器打开，另存成文件后再用下面的按钮导入。')

        # 每源一行：主源 / 备用1 / 备用2 + 可改的 URL + 下载并导入
        self.sources = []
        for i, src in enumerate(cd.SOURCES):
            row = QHBoxLayout()
            row.setSpacing(sc(6))
            tag = QLabel('主源' if i == 0 else '备用%d' % i)
            tag.setObjectName('setLabel')
            tag.setFixedWidth(sc(32))
            ed = QLineEdit(src['url'] % year)
            ed.setObjectName('srcEdit')
            ed.setCursorPosition(0)   # 默认露出域名（URL 尾巴不如域名好认）
            ed.setToolTip('%s\nURL 可以改：内网镜像、换年份直接改链接里的数字' % src['name'])
            btn = QPushButton('下载并导入')
            btn.setObjectName('setBtn')
            btn.clicked.connect(lambda _=False, s=src, e=ed, b=btn: self._download(on_download, s['name'], e, b))
            row.addWidget(tag)
            row.addWidget(ed, 1)
            row.addWidget(btn)
            lay.addLayout(row)
            self.sources.append((ed, btn))

        note('也可以自己另存成文件后从这里导入（三个源的 JSON 都能直接导入）：')
        self.status = QLabel()
        self.status.setObjectName('setLabel')
        lay.addWidget(self.status)
        row2 = QHBoxLayout()
        pick = QPushButton('选择文件导入…')
        pick.setObjectName('setBtn')
        pick.clicked.connect(lambda: (self.close(), on_pick()))
        row2.addWidget(pick)
        row2.addStretch(1)
        open_dir = QPushButton('打开下载目录')
        open_dir.setObjectName('setBtn')
        open_dir.setToolTip('「下载并导入」抓到的年份 JSON 都保存在这个目录')
        open_dir.clicked.connect(self._open_download_dir)
        row2.addWidget(open_dir)
        lay.addLayout(row2)
        self.setFixedWidth(sc(470))

        # 与设置窗口一致：默认居中在面板所在屏幕的可用区
        self.adjustSize()
        scr = QApplication.screenAt(panel.frameGeometry().center()) or QApplication.primaryScreen()
        ag = scr.availableGeometry()
        g = self.frameGeometry()
        g.moveCenter(ag.center())
        self.move(g.topLeft())

    def _download(self, on_download, name, edit, btn):
        """点「下载并导入」：按钮 loading + 禁用，后台抓取结束后恢复（结果写调试日志）。"""
        url = edit.text().strip()
        if not url:
            self.status.setText('URL 不能为空')
            return
        btn.setEnabled(False)
        btn.setText('下载中…')
        if on_download(name, url, lambda: self._download_done(btn)):
            self.status.setText('正在下载 %s…' % name)
        else:
            self.status.setText('上一次下载还没结束，本次随它一起完成')

    def _open_download_dir(self):
        d = sysutil.download_dir()
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    def _download_done(self, btn):
        try:
            btn.setEnabled(True)
            btn.setText('下载并导入')
        except RuntimeError:
            pass  # 导入窗已关，按钮随窗口销毁

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
    on_fetch/on_import 为节假日数据回调（由入口提供）。
    改动即时生效并写入 config.json。"""
    def __init__(self, panel, on_fetch, on_import, boxmgr=None):
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

        def commit_single(ed, key, normalize):
            """单值框：输入中途能解析才即时落盘；失焦时归一化，解析不了（含清空）就存空。"""
            v = parse_time_text(ed.text())
            if v is None:
                if not normalize:
                    return
                v = ''      # 留空 = 不设这个时间点（面板也就整块不显示倒计时）
            cfg.set(key, v)
            if normalize and ed.text() != v:
                ed.setText(v)

        def commit_noon(normalize=False):
            """午休两个框合并成一个 'HH:mm-HH:mm' 落盘：两端都有效才算数，否则（含整体清空）存空。
            输入中途不写半截状态；失焦才归一化，把解析不了的框清成空，能解析的留着等用户补齐另一端。"""
            a, b = parse_time_text(noon_a.text()), parse_time_text(noon_b.text())
            ok = bool(a and b)
            if not ok and not normalize:
                return
            cfg.set('off_noon', '%s-%s' % (a, b) if ok else '')
            if normalize:
                for ed, v in ((noon_a, a or ''), (noon_b, b or '')):
                    if ed.text() != v:
                        ed.setText(v)

        # 午休：开始 – 结束（留空即不设，两个框都空着显示）
        rng = parse_noon_range(cfg.data.get('off_noon')) or ('', '')
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
        noon_a.editingFinished.connect(lambda: commit_noon(True))
        noon_b.editingFinished.connect(lambda: commit_noon(True))

        # 下班（同样可留空）
        evening_row, evening = time_field(parse_time_text(cfg.data.get('off_evening')) or '')
        form.addRow(row_label('下班时间'), evening_row)
        evening.textChanged.connect(lambda _t: commit_single(evening, 'off_evening', False))
        evening.editingFinished.connect(lambda: commit_single(evening, 'off_evening', True))

        # 开机自启
        auto = QCheckBox('登录 Windows 后自动启动')
        auto.setChecked(bool(sysutil.autostart_get()))
        auto.toggled.connect(lambda on: sysutil.autostart_set() if on else sysutil.autostart_remove())
        form.addRow(row_label('开机自启'), auto)

        # 桌面格子
        sep_b = QFrame()
        sep_b.setObjectName('setSep')
        sep_b.setFixedHeight(1)
        form.addRow(sep_b)
        dbl = QCheckBox('双击桌面显示 / 隐藏格子')
        dbl.setChecked(bool(cfg.data.get('box_dblclick', True)))

        def commit_dblclick(on):
            cfg.set('box_dblclick', bool(on))
            if boxmgr is not None:
                boxmgr.set_dblclick_enabled(bool(on))
        dbl.toggled.connect(commit_dblclick)
        form.addRow(row_label('格子'), dbl)

        # 节假日数据
        sep = QFrame()
        sep.setObjectName('setSep')
        sep.setFixedHeight(1)
        form.addRow(sep)
        holiday_row = QHBoxLayout()
        holiday_row.setSpacing(sc(8))
        self._on_fetch = on_fetch
        self.btn_fetch = QPushButton('联网更新')
        self.btn_fetch.setObjectName('setBtn')
        self.btn_fetch.clicked.connect(self._fetch_clicked)
        holiday_row.addWidget(self.btn_fetch)
        b = QPushButton('导入 JSON…')
        b.setObjectName('setBtn')
        b.clicked.connect(on_import)
        holiday_row.addWidget(b)
        form.addRow(row_label('节假日'), holiday_row)

        # 保存按钮（改动即时生效，点击即确认并关闭）；左下角版本号与关于窗/安装程序一致
        save_row = QHBoxLayout()
        save_row.setContentsMargins(0, sc(12), sc(4), 0)
        ver = QLabel('v%s' % APP_VERSION)
        ver.setObjectName('setLabel')   # 借用表单标签的弱化色
        save_row.addWidget(ver)
        save_row.addStretch(1)
        save = QPushButton('保存')
        save.setObjectName('setSave')
        save.setCursor(Qt.PointingHandCursor)
        save.setDefault(True)
        save.clicked.connect(self.accept)
        save_row.addWidget(save)
        lay.addLayout(save_row)

        # 默认居中在屏幕可用区（不贴着面板：面板常停右下角，跟着它会被挤到屏幕边上）
        # 面板在哪个屏幕就居中到哪个屏幕，多显示器下对话框跟人待的那块屏一致
        self.adjustSize()
        scr = QApplication.screenAt(panel.frameGeometry().center()) or QApplication.primaryScreen()
        ag = scr.availableGeometry()
        g = self.frameGeometry()
        g.moveCenter(ag.center())
        self.move(g.topLeft())

    def _fetch_clicked(self):
        """联网更新：点击即 loading + 禁用，后台抓取结束后恢复（无论成败，结果写调试日志）。"""
        self.btn_fetch.setEnabled(False)
        self.btn_fetch.setText('更新中…')
        self._on_fetch(self._fetch_done)

    def _fetch_done(self):
        try:
            self.btn_fetch.setEnabled(True)
            self.btn_fetch.setText('联网更新')
        except RuntimeError:
            pass  # 设置窗已关，按钮随窗口销毁

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
        # 按锚点所在屏幕的可用区夹取，多显示器下弹层才不会被拉回主屏边缘
        scr = QApplication.screenAt(anchor.mapToGlobal(anchor.rect().center())) or QApplication.primaryScreen()
        ag = scr.availableGeometry()
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


class AboutDialog(QDialog):
    """「关于」弹窗：图标 + 简介 + 版本号 + GitHub 链接，样式跟随当前主题。
    版本号与开源地址取自 version.py（发新版只改那个文件）。"""

    def __init__(self, panel):
        super(AboutDialog, self).__init__(panel)
        self.setObjectName('settingsDlg')
        self.setWindowTitle('关于')
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self._drag = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = QWidget()
        card.setObjectName('settingsPanel')
        root.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(sc(16), sc(6), sc(14), sc(14))
        lay.setSpacing(0)

        # 标题栏（可拖动）
        self.titlebar = QFrame()
        self.titlebar.setFixedHeight(sc(34))
        tb = QHBoxLayout(self.titlebar)
        tb.setContentsMargins(0, 0, 0, 0)
        title = QLabel('关于')
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

        # 图标 + 名称 / 版本
        head = QHBoxLayout()
        head.setContentsMargins(sc(2), sc(4), sc(6), sc(4))
        head.setSpacing(sc(12))
        icon = QLabel()
        icon.setPixmap(make_icon().pixmap(sc(48), sc(48)))
        icon.setFixedSize(sc(48), sc(48))
        head.addWidget(icon)
        info = QVBoxLayout()
        info.setSpacing(sc(4))
        name = QLabel('Zviber 桌面日历')
        name.setObjectName('setTitle')
        info.addWidget(name)
        ver = QLabel('版本 v%s' % APP_VERSION)
        ver.setObjectName('setLabel')
        info.addWidget(ver)
        info.addStretch(1)
        head.addLayout(info, 1)
        lay.addLayout(head)

        # 简要介绍
        intro = QLabel('Windows 桌面悬浮面板：日历 + 待办，深色 / 浅色双主题，内置法定节假日与农历。')
        intro.setObjectName('setLabel')
        intro.setWordWrap(True)
        intro.setContentsMargins(sc(2), sc(2), sc(6), sc(6))
        lay.addWidget(intro)

        # GitHub 地址（可点击跳转）；链接颜色随主题，写在行内样式里（QSS 管不到 <a>）
        accent = '#0067c0' if resolve_theme(panel._theme) == 'mica' else '#e8a33d'
        gh = QHBoxLayout()
        gh.setContentsMargins(sc(2), 0, sc(6), 0)
        gh.setSpacing(sc(8))
        gh_label = QLabel('开源地址')
        gh_label.setObjectName('setLabel')
        gh.addWidget(gh_label)
        link = QLabel('<a href="%s" style="color:%s; text-decoration:none;">%s</a>'
                      % (GITHUB_URL, accent, GITHUB_URL))
        link.setObjectName('setUrl')
        link.setOpenExternalLinks(True)
        link.setCursor(Qt.PointingHandCursor)
        link.setToolTip('在浏览器中打开')
        gh.addWidget(link)
        gh.addStretch(1)
        lay.addLayout(gh)

        # 右下角关闭按钮
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, sc(12), sc(4), 0)
        btn_row.addStretch(1)
        done = QPushButton('关闭')
        done.setObjectName('setSave')
        done.setCursor(Qt.PointingHandCursor)
        done.setDefault(True)
        done.clicked.connect(self.accept)
        btn_row.addWidget(done)
        lay.addLayout(btn_row)

        self.setFixedWidth(sc(360))
        # 与设置窗口一致：默认居中在面板所在屏幕的可用区
        self.adjustSize()
        scr = QApplication.screenAt(panel.frameGeometry().center()) or QApplication.primaryScreen()
        ag = scr.availableGeometry()
        g = self.frameGeometry()
        g.moveCenter(ag.center())
        self.move(g.topLeft())

    def showEvent(self, e):
        super(AboutDialog, self).showEvent(e)
        round_corners(self)

    def resizeEvent(self, e):
        super(AboutDialog, self).resizeEvent(e)
        round_corners(self)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.pos().y() < self.titlebar.height():
            self._drag = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()
        else:
            super(AboutDialog, self).mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag)
            e.accept()
        else:
            super(AboutDialog, self).mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        super(AboutDialog, self).mouseReleaseEvent(e)


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

    def __init__(self, cfg, hstore, tstore):
        super(FloatingPanel, self).__init__()
        self.cfg = cfg
        self.cn_font, self.num_font = pick_fonts()
        set_num_font(self.num_font)
        # 不用 WA_TranslucentBackground：分层窗口禁用 ClearType，文字灰糊。
        # 不透明窗口 + Win11 DWM 圆角（Win7/10 降级为圆角遮罩），文字锐利度对齐系统组件。
        # 桌面格子模式：不置顶，可被其它窗口覆盖；移动靠顶部栏（悬浮滑出）或日历左侧时分秒拖拽。
        # 桌面层级（见 _ensure_band）：属主设为桌面图标窗加入「桌面带」，Win+D 收不走；
        # z-order 由看门狗维护在桌面带之上、应用窗口之下
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self._desk_pinned = False   # True = 已归属桌面带（SHELLDLL_DefView 的属主 popup）
        self._desk_surface = None   # 探测到的第三方桌面表层（沉底锚点缓存）
        self._floating = False      # True = 被点击激活浮起到应用窗口之上，失焦后需要沉回
        self._drag = None           # 窗口拖拽偏移（globalPos - topLeft）；None = 未在拖拽
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

        # 顶部栏：独立顶层小窗，默认收起。悬浮展开只改栏窗自己的几何——主窗口不重排、
        # 不重绘，不会抖动。无属主（子窗口永远压在父窗口之上）：栏窗要待在面板之下，
        # 底边探进面板顶边下方被遮住，才能和面板合成一张卡片；显隐由面板手动同步。
        self.titlebar = QFrame(None, Qt.FramelessWindowHint | Qt.Tool)
        self.titlebar.setObjectName('titlebar')
        self.titlebar.installEventFilter(self)
        tb = QHBoxLayout(self.titlebar)
        tb.setContentsMargins(sc(14), sc(8), sc(10), sc(2))
        tb.setSpacing(6)
        # 栏窗高度由展开动画逐帧设置，不能被子控件的最小高度顶住
        tb.setSizeConstraint(QLayout.SetNoConstraint)

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

        self._tb_anim = QVariantAnimation(self)
        self._tb_anim.setDuration(160)
        self._tb_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._tb_anim.valueChanged.connect(self._set_tb_height)
        self._tb_anim.finished.connect(self._tb_anim_done)

        # 内容：单栏（堆叠）/ 双栏（并排）
        self.cal = CalendarWidget(hstore, cfg, resolve_theme(cfg.theme))
        self.todo = TodoWidget(tstore)
        self.todo.set_theme(resolve_theme(cfg.theme))
        # 顶部栏平时隐藏：日历左侧的时分秒 / 日期行充当窗口拖拽把手
        self.cal.clock_hm.installEventFilter(self)
        self.cal.sub.installEventFilter(self)

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
        pl.addLayout(self.content, 1)          # 先装进父控件再加页面：否则第一个页面成为当前页，
        self.content.addWidget(self.single_page)   # 会被 QStackedLayout 立刻 show()，无父状态下
        self.content.addWidget(self.dual_page)     # 闪出一个默认大小的白框（启动白闪的根因）

        self._today = date.today()
        self._midnight = QTimer(self)
        self._midnight.timeout.connect(self._check_date)
        self._midnight.start(30000)

        self._dual = None  # None 而非 False：避免 set_dual 的“无变化短路”跳过首次布局/定尺寸
        self._theme = cfg.theme
        self._icon_dir = _indicator_icons()
        self.apply_theme(cfg.theme, save=False)
        if cfg.dual:
            self.set_dual(True, save=False)
        else:
            self.set_dual(False, save=False)
            self.set_tab(int(cfg.tab or 0), save=False)

        # 桌面层级：归属桌面带（Win+D 免疫）+ 看门狗维护 z-order 与挂接健康
        self._ensure_band()
        # WinEvent 钩子：桌面整理软件的表层重建时立刻把面板抬回（等看门狗会闪 0.3~0.6s）
        self._win_evt_cb = _WINEVENTPROC(self._on_win_event)   # 必须留引用，防 GC
        self._win_evt_hook = _u32.SetWinEventHook(_EVENT_SHOW, _EVENT_REORDER,
                                                  None, self._win_evt_cb, 0, 0, 0)
        QApplication.instance().aboutToQuit.connect(self._unhook_win_event)
        self._sink_timer = QTimer(self)
        self._sink_timer.timeout.connect(self._desktop_mode_tick)
        self._sink_timer.start(500)   # 桌面整理软件会在 Win+D 等时机重排表层，要快些跟上
        QApplication.instance().focusChanged.connect(self._grab_input_focus)
        QTimer.singleShot(800, lambda: sink_to_desktop(self))   # 首次沉底

    # --- 桌面层级 ---
    def _ensure_band(self):
        """确保面板归属桌面带（属主 = 桌面图标窗 SHELLDLL_DefView）。挂接丢失时补挂。"""
        if self._drag is not None:
            return   # 拖拽期间故意脱离桌面带（见 eventFilter），别补挂
        hwnd = int(self.winId())
        progman = _u32.FindWindowW('Progman', None)
        if not progman:
            return
        if _u32.GetAncestor(hwnd, _GA_ROOT) != progman:
            self._desk_pinned = pin_to_desktop(self)
        # 顶部栏窗同属桌面带：它是无属主的普通顶层窗口，不挂带的话悬停弹出时会
        # 盖住压在面板之上的应用窗口（面板被部分遮挡时尤其明显）
        if _u32.GetAncestor(int(self.titlebar.winId()), _GA_ROOT) != progman:
            pin_to_desktop(self.titlebar)

    def _desktop_mode_tick(self):
        hwnd = int(self.winId())
        if not _u32.IsWindow(hwnd):
            QApplication.instance().quit()   # 桌面（DefView）被销毁会连坐销毁属主窗口，无法恢复
            return
        self._ensure_band()
        skip = (hwnd, int(self.titlebar.winId()))
        extra = []
        if self.isVisible():
            extra.append((self.x() + self.width() // 2, self.y() + self.height() // 2))
        self._desk_surface, _t = probe_desktop(skip=skip, extra=extra)
        covered = self._covered_by_surface()
        _dbg('tick: pinned=%s surface=%s covered=%s active=%s undermouse=%s' % (
            self._desk_pinned, self._desk_surface, covered, self.isActiveWindow(), self.underMouse()))
        if covered and self._drag is None:
            sink_to_desktop(self, self._desk_surface)   # 被桌面表层压住：无条件抬上来
        elif not covered:
            self._ensure_desktop_level()

    def _on_win_event(self, _hook, event, hwnd, idObject, _idChild, _thread, _ts):
        """桌面带内窗口的 SHOW / 容器 REORDER 事件回调。只做轻量过滤，
        真正的抬回动作丢回事件循环（钩子里直接动 z-order 有风险）。"""
        try:
            if not hwnd or not self.isVisible() or self._drag is not None:
                return
            if hwnd == int(self.winId()) or hwnd == int(self.titlebar.winId()):
                return
            if idObject not in (0, -4):   # 只看窗口本身 / 客户区级别
                return
            cls = _class_name(hwnd)
            if cls in _PROG_FAMILY:
                if event != _EVENT_REORDER:
                    return
            else:
                sw, sh = _u32.GetSystemMetrics(0), _u32.GetSystemMetrics(1)
                if not _is_desktop_surface(hwnd, sw, sh):
                    return
            QTimer.singleShot(0, self._lift_if_covered)
        except Exception:
            pass

    def _unhook_win_event(self):
        if self._win_evt_hook:
            _u32.UnhookWinEvent(self._win_evt_hook)
            self._win_evt_hook = None

    def _lift_if_covered(self):
        """表层重排后的即时抬回：只抬不换锚点；没被压住就不动（我们自己的沉底也会触发
        REORDER 事件，靠这道判断防自激回路）。"""
        if self._covered_by_surface():
            _dbg('lift: 表层重排事件触发抬回')
            sink_to_desktop(self, self._desk_surface)

    def _covered_by_surface(self):
        """面板中心被桌面整理软件的表层压住（看不见也点不到）的判定。
        此状态绝非用户所愿，必须无条件抬回——不能走 _ensure_desktop_level 的空闲守卫
        （光标停在面板上时 underMouse 会因收不到 Leave 事件而过期为真，把沉底永久挡住）。"""
        if not self.isVisible():
            return False
        h = _u32.WindowFromPoint(wintypes.POINT(self.x() + self.width() // 2,
                                                self.y() + self.height() // 2))
        mine = (int(self.winId()), int(self.titlebar.winId()))
        sw, sh = _u32.GetSystemMetrics(0), _u32.GetSystemMetrics(1)
        while h:
            if h in mine or _class_name(h) in _PROG_FAMILY:
                return False
            if _is_desktop_surface(h, sw, sh):
                return True
            h = _u32.GetParent(h)
        return False

    def _grab_input_focus(self, _old, new):
        """桌面带窗口的键盘焦点兜底（Win7/10 用；Win11 实测点击即自然获得焦点）。
        焦点不在面板上时不动。"""
        if not self._desk_pinned or new is None or new.window() is not self:
            return
        try:
            hwnd = int(self.winId())
            cur = ctypes.windll.kernel32.GetCurrentThreadId()
            tid = _u32.GetWindowThreadProcessId(_u32.GetForegroundWindow(), None)
            if tid and tid != cur:
                _u32.AttachThreadInput(cur, tid, True)
                _u32.SetFocus(hwnd)
                _u32.AttachThreadInput(cur, tid, False)
        except Exception:
            pass


    def event(self, e):
        if e.type() == QEvent.WindowActivate:
            self._floating = True    # 点击激活会浮到应用窗口之上，记下待沉
        elif e.type() == QEvent.WindowDeactivate:
            QTimer.singleShot(300, self._ensure_desktop_level)   # 失焦后压回桌面层
        return super(FloatingPanel, self).event(e)

    def _ensure_desktop_level(self):
        """面板被点击激活后会浮到普通窗口之上；空闲（未激活/未悬停/未拖拽）时压回桌面层，
        让其它窗口可以正常遮挡它。正在使用时不动，避免打字/拖拽途中被其它窗口盖住。
        没浮起过就不动——z-order 变动会触发桌面整理软件的表层反压，空发会振荡闪烁。"""
        if (not self._floating or not self.isVisible() or self.isActiveWindow() or self.underMouse()
                or self._drag is not None or self.titlebar.underMouse()):
            return
        self._floating = False
        sink_to_desktop(self, self._desk_surface)
        if self.titlebar.isVisible():
            _place_below(self.titlebar, self)   # 面板沉层后栏窗要重新压回它正下方

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


    # --- 主题 ---
    def apply_theme(self, key, save=True):
        self._theme = key  # 用户选择，可能是 auto
        real = resolve_theme(key)
        QApplication.instance().setStyleSheet(build_qss(real, self.cn_font, self.num_font, ui_scale(), self._icon_dir))
        self.cal.set_theme(real)
        self.todo.set_theme(real)
        if save:
            self.cfg.set('theme', key)


    def showEvent(self, e):
        super(FloatingPanel, self).showEvent(e)
        self._round_corners()

    def hideEvent(self, e):
        self.titlebar.hide()   # 栏窗无属主，不随面板隐藏，手动带上
        super(FloatingPanel, self).hideEvent(e)

    def moveEvent(self, e):
        super(FloatingPanel, self).moveEvent(e)
        self._sync_bar()

    def resizeEvent(self, e):
        super(FloatingPanel, self).resizeEvent(e)
        self._sync_bar()
        self._round_corners()

    def _sync_bar(self):
        """栏窗贴住面板顶边（底边探进一个圆角半径，藏在面板下面）：拖拽移动、
        单双栏变宽时跟随；遮罩随尺寸重贴；z-order 重新压回面板之下。"""
        if self.titlebar.isVisible():
            ov = int(bar_corner_radius(self.titlebar))
            self.titlebar.setGeometry(self.x(), self.y() - self.titlebar.height() + ov,
                                      self.width(), self.titlebar.height())
            round_bar_top(self.titlebar)
            _place_below(self.titlebar, self)

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

    # --- 顶部栏：默认收起，悬浮时从面板顶边向上展开 ---
    def enterEvent(self, e):
        _dbg('enterEvent')
        self._slide_titlebar(True)
        super(FloatingPanel, self).enterEvent(e)

    def leaveEvent(self, e):
        self._schedule_hover_check()
        super(FloatingPanel, self).leaveEvent(e)

    def _schedule_hover_check(self):
        # 光标从面板挪到展开栏会先触发面板 leave：等一拍看落点再决定收不收
        QTimer.singleShot(150, self._check_hover)

    def _check_hover(self):
        pos = QCursor.pos()
        in_panel = self.geometry().contains(pos)
        in_bar = self.titlebar.geometry().contains(pos)
        _dbg('check_hover pos=(%d,%d) in_panel=%s in_bar=%s' % (pos.x(), pos.y(), in_panel, in_bar))
        if not in_panel and not in_bar:
            self._slide_titlebar(False)

    def _slide_titlebar(self, on):
        """栏窗高 0↔H 动画（从当前高度续滑，中途反向不打断）；只改栏窗几何，主窗口不动。"""
        _dbg('slide_titlebar on=%s panelVis=%s tbVis=%s' % (on, self.isVisible(), self.titlebar.isVisible()))
        if on and not self.isVisible():
            return   # 面板已收起就不再弹出栏窗（面板隐藏后光标划过原位置也会触发栏窗 Enter）
        self._tb_anim.stop()
        ov = int(bar_corner_radius(self.titlebar))
        cur = self.titlebar.height() - ov if self.titlebar.isVisible() else 0   # 栏高含底边探进量
        self._tb_anim.setStartValue(max(0, cur))
        self._tb_anim.setEndValue(sc(42) if on else 0)
        if on:
            self.titlebar.show()
            _place_below(self.titlebar, self)   # 栏窗待在面板之下，探进的底边才被遮住
        self._tb_anim.start()

    def _set_tb_height(self, h):
        # 可见高度 h：底边探进面板一个圆角半径（被面板遮住，不露接缝）；
        # 动画中高度每帧都变，遮罩跟着重贴
        h = int(h)
        ov = int(bar_corner_radius(self.titlebar))
        self.titlebar.setGeometry(self.x(), self.y() - h, self.width(), h + ov)
        round_bar_top(self.titlebar)

    def _tb_anim_done(self):
        _dbg('tb_anim_done endValue=%s tbVis=%s' % (self._tb_anim.endValue(), self.titlebar.isVisible()))
        if self._tb_anim.endValue() == 0:
            self.titlebar.hide()

    def eventFilter(self, obj, ev):
        """时分秒 / 日期行和展开的顶部栏都是窗口拖拽把手；栏窗的悬浮进出也在这里接力。"""
        t = ev.type()
        if obj is self.titlebar and t == QEvent.WindowActivate:
            _place_below(self.titlebar, self)   # 激活会浮到面板之上，压回去
            return False
        if obj is self.titlebar and t == QEvent.Enter:
            self._slide_titlebar(True)
            return False
        if obj is self.titlebar and t == QEvent.Leave:
            self._schedule_hover_check()
            return False
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            self._drag = ev.globalPos() - self.frameGeometry().topLeft()
            unpin_from_desktop(self)   # 拖拽期间临时退出桌面带：普通窗口移动不会触发表层反压
            unpin_from_desktop(self.titlebar)   # 栏窗一起退出：拖拽中面板浮起，栏窗留带内会被应用盖住
            self._desk_pinned = False
            return True
        if t == QEvent.MouseMove and self._drag is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPos() - self._drag)
            return True
        if t == QEvent.MouseButtonRelease and self._drag is not None:
            self._drag = None
            self._save_pos()
            self._desk_pinned = pin_to_desktop(self)   # 归位：重新归属桌面带并沉到表层之上
            pin_to_desktop(self.titlebar)
            sink_to_desktop(self, self._desk_surface)
            if self.titlebar.isVisible():
                _place_below(self.titlebar, self)
            return True
        return super(FloatingPanel, self).eventFilter(obj, ev)

    def _save_pos(self):
        ag = QApplication.primaryScreen().availableGeometry()
        self.cfg.data['pos_screen'] = [ag.width(), ag.height()]
        self.cfg.set('pos', [self.x(), self.y()])

    # --- 其他 ---
    def close_panel(self):
        """收起面板：顶部栏是独立顶层小窗，必须跟着一起收（否则会残留在屏幕上）。"""
        self._tb_anim.stop()
        self.titlebar.hide()
        self.hide()

    def toggle_visible(self):
        if self.isVisible():
            self.close_panel()
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


























