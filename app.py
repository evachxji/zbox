# -*- coding: utf-8 -*-
"""Zviber 桌面悬浮面板：日历 + 待办。PyQt5，兼容 Win7/10/11、Python 3.8+。"""
import ctypes
import json
import os
import sys
from datetime import date, datetime, timedelta

from PyQt5.QtCore import (Qt, QTimer, QSize, QPoint, QPointF, QRectF, QDate, QTime,
                          pyqtSignal, QEvent, QPropertyAnimation, QEasingCurve)
from PyQt5.QtGui import (QFont, QFontDatabase, QPainter, QColor, QPixmap, QIcon, QPainterPath,
                         QRegion, QPen)
from PyQt5.QtWidgets import (QWidget, QFrame, QLabel, QToolButton, QVBoxLayout, QHBoxLayout,
                             QGridLayout, QStackedLayout, QListWidget,
                             QListWidgetItem, QLineEdit, QMenu, QApplication, QDialog,
                             QFormLayout, QCheckBox, QRadioButton, QTimeEdit, QPushButton, QCalendarWidget)

import calendar_data as cd
import sysutil
from themes import THEMES, THEME_ORDER, build_qss

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


def make_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor('#1e2028'))
    p.drawRoundedRect(2, 2, 60, 60, 15, 15)
    p.setBrush(QColor('#e8a33d'))
    p.drawRoundedRect(6, 6, 52, 52, 12, 12)
    p.setPen(QColor('#1a1610'))
    p.setFont(QFont('Arial', 24, QFont.Bold))
    p.drawText(pm.rect(), Qt.AlignCenter, str(date.today().day))
    p.end()
    return QIcon(pm)


DUE_ICON_COLORS = {'nocturne': '#8d8a82', 'mica': '#8a8a90'}


def _dbg(msg):
    """临时调试：记录日期按钮点击链路。定位完成后移除。"""
    try:
        p = os.path.join(os.environ.get('APPDATA', '.'), 'ZviberPanel', 'debug_due.log')
        with open(p, 'a', encoding='utf-8') as f:
            f.write('%s %s\n' % (datetime.now().strftime('%H:%M:%S.%f')[:-3], msg))
    except Exception:
        pass


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


def due_chip(due_str, theme_key):
    """截止日期 -> (标签文本, 是否逾期)，展现形式对齐 designs/ 三套风格稿。"""
    try:
        d = datetime.strptime(due_str, '%Y-%m-%d').date()
    except Exception:
        return None, False
    delta = (d - date.today()).days
    if theme_key == 'nocturne':
        if delta < 0:
            return ('D%d' % delta, True)
        if delta == 0:
            return ('TODAY', False)
        return (d.strftime('%m.%d'), False)
    if delta < 0:
        return ('逾期 %d 天' % -delta if theme_key == 'mica' else '逾期%d天' % -delta, True)
    if delta == 0:
        return ('今天', False)
    if theme_key == 'mica':
        return ('%d月%d日' % (d.month, d.day), False)
    return ('%d.%d' % (d.month, d.day), False)


class Config(object):
    def __init__(self, path):
        self.path = path
        self.data = {'theme': THEME_ORDER[0], 'dual': False, 'tab': 0, 'pos': None,
                     'off_noon': '12:00', 'off_evening': '18:00'}
        self.load()

    def load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                self.data.update(json.load(f))
        except Exception:
            pass
        if self.data.get('theme') not in THEMES:
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
        self.num.setFixedSize(sc(38), sc(38))
        if _NUM_FONT['name']:
            f = QFont(_NUM_FONT['name'])
            f.setPixelSize(sc(_NUM_FONT['size']))
            f.setWeight(_NUM_FONT['weight'])
            self.num.setFont(f)
        self.sub = QLabel(self)
        self.sub.setObjectName('daySub')
        self.sub.setAlignment(Qt.AlignCenter)
        self.badge = QLabel(self)
        self.badge.setObjectName('badge')
        self.badge.setFixedSize(sc(6), sc(6))
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
        self.badge.setGeometry(self.width() - w - sc(4), sc(4), w, w)

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
            self.badge.setText('')
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
        """距离下一个下班节点（午休/晚上）的倒计时，休息日不显示。"""
        _, kind = self.store.info(t)
        if kind == 'off' or (t.weekday() >= 5 and kind != 'work'):
            return '今天休息'
        now = datetime.now()
        for key, label, dflt in (('off_noon', '午休', '12:00'), ('off_evening', '下班', '18:00')):
            try:
                hh, mm = (self.cfg.data.get(key) or dflt).split(':')
                target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            except Exception:
                continue
            if target > now:
                secs = (target - now).seconds
                total_min = -(-secs // 60)  # 向上取整
                return '距%s %d:%02d' % (label, total_min // 60, total_min % 60)
        return '今天已下班'

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
            self.viewport.pixmaps[n] = _page_pixmap(gone)

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
        f = tx.font()
        f.setStrikeOut(it['done'])
        tx.setFont(f)
        lay.addWidget(tx, 1)
        if it.get('due') and not it['done']:
            text, late = due_chip(it['due'], self.theme_key)
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
        self._update_count()

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
        ed.editingFinished.connect(lambda: self._commit(li, ed, item_id))
        hl.addWidget(ed, 1)
        btn = QToolButton()
        btn.setObjectName('todoDateBtn')
        btn.setFocusPolicy(Qt.NoFocus)   # 不抢焦点，避免触发编辑框的失焦提交
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip('设置截止时间')
        btn.setFixedSize(sc(32), sc(30))
        btn.setIcon(make_cal_icon(DUE_ICON_COLORS.get(self.theme_key, '#8a8a90')))
        btn.setIconSize(QSize(sc(17), sc(17)))
        btn.clicked.connect(lambda: (_dbg('date btn CLICKED'), self._pick_due(btn)))
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
                self._due_btn.setText('%d/%d' % (d.month, d.day))
                self._due_btn.setFixedWidth(sc(46))
                return
            except Exception:
                pass
        self._due_btn.setText('')

    def _pick_due(self, btn):
        _dbg('_pick_due enter: editing=%s picking=%s' % (self._editing, getattr(self, '_picking', None)))
        if not self._editing or getattr(self, '_picking', False):
            _dbg('_pick_due EARLY RETURN')
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
        _dbg('popup shown: visible=%s pos=(%d,%d) size=%dx%d btnGlobal=%s' % (
            pop.isVisible(), x, y, pop.width(), pop.height(), pos))

    def _due_picked(self, d):
        if not self._editing:
            return   # 编辑会话已结束（编辑器控件已随 rebuild 销毁），忽略迟到回调
        self._edit_due = d.isoformat() if d else None
        self._just_picked = True
        self._refresh_due_btn()

    def _popup_closed(self):
        _dbg('popup closed')
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
        li, ed, item_id = self._editor
        self._commit(li, ed, item_id)

    def _commit(self, li, ed, item_id):
        _dbg('_commit: editing=%s picking=%s text=%r' % (
            self._editing, getattr(self, '_picking', None), ed.text()[:20]))
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


class SettingsDialog(QDialog):
    """齿轮按钮弹出的无边框设置窗口，样式跟随当前主题（themes.py #settingsPanel 区段）。
    on_fetch/on_import/on_reset 为节假日数据回调（由入口提供，以便复用托盘通知）。
    改动即时生效并写入 config.json。"""
    def __init__(self, panel, on_fetch, on_import, on_reset):
        super(SettingsDialog, self).__init__(panel)
        self.setObjectName('settingsDlg')
        self.setWindowTitle('设置')
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
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
        for key in THEME_ORDER:
            r = QRadioButton(THEMES[key]['name'])
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

        # 下班倒计时（时间选择器，存 HH:mm 与旧配置兼容）
        for key, label, dflt in (('off_noon', '午休时间', '12:00'), ('off_evening', '下班时间', '18:00')):
            te = QTimeEdit()
            te.setDisplayFormat('HH:mm')
            te.setButtonSymbols(QTimeEdit.NoButtons)  # QSS 下原生箭头不渲染，用自建步进按钮
            t = QTime.fromString(cfg.data.get(key) or dflt, 'HH:mm')
            te.setTime(t if t.isValid() else QTime.fromString(dflt, 'HH:mm'))
            te.timeChanged.connect(lambda qt, k=key: cfg.set(k, qt.toString('HH:mm')))
            field = QWidget()
            field.setObjectName('timeField')
            field.setFocusProxy(te)
            fb = QHBoxLayout(field)
            fb.setContentsMargins(0, 0, sc(3), 0)
            fb.setSpacing(0)
            fb.addWidget(te, 1)
            steps = QVBoxLayout()
            steps.setSpacing(0)
            for arrow, fn in (('▲', te.stepUp), ('▼', te.stepDown)):
                b = QToolButton()
                b.setObjectName('timeStep')
                b.setText(arrow)
                b.setFixedSize(sc(16), sc(13))
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(fn)
                steps.addWidget(b)
            fb.addLayout(steps)
            field.setFixedWidth(sc(96))
            form.addRow(row_label(label), field)

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
        for text, fn in (('联网更新', on_fetch), ('导入 JSON…', on_import), ('恢复内置', on_reset)):
            b = QPushButton(text)
            b.setObjectName('setBtn')
            b.clicked.connect(fn)
            holiday_row.addWidget(b)
        form.addRow(row_label('节假日'), holiday_row)

        # 默认停靠在主面板上方右对齐，溢出屏幕上方则改到下方
        self.adjustSize()
        ag = QApplication.primaryScreen().availableGeometry()
        geo = panel.frameGeometry()
        x = min(max(geo.right() - self.width(), ag.left()), ag.right() - self.width())
        y = geo.top() - self.height() - sc(8)
        if y < ag.top():
            y = min(geo.bottom() + sc(8), ag.bottom() - self.height())
        self.move(x, y)

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
        bx.setSpacing(sc(6 if cfg.theme == 'nocturne' else 2))
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
        self.cal = CalendarWidget(hstore, cfg, cfg.theme)
        self.todo = TodoWidget(tstore)
        self.todo.set_theme(cfg.theme)

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
        self.apply_theme(cfg.theme, save=False)
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
            for b in self.tabs:
                b.setProperty('active', 'true')
                b.style().unpolish(b)
                b.style().polish(b)
        else:
            self.dual_box.removeWidget(self.cal)
            self.dual_box.removeWidget(self.todo)
            self.single_stack.addWidget(self.cal)
            self.single_stack.addWidget(self.todo)
            self.todo.set_solo(True)
            self.content.setCurrentWidget(self.single_page)
            self.set_tab(self.single_stack.currentIndex() if self.single_stack.currentWidget() in (self.cal, self.todo) else 0, save=False)
        self.setFixedSize(sc(DUAL_W if dual else SINGLE_W), sc(PANEL_H))
        self._clamp_to_screen()
        if save:
            self.cfg.set('dual', dual)

    # --- 主题 ---
    def apply_theme(self, key, save=True):
        self._theme = key
        QApplication.instance().setStyleSheet(build_qss(key, self.cn_font, self.num_font, ui_scale()))
        self.cal.set_theme(key)
        self.todo.set_theme(key)
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
        if e.button() == Qt.LeftButton and e.pos().y() < SHADOW + self.titlebar.height():
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



























