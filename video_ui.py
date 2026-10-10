# -*- coding: utf-8 -*-
"""视频解析页 UI：网址解析 → 清晰度选择 → 下载，底栏显示组件版本/更新/卸载。

对照 transfer_ui.py 的模式：功能默认关闭，页面盖门禁层（「启用视频解析」+「?」说明）；
首次开启时后台下载 yt-dlp / ffmpeg 组件（进度显示在门禁层上），就绪后才揭层。
线程纪律同 transfer_ui：video_dl 的回调都发生在后台线程，本模块只经 Signal 回主线程
再动 UI（PySide6 槽里未捕获异常会让进程 abort，故所有槽函数 try/except 兜底）。

交互流：粘贴网址 → 「解析」（后台 yt-dlp -J）→ 视频卡显示标题/时长 + 实际清晰度档位
下拉 → 「下载视频」。网址改动后需重新解析。
"""

import os
import re
import subprocess
import threading
from urllib.request import Request, urlopen
import time

from PySide6.QtCore import Qt, QUrl, Signal, QTimer, QSize
from PySide6.QtGui import (QAction, QActionGroup, QDesktopServices,
                             QPixmap, QPainter, QPainterPath, QPen, QColor, QBrush)
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QToolButton, QPushButton,
                               QVBoxLayout, QHBoxLayout, QLineEdit, QProgressBar,
                               QFileDialog, QMenu, QDialog, QGraphicsBlurEffect,
                               QScrollArea)

import app as ui            # 仅运行期用 ui.sc()；import 期无依赖（app 也 import 本模块）
import glow
import video_dl


def _fmt_mb(n):
    return '%.1f MB' % (n / 1048576.0)


def _fmt_size(n):
    return ('%.2f GB' % (n / 1073741824.0)) if n >= 1073741824 else ('%.1f MB' % (n / 1048576.0))


def _fmt_pair(pct, total):
    """已下载/总大小：yt-dlp 只报百分比与总量，已下载按百分比折算（与总量同单位）。"""
    m = re.match(r'([\d.]+)\s*(\S+)', total or '')
    if not m:
        return total or ''
    return '%.1f%s/%s' % (float(m.group(1)) * pct / 100.0, m.group(2), total)


def _fmt_dur(sec):
    """秒数转 mm:ss / h:mm:ss。"""
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return ''
    if sec <= 0:
        return ''
    if sec < 3600:
        return '%d:%02d' % (sec // 60, sec % 60)
    return '%d:%02d:%02d' % (sec // 3600, sec % 3600 // 60, sec % 60)


_UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}


def _rounded_square_pm(data, side):
    """图片字节 → 居中裁方 → 缩放到 side 边长 → 圆角蒙版；解码失败返回 None。"""
    pm = QPixmap()
    if not pm.loadFromData(data):
        return None
    w, h = pm.width(), pm.height()
    sq = min(w, h)
    s = ui.sc(side)
    pm = pm.copy((w - sq) // 2, (h - sq) // 2, sq, sq).scaled(
        s, s, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    out = QPixmap(s, s)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, s, s, ui.sc(8), ui.sc(8))
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


def _placeholder_pm():
    """封面占位图：64px 圆角方块 + 居中播放三角，半透明中性灰（两主题通用）。
    封面加载前/取不到都显示它，卡片高度恒定不跳动。"""
    s = ui.sc(64)
    out = QPixmap(s, s)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, s, s, ui.sc(8), ui.sc(8))
    p.fillPath(path, QBrush(QColor(128, 128, 128, 28)))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor(128, 128, 128, 120)))
    w, h = ui.sc(20), ui.sc(24)          # 播放三角宽高
    cx, cy = s / 2.0, s / 2.0
    tri = QPainterPath()
    tri.moveTo(cx - w / 2.0 + ui.sc(2), cy - h / 2.0)   # 左顶点右移一点补视觉重心
    tri.lineTo(cx - w / 2.0 + ui.sc(2), cy + h / 2.0)
    tri.lineTo(cx + w / 2.0 + ui.sc(2), cy)
    tri.closeSubpath()
    p.drawPath(tri)
    p.end()
    return out


class _TaskBox(QWidget):
    """任务卡列表容器。QScrollArea 会按内容的 minimumSizeHint 放大容器，
    而横向滚动条禁用 → 内容稍宽时所有卡片右侧被硬裁（单卡时代布局是软压缩，
    没这个问题）。宽度方向的 minSizeHint 归零，恢复软压缩；高度照常传递（垂直滚动需要）。"""

    def minimumSizeHint(self):
        s = super(_TaskBox, self).minimumSizeHint()
        return QSize(0, s.height())


class _Spinner(QWidget):
    """旋转 loading 圆环：yt-dlp 启动握手期（还没出真实进度）顶替「暂停」按钮。"""

    def __init__(self, parent=None):
        super(_Spinner, self).__init__(parent)
        self._angle = 0
        self._color = QColor('#e8a33d')
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(ui.sc(18), ui.sc(18))
        self.hide()

    def set_color(self, color):
        self._color = QColor(color)

    def start(self):
        self._timer.start()
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, e):
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            pen = QPen(self._color, 2)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(self.rect().adjusted(2, 2, -2, -2), self._angle * 16, 270 * 16)
            p.end()
        except Exception:
            pass


class _VideoTask(glow.GlowCard):
    """一个解析/下载任务卡（新任务插到列表顶部，卡片即任务）：
    parsing → parsed ⇄ downloading（暂停/继续）→ done / failed；取消回 parsed。
    回调全在后台线程，经本任务的 Signal 回主线程再碰控件。"""

    sig_parse_done = Signal(bool, object)
    sig_thumb = Signal(bytes)
    sig_dl_progress = Signal(object, str, str, str, str)   # percent(float|None), 阶段, 总大小, 速度, ETA
    sig_dl_done = Signal(bool, str)

    def __init__(self, owner, url):
        super(_VideoTask, self).__init__()
        self.owner = owner            # VideoWidget：cfg / save_dir / _on / _updating / cookie_link
        self.cfg = owner.cfg
        self.url = url
        self.state = 'parsing'        # parsing/parsed/downloading/done/failed
        self._parsed = None
        self._dl = None
        self._dl_paused = False
        self._cancel_requested = False
        self._done_file = ''
        accent = '#e8a33d' if owner.theme_key == 'nocturne' else '#0067c0'
        self.setObjectName('videoCard')
        self.setContextMenuPolicy(Qt.CustomContextMenu)   # 下载中=取消下载；完成态=打开所在目录
        self.customContextMenuRequested.connect(self._card_menu)
        self.set_accent('#6ea8fe')   # 待下载呼吸灯固定淡蓝（完成态无光、下载中彩虹跑马灯）

        cl = QHBoxLayout(self)
        cl.setContentsMargins(ui.sc(10), ui.sc(8), ui.sc(10), ui.sc(8))
        cl.setSpacing(ui.sc(8))
        self.thumb_lab = QLabel()
        self.thumb_lab.setObjectName('videoThumb')
        self.thumb_lab.setFixedSize(ui.sc(64), ui.sc(64))
        self.thumb_lab.setPixmap(_placeholder_pm())   # 封面加载前/取不到都显示占位图
        cl.addWidget(self.thumb_lab, 0, Qt.AlignVCenter)
        info_col = QVBoxLayout()
        info_col.setSpacing(ui.sc(5))
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(ui.sc(4))
        self.title_lab = QLabel()
        self.title_lab.setObjectName('videoTitle')
        title_row.addWidget(self.title_lab, 1)
        self.close_btn = QToolButton()
        self.close_btn.setObjectName('cardCloseBtn')
        self.close_btn.setText('✕')
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip('移除该任务')
        self.close_btn.clicked.connect(self._close_clicked)
        self.close_btn.hide()            # 仅 parsed / done 态显示
        title_row.addWidget(self.close_btn, 0, Qt.AlignTop)
        info_col.addLayout(title_row)
        self.meta_box = QWidget()
        meta_row = QHBoxLayout(self.meta_box)
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(ui.sc(6))
        self.parse_spin = _Spinner()
        self.parse_spin.set_color(accent)
        meta_row.addWidget(self.parse_spin, 0, Qt.AlignVCenter)
        self.parse_lab = QLabel()
        self.parse_lab.setObjectName('videoMeta')
        meta_row.addWidget(self.parse_lab)
        self.fail_lab = QLabel()
        self.fail_lab.setObjectName('videoState')
        meta_row.addWidget(self.fail_lab)
        self.dur_lab = QLabel()
        self.dur_lab.setObjectName('videoMeta')
        meta_row.addWidget(self.dur_lab)
        meta_row.addStretch(1)
        self.quality_btn = QToolButton()
        self.quality_btn.setObjectName('qualityBtn')
        self.quality_btn.setCursor(Qt.PointingHandCursor)
        self.quality_btn.setPopupMode(QToolButton.InstantPopup)
        self.quality_menu = QMenu(self.quality_btn)
        self.quality_btn.setMenu(self.quality_menu)
        meta_row.addWidget(self.quality_btn)
        self.dl_btn = QPushButton('下载')
        self.dl_btn.setObjectName('sendBtn')
        self.dl_btn.setCursor(Qt.PointingHandCursor)
        self.dl_btn.clicked.connect(self._start_download)
        meta_row.addWidget(self.dl_btn)
        self.open_btn = QPushButton('打开')
        self.open_btn.setObjectName('sendBtn')
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(self._open_done_file)
        meta_row.addWidget(self.open_btn)
        info_col.addWidget(self.meta_box)
        # 下载期间的卡内进度区（替换 meta 行，下载结束还原）：
        # 进度条+「暂停/继续」（握手期换 _Spinner）；下方 已下载/总大小 · 剩余时间 · 下载速度
        self.dl_box = QWidget()
        dlb = QVBoxLayout(self.dl_box)
        dlb.setContentsMargins(0, 0, 0, 0)
        dlb.setSpacing(ui.sc(5))
        dl_prog_row = QHBoxLayout()
        dl_prog_row.setContentsMargins(0, 0, 0, 0)
        dl_prog_row.setSpacing(ui.sc(8))
        prog_card = QFrame()
        prog_card.setObjectName('videoRow')
        pc = QVBoxLayout(prog_card)
        pc.setContentsMargins(0, 0, 0, 0)
        pc.setSpacing(ui.sc(3))
        self.prog = QProgressBar()
        self.prog.setRange(0, 100)
        self.prog.setValue(0)
        self.prog.setTextVisible(False)
        self.prog.setFixedHeight(ui.sc(6))
        pc.addWidget(self.prog)
        dl_prog_row.addWidget(prog_card, 1)
        self.spinner = _Spinner()
        self.spinner.set_color(accent)
        dl_prog_row.addWidget(self.spinner, 0, Qt.AlignVCenter)
        self.pause_btn = QToolButton()
        self.pause_btn.setObjectName('cancelBtn')
        self.pause_btn.setText('暂停')
        self.pause_btn.setCursor(Qt.PointingHandCursor)
        self.pause_btn.clicked.connect(self._toggle_pause)
        dl_prog_row.addWidget(self.pause_btn, 0, Qt.AlignVCenter)
        dlb.addLayout(dl_prog_row)
        dl_state_row = QHBoxLayout()
        dl_state_row.setContentsMargins(0, 0, 0, 0)
        dl_state_row.setSpacing(ui.sc(6))
        # 三栏只在下载中可见（dl_box 隐藏时不占位），统一用 busy 强调色
        self.size_lab = QLabel()
        self.size_lab.setObjectName('videoState')
        self.size_lab.setProperty('state', 'busy')
        dl_state_row.addWidget(self.size_lab)
        dl_state_row.addStretch(1)
        self.eta_lab = QLabel()
        self.eta_lab.setObjectName('videoState')
        self.eta_lab.setProperty('state', 'busy')
        dl_state_row.addWidget(self.eta_lab)
        dl_state_row.addStretch(1)
        self.speed_lab = QLabel()
        self.speed_lab.setObjectName('videoState')
        self.speed_lab.setProperty('state', 'busy')
        dl_state_row.addWidget(self.speed_lab)
        dlb.addLayout(dl_state_row)
        self.dl_box.hide()
        info_col.addWidget(self.dl_box)
        cl.addLayout(info_col, 1)

        # URL 标题与解析后同宽（172）：更宽会把 task_box 最小宽度撑出滚动区视口，
        # 横向滚动条禁用 → 所有卡片右侧被裁（「解析中卡片让别的卡布局崩坏」的根因）
        fm = self.title_lab.fontMetrics()
        self.title_lab.setText(fm.elidedText(url, Qt.ElideMiddle, ui.sc(172)))
        self.title_lab.setToolTip(url)
        self._show_meta('parsing')

        self.sig_parse_done.connect(self._on_parse_done)
        self.sig_thumb.connect(self._on_thumb)
        self.sig_dl_progress.connect(self._on_dl_progress)
        self.sig_dl_done.connect(self._on_dl_done)

    # ---------------- 通用 ----------------

    def set_theme(self, key):
        accent = '#e8a33d' if key == 'nocturne' else '#0067c0'
        self.parse_spin.set_color(accent)
        self.spinner.set_color(accent)

    def is_busy(self):
        return self.state in ('parsing', 'downloading')

    def terminate(self):
        """程序退出 / 功能关闭：终止进行中的下载子进程。"""
        try:
            if self._dl is not None:
                self._dl.terminate()
        except Exception:
            pass

    def _show_meta(self, mode):
        """meta 行四态：parsing 转圈+正在解析 / parse 时长+清晰度+下载 /
        done 时长·大小+打开 / text 提示文字（fail_lab，颜色由 state 属性定）。"""
        for w in (self.parse_lab, self.fail_lab, self.dur_lab,
                  self.quality_btn, self.dl_btn, self.open_btn):
            w.hide()
        self.close_btn.setVisible(mode in ('parse', 'done'))
        self.parse_spin.stop()
        if mode == 'parsing':
            self.parse_lab.setText('正在解析…')
            self.parse_lab.show()
            self.parse_spin.start()
        elif mode == 'parse':
            for w in (self.dur_lab, self.quality_btn, self.dl_btn):
                w.show()
        elif mode == 'done':
            self.dur_lab.show()
            self.open_btn.show()
        else:   # text
            self.fail_lab.show()

    def _show_meta_text(self, state, text):
        self.fail_lab.setProperty('state', state)
        fm = self.fail_lab.fontMetrics()
        self.fail_lab.setText(fm.elidedText(text, Qt.ElideMiddle, ui.sc(220)))
        self.fail_lab.setToolTip(text)
        self.fail_lab.style().unpolish(self.fail_lab)
        self.fail_lab.style().polish(self.fail_lab)
        self._show_meta('text')

    # ---------------- 解析 ----------------

    def start_parse(self):
        threading.Thread(target=self._parse_work, daemon=True).start()

    def _parse_work(self):
        try:
            info = video_dl.parse_video(self.url)
            info['url'] = self.url
            self.sig_parse_done.emit(True, info)
        except Exception as e:
            self.sig_parse_done.emit(False, str(e))

    def _on_parse_done(self, ok, info):
        try:
            if not ok:
                self.state = 'failed'
                self.set_glow('')
                if video_dl.is_cookie_error(info):
                    if video_dl.has_cookies():
                        self._show_meta_text('fail', '解析失败：抖音风控升级，cookie 暂时无效')
                    else:
                        self._show_meta_text('fail', '解析失败：该站点要求浏览器 cookie')
                    self.owner.cookie_link.show()
                else:
                    self._show_meta_text('fail', '解析失败：%s' % info)
                return
            self.state = 'parsed'
            self._parsed = info
            self._done_file = ''
            self.title_lab.setToolTip(info['title'] or '')
            self._elide_title()
            dur = _fmt_dur(info['duration'])
            self.dur_lab.setText(('时长 ' + dur) if dur else '')
            self._rebuild_quality_menu(info['heights'])
            self.set_glow('breath')
            self._show_meta('parse')
            self.thumb_lab.setPixmap(_placeholder_pm())
            thumb_url = info.get('thumbnail') or ''
            if thumb_url:
                threading.Thread(target=self._thumb_work,
                                 args=(thumb_url,), daemon=True).start()
        except Exception:
            pass

    def _elide_title(self):
        try:
            title = (self._parsed or {}).get('title') or '（无标题）'
            w = ui.sc(172) if self.thumb_lab.isVisible() else ui.sc(244)
            self.title_lab.setText(
                self.title_lab.fontMetrics().elidedText(title, Qt.ElideRight, w))
        except Exception:
            pass

    def _thumb_work(self, url):
        try:
            with urlopen(Request(url, headers=_UA), timeout=10) as r:
                data = r.read(5 * 1024 * 1024)
        except Exception:
            data = b''
        self.sig_thumb.emit(data)

    def _on_thumb(self, data):
        try:
            pm = _rounded_square_pm(data, 64) if data else None
            if pm is not None and self._parsed is not None:
                self.thumb_lab.setPixmap(pm)
                self.thumb_lab.show()
                self._elide_title()   # 封面占了 64px，标题收窄重排
        except Exception:
            pass

    def _rebuild_quality_menu(self, heights):
        """按源视频实际提供的分辨率降序建菜单；首选最高不超过用户偏好档
        （cfg['video_quality']，手动选择时更新）的档位。"""
        self.quality_menu.clear()
        group = QActionGroup(self)
        group.setExclusive(True)
        options = [('%dP' % h, h) for h in heights] or [('自动', None)]
        m = re.match(r'(\\d+)', self.cfg.data.get('video_quality') or '1080P')
        prefer = int(m.group(1)) if m else 1080
        default_h = None
        for _name, h in options:
            if h and h <= prefer:
                default_h = h
                break
        if default_h is None:
            default_h = options[0][1]
        for name, h in options:
            act = QAction(name, self)
            act.setCheckable(True)
            act.setChecked(h == default_h)
            act.triggered.connect(lambda _c=False, v=h, n=name: self._set_quality(v, n))
            group.addAction(act)
            self.quality_menu.addAction(act)
        self._parsed['height'] = default_h
        self.quality_btn.setText('%s ▾' % (('%dP' % default_h) if default_h else '自动'))

    def _set_quality(self, height, name):
        try:
            if self._parsed:
                self._parsed['height'] = height
            self.quality_btn.setText('%s ▾' % name)
            if height:   # 记住偏好，下次解析同档优先（「自动」不记）
                self.cfg.set('video_quality', name)
        except Exception:
            pass

    # ---------------- 下载 ----------------

    def _start_download(self):
        try:
            if self.state != 'parsed' or not self.owner._on or self.owner._updating:
                return
            try:
                os.makedirs(self.owner.save_dir, exist_ok=True)
            except OSError:
                self._show_meta_text('fail', '保存目录不可用，请重新选择')
                return
            h = self._parsed.get('height')
            self._dl = video_dl.Download(self._parsed['url'], h, self.owner.save_dir,
                                         split=(h in self._parsed.get('split_heights', [])))
            self.state = 'downloading'
            self._cancel_requested = False
            self.size_lab.setText('')
            self.eta_lab.setText('')
            self.speed_lab.setText('')
            self.set_glow('run')
            self._set_dl_ui(True)
            self.prog.setValue(0)
            dl = self._dl
            threading.Thread(
                target=dl.start,
                args=(lambda p, d, sz='', sp='', et='':
                      self.sig_dl_progress.emit(p, d, sz, sp, et),
                      lambda ok, msg: self.sig_dl_done.emit(ok, msg)),
                daemon=True).start()
        except Exception:
            pass

    def _on_dl_progress(self, pct, detail, size='', speed='', eta=''):
        try:
            if pct is None:
                if detail and self._dl is not None:
                    self.eta_lab.setText(detail)   # 阶段提示（合并中…）
                return
            if self._dl is None:
                return
            if not self.spinner.isHidden():   # 正式开始下载：loading 换回「暂停」
                self.spinner.stop()
                self.pause_btn.show()
            self.prog.setValue(int(pct))
            if size:
                self.size_lab.setText(_fmt_pair(pct, size))
            if eta:
                self.eta_lab.setText(eta)
            if speed:
                self.speed_lab.setText(speed)
        except Exception:
            pass

    def _on_dl_done(self, ok, msg):
        try:
            self._dl = None
            self._set_dl_ui(False)
            if self._cancel_requested and not ok:
                # 取消与完成竞速，完成优先；取消回解析态（可重新下载）
                self._cancel_requested = False
                self.prog.setValue(0)
                self.set_glow('breath')
                self._show_meta('parse')
                return
            if ok:
                self.prog.setValue(100)
                if msg and os.path.isfile(msg):
                    # 完成态：淡蓝静态轮廓，meta 行 时长·大小 + 「打开」
                    self.state = 'done'
                    self._done_file = msg
                    self.set_glow('')   # 完成态不加轮廓灯
                    dur = _fmt_dur((self._parsed or {}).get('duration'))
                    head = ('时长 ' + dur + ' · ') if dur else ''
                    self.dur_lab.setText(head + _fmt_size(os.path.getsize(msg)))
                    self._show_meta('done')
                else:
                    self.state = 'failed'
                    self.set_glow('')
                    self._show_meta_text('done', '已完成' if not msg else msg)
            elif '未重复下载' in (msg or ''):
                self.state = 'failed'
                self.set_glow('')
                self._show_meta_text('', msg)   # 同名跳过是提示而非失败，不用红色
            else:
                self.state = 'failed'
                self.set_glow('')
                if video_dl.is_cookie_error(msg):
                    if video_dl.has_cookies():
                        self._show_meta_text('fail', '下载失败：抖音风控升级，cookie 暂时无效')
                    else:
                        self._show_meta_text('fail', '下载失败：该站点要求浏览器 cookie')
                    self.owner.cookie_link.show()
                else:
                    self._show_meta_text('fail', '下载失败：%s' % msg)
        except Exception:
            pass

    def _set_dl_ui(self, busy):
        """下载进度区与 meta 行互换显隐；握手期右侧转圈顶替「暂停」。"""
        if busy:
            self._dl_paused = False
            self.pause_btn.setText('暂停')
            self.pause_btn.hide()
            self.spinner.start()
            self.meta_box.hide()
            self.dl_box.show()
        else:
            self.spinner.stop()
            self.pause_btn.show()
            self.dl_box.hide()
            self.meta_box.show()

    def _close_clicked(self):
        """✕：把卡片从任务列表移除。下载中（含暂停）先二次确认——
        terminate 后 start() 收尾的 _cleanup_parts 会删掉下载到一半的缓存文件。"""
        try:
            if self._dl is not None:
                if _ConfirmDialog(self, '删除任务',
                                  '该任务正在下载，确定要删除吗？'
                                  '下载到一半的缓存文件会一并删除。',
                                  '确认删除').exec() != QDialog.Accepted:
                    return
                self._cancel_requested = True
                self._dl.terminate()
            owner = self.owner
            if self in owner.tasks:
                owner.tasks.remove(self)
            owner.task_lay.removeWidget(self)
            self.deleteLater()
        except Exception:
            pass

    def _toggle_pause(self):
        """暂停/继续：暂停杀进程树但留 .part，继续以同命令重启自动断点续传。"""
        try:
            if self._dl is None:
                return
            if self._dl_paused:
                self._dl_paused = False
                self.pause_btn.setText('暂停')
                self.eta_lab.setText('继续下载…')
                self._dl.resume()
            else:
                self._dl_paused = True
                self.pause_btn.setText('继续')
                self.eta_lab.setText('已暂停')
                self._dl.pause()
        except Exception:
            pass

    def _card_menu(self, pos):
        """右键任务卡：完成态弹「打开所在目录」（下载中不弹菜单，取消走 ✕ 二次确认）。"""
        try:
            if self._dl is None and self._done_file and os.path.isfile(self._done_file):
                menu = QMenu(self)
                act = menu.addAction('打开所在目录')
                if menu.exec_(self.mapToGlobal(pos)) == act:
                    self._open_done_dir()
        except Exception:
            pass

    def _open_done_file(self):
        try:
            if self._done_file and os.path.isfile(self._done_file):
                QDesktopServices.openUrl(QUrl.fromLocalFile(self._done_file))
        except Exception:
            pass

    def _open_done_dir(self):
        """打开所在目录并选中该文件（explorer /select,）。"""
        try:
            if self._done_file and os.path.isfile(self._done_file):
                subprocess.Popen(['explorer', '/select,', os.path.normpath(self._done_file)])
        except Exception:
            pass


class VideoInfoDialog(QDialog):
    """视频解析页门禁层 / 设置窗的「?」共用的说明弹窗。
    样式复用设置窗（#settingsDlg / #settingsPanel 区段）。"""

    def __init__(self, parent=None):
        super(VideoInfoDialog, self).__init__(parent)
        self.setObjectName('settingsDlg')
        self.setWindowTitle('关于视频解析')
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = QWidget()
        card.setObjectName('settingsPanel')
        root.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(ui.sc(16), ui.sc(6), ui.sc(16), ui.sc(14))
        lay.setSpacing(ui.sc(8))

        tb = QHBoxLayout()
        tb.setContentsMargins(0, 0, 0, 0)
        title = QLabel('关于「视频解析」')
        title.setObjectName('setTitle')
        tb.addWidget(title)
        tb.addStretch(1)
        close = QToolButton()
        close.setObjectName('closeBtn')
        close.setText('✕')
        close.setFixedSize(ui.sc(28), ui.sc(24))
        close.setToolTip('关闭')
        close.clicked.connect(self.reject)
        tb.addWidget(close)
        lay.addLayout(tb)

        def para(text, name='infoText'):
            lb = QLabel(text)
            lb.setObjectName(name)
            lb.setWordWrap(True)
            lay.addWidget(lb)
            return lb

        para('粘贴视频网址，点「解析」读取标题与实际清晰度档位，'
             '选好档位后点「下载视频」。支持 YouTube、Bilibili 等国内外主流视频平台'
             '（由开源项目 yt-dlp 提供支持），音视频由 ffmpeg 自动合并为 mp4。')
        para('开启后会发生什么', 'transferTitle')
        para('· 首次开启时自动下载解析所需的组件，存放在程序目录的 tools 文件夹内；\n'
             '· 本页底部可随时检查组件更新或卸载。')
        para('版权提示', 'transferTitle')
        para('下载内容仅供个人学习使用，请遵守各平台条款与著作权相关法律。')

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok = QPushButton('我知道了')
        ok.setObjectName('setSave')
        ok.setCursor(Qt.PointingHandCursor)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btn_row.addWidget(ok)
        lay.addLayout(btn_row)

        para('可随时在「设置 → 视频解析」中关闭此功能。', 'transferHint')

        self.setFixedWidth(ui.sc(320))
        self.adjustSize()


class _ConfirmDialog(QDialog):
    """危险操作二次确认弹窗：样式复用设置窗。"""

    def __init__(self, parent=None, title='卸载组件',
                 text='将删除视频解析所需的组件文件与已导入的 cookie，本功能随之关闭。'
                      '下次启用时会自动重新下载，已下载的视频不受影响。',
                 ok_text='确认卸载'):
        super(_ConfirmDialog, self).__init__(parent)
        self.setObjectName('settingsDlg')
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = QWidget()
        card.setObjectName('settingsPanel')
        root.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(ui.sc(16), ui.sc(6), ui.sc(16), ui.sc(14))
        lay.setSpacing(ui.sc(8))

        tb = QHBoxLayout()
        tb.setContentsMargins(0, 0, 0, 0)
        title = QLabel(self.windowTitle())
        title.setObjectName('setTitle')
        tb.addWidget(title)
        tb.addStretch(1)
        close = QToolButton()
        close.setObjectName('closeBtn')
        close.setText('✕')
        close.setFixedSize(ui.sc(28), ui.sc(24))
        close.setToolTip('关闭')
        close.clicked.connect(self.reject)
        tb.addWidget(close)
        lay.addLayout(tb)

        lb = QLabel(text)
        lb.setObjectName('infoText')
        lb.setWordWrap(True)
        lay.addWidget(lb)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(ui.sc(8))
        cancel = QPushButton('取消')
        cancel.setObjectName('setBtn')
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        btn_row.addStretch(1)
        ok = QPushButton(ok_text)
        ok.setObjectName('setSave')
        ok.setCursor(Qt.PointingHandCursor)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btn_row.addWidget(ok)
        lay.addLayout(btn_row)

        self.setFixedWidth(ui.sc(300))
        self.adjustSize()


class CookieGuideDialog(QDialog):
    """抖音等站点「需要 cookie」的引导弹窗：装扩展 → 刷页面 → 导出 → 导入四步。
    样式复用设置窗（#settingsDlg / #settingsPanel 区段）。"""

    # Edge 外接程序商店国内直连（用搜索链接，不怕商品 ID 变动）；Chrome 商店需科学上网
    EDGE_STORE = 'https://microsoftedge.microsoft.com/addons/search/Get%20cookies.txt%20LOCALLY'
    CHROME_STORE = ('https://chromewebstore.google.com/detail/'
                    'get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc')

    def __init__(self, parent=None):
        super(CookieGuideDialog, self).__init__(parent)
        theme = getattr(parent, 'theme_key', 'nocturne')
        accent = '#0067c0' if theme == 'mica' else '#e8a33d'   # 同关于窗链接配色（QSS 管不到 <a>）
        self.setObjectName('settingsDlg')
        self.setWindowTitle('抖音需要 cookie')
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = QWidget()
        card.setObjectName('settingsPanel')
        root.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(ui.sc(16), ui.sc(6), ui.sc(16), ui.sc(14))
        lay.setSpacing(ui.sc(8))

        tb = QHBoxLayout()
        tb.setContentsMargins(0, 0, 0, 0)
        title = QLabel('抖音需要 cookie')
        title.setObjectName('setTitle')
        tb.addWidget(title)
        tb.addStretch(1)
        close = QToolButton()
        close.setObjectName('closeBtn')
        close.setText('✕')
        close.setFixedSize(ui.sc(28), ui.sc(24))
        close.setToolTip('关闭')
        close.clicked.connect(self.reject)
        tb.addWidget(close)
        lay.addLayout(tb)

        def para(text, name='infoText'):
            lb = QLabel(text)
            lb.setObjectName(name)
            lb.setWordWrap(True)
            lay.addWidget(lb)
            return lb

        def link_para(text):
            lb = para(text)
            lb.setOpenExternalLinks(True)   # <a> 点击交给系统浏览器
            lb.setCursor(Qt.PointingHandCursor)
            return lb

        para('抖音限制了匿名访问：解析前要给 zbox 一份浏览器 cookie'
             '（访客 cookie 即可，<b>不需要登录抖音账号</b>）。按下面四步操作；'
             'cookie 大约几周后过期，届时抖音再次解析失败，重走第 2～4 步即可。')
        warn = para('<b>注意：</b>2026 年 9 月起抖音升级了风控，即使导入 cookie，'
                    'yt-dlp 也暂时无法解析抖音（需等 yt-dlp 更新支持）；'
                    'cookie 对其它要求登录的站点仍然有效。')
        warn.setStyleSheet('color:%s;' % accent)
        para('第 1 步：安装 cookie 导出扩展', 'transferTitle')
        link_para('在浏览器扩展商店安装「Get cookies.txt LOCALLY」：'
                  '<a href="%s" style="color:%s;">Edge 外接程序商店（国内直连）</a>　'
                  '<a href="%s" style="color:%s;">Chrome 应用商店（需科学上网）</a>'
                  % (self.EDGE_STORE, accent, self.CHROME_STORE, accent))
        para('第 2 步：让浏览器拿到新鲜 cookie', 'transferTitle')
        link_para('用装了扩展的浏览器打开 '
                  '<a href="https://www.douyin.com" style="color:%s;">douyin.com</a>，'
                  '随便点开一两个视频（或刷新几下页面），不用登录。' % accent)
        para('第 3 步：导出 cookies.txt', 'transferTitle')
        para('点浏览器工具栏上的扩展图标 →「Export」，得到一个 cookies.txt 文件'
             '（通常在「下载」文件夹里）。')
        para('第 4 步：导入 zbox', 'transferTitle')
        self.status_lab = para('')

        self.result_lab = QLabel('')
        self.result_lab.setObjectName('transferHint')
        self.result_lab.setWordWrap(True)
        lay.addWidget(self.result_lab)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(ui.sc(8))
        btn_row.addStretch(1)
        self.imp_btn = QPushButton('导入 cookies.txt')
        self.imp_btn.setObjectName('setSave')
        self.imp_btn.setCursor(Qt.PointingHandCursor)
        self.imp_btn.setDefault(True)
        self.imp_btn.clicked.connect(self._on_main_btn)
        btn_row.addWidget(self.imp_btn)
        self.rm_btn = QPushButton('完成')
        self.rm_btn.setObjectName('setSave')
        self.rm_btn.setCursor(Qt.PointingHandCursor)
        self.rm_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.rm_btn)
        lay.addLayout(btn_row)

        self.setFixedWidth(ui.sc(320))
        self._refresh_status()
        self.adjustSize()

    def _refresh_status(self):
        try:
            if video_dl.has_cookies():
                ts = time.strftime('%Y-%m-%d',
                                   time.localtime(os.path.getmtime(video_dl.cookies_path())))
                self.status_lab.setText('当前状态：<b>已导入</b>（%s）。' % ts)
                self.imp_btn.setText('移除 cookies')
                self.imp_btn.setToolTip('删除已导入的 cookies.txt')
                self.rm_btn.show()
            else:
                self.status_lab.setText('当前状态：未导入。点下面按钮选择刚导出的 cookies.txt。')
                self.imp_btn.setText('导入 cookies.txt')
                self.imp_btn.setToolTip('')
                self.rm_btn.hide()
        except Exception:
            pass

    def _on_main_btn(self):
        if video_dl.has_cookies():
            self._remove()
        else:
            self._import()

    def _import(self):
        try:
            dl_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
            src, _ = QFileDialog.getOpenFileName(
                self, '选择 cookies.txt', dl_dir,
                'cookie 文件 (cookies.txt *.txt);;所有文件 (*)')
            if not src:
                return
            ok, msg = video_dl.import_cookies(src)
            self.result_lab.setText(msg if msg else '导入成功，回到面板重新点「解析」即可。')
            self._refresh_status()
            self.adjustSize()
        except Exception:
            pass

    def _remove(self):
        try:
            video_dl.remove_cookies()
            self.result_lab.setText('已移除。')
            self._refresh_status()
            self.adjustSize()
        except Exception:
            pass


class VideoWidget(QWidget):
    """视频解析 tab。功能默认关闭：页面盖门禁层，开启后后台下载组件，
    就绪后可解析/下载视频；底栏常驻 yt-dlp / ffmpeg 版本与更新、卸载入口。

    多任务模型：输入框 + 「解析」创建任务卡（`_VideoTask`，卡片即任务）插到列表
    顶部；解析/下载进行中输入框不锁，可随时添加新任务；卡片一经创建留到程序重启。"""

    enabled_changed = Signal(bool)                  # 开关状态变化（设置窗同步勾选用）
    sig_prep = Signal(str)                          # 组件准备进度文案
    sig_prep_done = Signal(bool, str, int)          # 组件准备结束 ok, err, 批次序号
    sig_ver = Signal(str, object, str, object)      # 版本查询：yt本地, yt最新, ff本地, ff最新(None=失败)
    sig_msg = Signal(str, str)                      # 全局状态行提示 state, text（组件更新完成等）

    def __init__(self, cfg, parent=None, auto_start=True):
        super(VideoWidget, self).__init__(parent)
        self.cfg = cfg
        self.theme_key = 'nocturne'
        self._on = False             # 组件就绪、功能开启
        self.tasks = []              # _VideoTask 列表（新的在前，程序重启前不移除）
        self._local = ''             # 本地 yt-dlp 版本
        self._latest = None          # yt-dlp 最新版本（None=未查过/查询失败）
        self._ff_local = ''          # 本地 ffmpeg 版本
        self._ff_latest = None       # ffmpeg 最新版本
        self._yt_new = False         # 有 yt-dlp 新版
        self._ff_new = False         # 有 ffmpeg 新版
        self._updating = False       # 正在更新 yt-dlp
        self._prep_seq = 0           # 组件准备批次：关功能后迟到的结果要丢弃
        self.save_dir = cfg.data.get('video_dir') or video_dl.desktop_dir()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.pane = QFrame()
        self.pane.setObjectName('videoRoot')
        pl = QVBoxLayout(self.pane)
        pl.setContentsMargins(ui.sc(8), ui.sc(8), ui.sc(8), ui.sc(8))
        pl.setSpacing(ui.sc(6))
        root.addWidget(self.pane)

        # ---- 网址行：输入框 + 解析按钮（始终可用，随时添加新任务）----
        url_row = QHBoxLayout()
        url_row.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        url_row.setSpacing(ui.sc(6))
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName('urlEdit')
        self.url_edit.setPlaceholderText('粘贴视频网址（YouTube / Bilibili 等）')
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self._start_parse)
        url_row.addWidget(self.url_edit, 1)
        self.parse_btn = QToolButton()
        self.parse_btn.setObjectName('parseBtn')
        self.parse_btn.setText('解 析')
        self.parse_btn.setCursor(Qt.PointingHandCursor)
        self.parse_btn.clicked.connect(self._start_parse)
        url_row.addWidget(self.parse_btn)
        pl.addLayout(url_row)

        # ---- 任务卡列表：每个解析/下载任务一张卡，新任务插顶部 ----
        self.task_scroll = QScrollArea()
        self.task_scroll.setObjectName('videoScroll')
        self.task_scroll.setWidgetResizable(True)
        self.task_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.task_box = _TaskBox()
        self.task_box.setObjectName('videoBox')
        self.task_lay = QVBoxLayout(self.task_box)
        self.task_lay.setContentsMargins(0, 0, 0, 0)
        self.task_lay.setSpacing(ui.sc(6))
        self.task_lay.addStretch(1)
        self.task_scroll.setWidget(self.task_box)
        pl.addWidget(self.task_scroll, 1)   # 吃掉剩余空间：卡少时留白，卡多时滚动

        # ---- 状态行：只放全局提示（空文本时整行隐藏不占位）----
        state_row = QHBoxLayout()
        state_row.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        state_row.setSpacing(ui.sc(6))
        state_row.addStretch(1)
        self.state_lab = QLabel()
        self.state_lab.setObjectName('videoState')
        self.state_lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)   # 单行右对齐
        self.state_lab.hide()                # 空文本不占位，_set_state 有文本才显示
        state_row.addWidget(self.state_lab)
        self.cookie_link = QToolButton()
        self.cookie_link.setObjectName('linkBtn')
        self.cookie_link.setText('查看解决办法')
        self.cookie_link.setCursor(Qt.PointingHandCursor)
        self.cookie_link.setToolTip('抖音等站点要求浏览器 cookie，点这里看导入步骤')
        self.cookie_link.clicked.connect(lambda: CookieGuideDialog(self).exec())
        self.cookie_link.hide()          # 只在 cookie 类报错时出现
        state_row.addWidget(self.cookie_link)
        state_row.addStretch(1)
        pl.addLayout(state_row)

        # ---- 保存目录 ----
        dir_row = QHBoxLayout()
        dir_row.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        dir_row.setSpacing(ui.sc(6))
        dir_t = QLabel('保存到')
        dir_t.setObjectName('videoLabel')
        dir_row.addWidget(dir_t)
        self.dir_lab = QLabel()
        self.dir_lab.setObjectName('videoDir')
        self.dir_lab.setToolTip(self.save_dir)
        dir_row.addWidget(self.dir_lab, 1)
        pick = QToolButton()
        pick.setObjectName('linkBtn')
        pick.setText('更改')
        pick.setCursor(Qt.PointingHandCursor)
        pick.clicked.connect(self._pick_dir)
        dir_row.addWidget(pick)
        open_btn = QToolButton()
        open_btn.setObjectName('linkBtn')
        open_btn.setText('打开')
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.clicked.connect(self._open_dir)
        dir_row.addWidget(open_btn)
        pl.addLayout(dir_row)
        self._sync_dir_text()

        # ---- 底栏：组件信息（分隔线 + yt-dlp / ffmpeg 两行）----
        sep = QFrame()
        sep.setObjectName('setSep')
        sep.setFixedHeight(1)
        pl.addWidget(sep)

        ver_row = QHBoxLayout()
        ver_row.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        ver_row.setSpacing(ui.sc(6))
        self.ver_lab = QLabel('组件 —')
        self.ver_lab.setObjectName('videoVer')
        ver_row.addWidget(self.ver_lab, 1)
        self.update_btn = QToolButton()
        self.update_btn.setObjectName('linkBtn')
        self.update_btn.setText('检查更新')
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(self._ver_clicked)
        ver_row.addWidget(self.update_btn)
        self.uninst_btn = QToolButton()
        self.uninst_btn.setObjectName('linkBtn')
        self.uninst_btn.setText('卸载组件')
        self.uninst_btn.setCursor(Qt.PointingHandCursor)
        self.uninst_btn.setToolTip('删除视频解析组件，关闭本功能')
        self.uninst_btn.clicked.connect(self._uninstall_clicked)
        ver_row.addWidget(self.uninst_btn)
        pl.addLayout(ver_row)

        # ---- 信号 ----
        self.sig_prep.connect(self._on_prep_text)
        self.sig_prep_done.connect(self._on_prep_done)
        self.sig_ver.connect(self._on_ver)
        self.sig_msg.connect(self._set_state)

        # ---- 门禁层：未开启时盖住整页（内容高斯模糊）----
        self._build_gate()

        # auto_start=False（截图自检）：不下组件也不盖门禁层，按功能态渲染
        if not auto_start:
            return
        if bool(cfg.data.get('video_enabled')):
            self.set_enabled(True)
        else:
            self._show_gate('enable')

    # ---------------- 通用 ----------------

    def set_theme(self, key):
        """主题切换：颜色全走 QSS；任务卡灯效/转圈的 accent 色跟随主题。"""
        self.theme_key = key
        for t in getattr(self, 'tasks', []):
            t.set_theme(key)

    def service_enabled(self):
        return self._on

    def shutdown(self):
        """程序退出 / 功能关闭：终止所有任务进行中的下载子进程。"""
        for t in self.tasks:
            t.terminate()

    # ---------------- 开关与组件准备 ----------------

    def set_enabled(self, on):
        """界面开关入口（视频解析页「启用」/ 设置窗勾选共用）。
        开启是异步的（可能要下载组件）：失败时经 enabled_changed(False) 回落。"""
        try:
            if on:
                if self._on:
                    return True
                self.gate_msg.setText('正在检查组件…')
                self._show_gate('prep')
                self._prep_seq += 1
                threading.Thread(target=self._prep_work,
                                 args=(self._prep_seq,), daemon=True).start()
                return True
            self.shutdown()
            self._on = False
            self._prep_seq += 1   # 作废进行中的准备结果
            self.cfg.set('video_enabled', False)
            self._show_gate('enable')
            self.enabled_changed.emit(False)
            return True
        except Exception:
            return False

    def _prep_work(self, seq):
        try:
            ok, err = video_dl.ensure_tools(self._prep_progress)
        except Exception as e:
            ok, err = False, str(e)
        self.sig_prep_done.emit(ok, err, seq)

    def _prep_progress(self, what, done, total):
        try:
            if total:
                self.sig_prep.emit('正在下载 %s… %d%%' % (what, done * 100 // total))
            else:
                self.sig_prep.emit('正在下载 %s… %s' % (what, _fmt_mb(done)))
        except Exception:
            pass

    def _on_prep_text(self, text):
        try:
            if self._gate_mode == 'prep':
                self.gate_msg.setText(text)
        except Exception:
            pass

    def _on_prep_done(self, ok, err, seq):
        try:
            if seq != self._prep_seq:   # 准备期间用户又关了功能：丢弃迟到结果
                return
            if ok:
                self._on = True
                self.cfg.set('video_enabled', True)
                self._hide_gate()
                self.enabled_changed.emit(True)
                self._refresh_versions()
            else:
                self._on = False
                self.cfg.set('video_enabled', False)
                self.gate_msg.setText('组件下载失败，请检查网络后重试\n%s' % (err or '')[:80])
                self._show_gate('unavailable')
                self.enabled_changed.emit(False)
        except Exception:
            pass

    # ---------------- 版本 / 更新 / 卸载（底栏） ----------------

    def _refresh_versions(self):
        def work():
            try:
                local = video_dl.local_version()
                latest = video_dl.latest_version()
                ffver = video_dl.ffmpeg_version()
                ff_latest = video_dl.latest_ffmpeg_version()
            except Exception:
                local, latest, ffver, ff_latest = '', None, '', None
            self.sig_ver.emit(local, latest, ffver, ff_latest)
        threading.Thread(target=work, daemon=True).start()

    def _on_ver(self, local, latest, ffver, ff_latest):
        try:
            self.update_btn.setEnabled(True)
            self._local, self._latest = local, latest
            self._ff_local, self._ff_latest = ffver, ff_latest
            self._yt_new = bool(latest) and \
                    video_dl.version_key(latest) != video_dl.version_key(local)
            self._ff_new = bool(ff_latest) and bool(ffver) and \
                    video_dl.version_key(ff_latest) != video_dl.version_key(ffver)
            if not local or not ffver:
                self.ver_lab.setText('组件异常')
                self.update_btn.setText('重试')
            elif self._yt_new or self._ff_new:
                self.ver_lab.setText('组件有新版可更新')
                self.update_btn.setText('更新')
            elif latest and ff_latest:
                self.ver_lab.setText('组件已是最新')
                self.update_btn.setText('检查更新')
            else:
                self.ver_lab.setText('更新检查失败')
                self.update_btn.setText('重试')
        except Exception:
            pass

    def _ver_clicked(self):
        try:
            if self._updating or self._any_busy():
                return
            has_new = self._yt_new or self._ff_new
            self._updating = True
            self.update_btn.setEnabled(False)
            if has_new:
                self._set_state('busy', '正在更新 yt-dlp…')
                threading.Thread(target=self._update_work, daemon=True).start()
            else:
                self.ver_lab.setText('检查中…')
                threading.Thread(target=self._check_work, daemon=True).start()
        except Exception:
            pass

    def _check_work(self):
        try:
            latest = video_dl.latest_version()
            ff_latest = video_dl.latest_ffmpeg_version()
        except Exception:
            latest, ff_latest = None, None
        self._updating = False
        self.sig_ver.emit(video_dl.local_version(), latest,
                          video_dl.ffmpeg_version(), ff_latest)

    def _update_work(self):
        ok = True
        try:
            if self._yt_new:
                video_dl.download_ytdlp()
            if self._ff_new:
                video_dl.download_ffmpeg(ver=self._ff_latest)
        except Exception:
            ok = False
        local = video_dl.local_version()
        latest = video_dl.latest_version()
        ffver = video_dl.ffmpeg_version()
        ff_latest = video_dl.latest_ffmpeg_version()
        self._updating = False
        self.sig_ver.emit(local, latest, ffver, ff_latest)
        self.sig_msg.emit('done' if ok else 'fail',
                          '组件已更新到最新' if ok else '组件更新失败，请稍后重试')

    def _uninstall_clicked(self):
        try:
            if self._any_busy() or self._updating:
                self._set_state('fail', '当前有任务进行中，无法卸载')
                return
            if _ConfirmDialog(self).exec() != QDialog.Accepted:
                return
            video_dl.uninstall_tools()
            self.set_enabled(False)   # 关功能回门禁层，下次启用重新下载组件
        except Exception:
            pass

    # ---------------- 解析（任务入口） ----------------

    def _start_parse(self):
        """输入框 + 解析按钮：创建一个任务卡插到列表顶部。
        解析/下载进行中不锁输入框，可随时添加新任务。"""
        try:
            if not self._on or self._updating:
                return
            url = self.url_edit.text().strip()
            if not url:
                self._set_state('fail', '请先粘贴视频网址')
                return
            if any(t.url == url for t in self.tasks):
                self._set_state('', '该网址已在列表中')
                return
            self._set_state('', '')
            task = _VideoTask(self, url)
            self.tasks.insert(0, task)
            self.task_lay.insertWidget(0, task)
            task.show()
            task.start_parse()
            self.url_edit.clear()   # 任务卡已建，清空输入框方便粘下一个
        except Exception:
            pass

    def _any_busy(self):
        return any(t.is_busy() for t in self.tasks)

    def _clear_tasks(self):
        for t in self.tasks:
            t.terminate()
            t.deleteLater()
        self.tasks = []

    def _set_state(self, state, text):
        if hasattr(self, 'cookie_link'):
            self.cookie_link.hide()
        self.state_lab.setProperty('state', state)
        fm = self.state_lab.fontMetrics()
        self.state_lab.setText(fm.elidedText(text, Qt.ElideMiddle, ui.sc(280)))
        self.state_lab.setToolTip(text)
        self.state_lab.setVisible(bool(text))
        self.state_lab.style().unpolish(self.state_lab)
        self.state_lab.style().polish(self.state_lab)

    # ---------------- 保存目录 ----------------

    def _sync_dir_text(self):
        try:
            fm = self.dir_lab.fontMetrics()
            self.dir_lab.setText(fm.elidedText(self.save_dir, Qt.ElideMiddle, ui.sc(140)))
            self.dir_lab.setToolTip(self.save_dir)
        except Exception:
            pass

    def _pick_dir(self):
        try:
            d = QFileDialog.getExistingDirectory(self, '选择保存目录', self.save_dir)
            if d:
                self.save_dir = os.path.normpath(d)
                self.cfg.set('video_dir', self.save_dir)
                self._sync_dir_text()
        except Exception:
            pass

    def _open_dir(self):
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.save_dir))
        except Exception:
            pass

    # ---------------- 门禁层 ----------------

    def _build_gate(self):
        """门禁层：与传输页同款的页内遮罩（pane 的兄弟，不随 pane 一起模糊）。"""
        self._blur = None
        self._gate_mode = 'enable'
        self.gate = QFrame(self)
        self.gate.setObjectName('transferGate')
        gl = QVBoxLayout(self.gate)
        gl.setContentsMargins(ui.sc(18), ui.sc(16), ui.sc(18), ui.sc(14))
        gl.setSpacing(ui.sc(10))
        gl.addStretch(1)
        self.gate_msg = QLabel()
        self.gate_msg.setObjectName('transferHint')
        self.gate_msg.setAlignment(Qt.AlignCenter)
        gl.addWidget(self.gate_msg)
        self.gate_ok = QPushButton('启用视频解析')
        self.gate_ok.setObjectName('setSave')           # 复用设置窗主按钮样式
        self.gate_ok.setCursor(Qt.PointingHandCursor)
        self.gate_ok.clicked.connect(self._gate_ok_clicked)
        gl.addWidget(self.gate_ok, 0, Qt.AlignCenter)
        # 「?」圆形说明按钮：放在「启用视频解析」正下方居中
        self.gate_help = QToolButton()
        self.gate_help.setObjectName('gateHelpBtn')
        self.gate_help.setText('?')
        self.gate_help.setFixedSize(ui.sc(20), ui.sc(20))
        self.gate_help.setCursor(Qt.PointingHandCursor)
        self.gate_help.setToolTip('什么是视频解析')
        self.gate_help.clicked.connect(lambda: VideoInfoDialog(self).exec())
        gl.addWidget(self.gate_help, 0, Qt.AlignCenter)
        gl.addStretch(1)
        self.gate.hide()

    def _show_gate(self, mode):
        """mode='enable'：启用按钮 + 「?」；mode='prep'：组件准备进度；
        mode='unavailable'：失败提示 + 确定。"""
        try:
            self._gate_mode = mode
            self.gate_msg.setVisible(mode != 'enable')
            self.gate_ok.setText({'enable': '启用视频解析',
                                  'prep': '准备中…',
                                  'unavailable': '确定'}[mode])
            self.gate_ok.setEnabled(mode != 'prep')
            self.gate_help.setVisible(mode == 'enable')
            if self._blur is None:
                self._blur = QGraphicsBlurEffect(self)
                self._blur.setBlurRadius(ui.sc(8))
            self.pane.setGraphicsEffect(self._blur)
            self.gate.setGeometry(self.rect())
            self.gate.show()
            self.gate.raise_()
        except Exception:
            pass

    def _hide_gate(self):
        try:
            self.pane.setGraphicsEffect(None)
            self._blur = None
            self.gate.hide()
        except Exception:
            pass

    def _gate_ok_clicked(self):
        try:
            if self._gate_mode == 'unavailable':
                # 「确定」：回到未开启态
                self.cfg.set('video_enabled', False)
                self._show_gate('enable')
                self.enabled_changed.emit(False)
            elif self._gate_mode == 'enable':
                self.set_enabled(True)
        except Exception:
            pass

    def resizeEvent(self, e):
        super(VideoWidget, self).resizeEvent(e)
        try:
            if hasattr(self, 'gate'):
                self.gate.setGeometry(self.rect())
        except Exception:
            pass