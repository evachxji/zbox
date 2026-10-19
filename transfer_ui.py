# -*- coding: utf-8 -*-
'''传输页 UI：本机别名、附近设备列表、文件发送、传输记录与接收确认弹窗。

线程模型：TransferServer / Discovery / send_files 的回调全部发生在后台线程，
本模块只经 Signal 把事件送回主线程再动 UI（PySide6 槽里未捕获异常会让进程
abort，故所有槽函数 try/except 兜底）。on_receive_request 是 HTTP 线程里的
阻塞调用：发信号给主线程弹确认层，结果经 threading.Event 回传，超时按拒绝。
'''

import math
import os
import subprocess
import threading
import time
import uuid

from PySide6.QtCore import (Qt, QTimer, Signal, QPointF, QRect, QRectF,
                          QSize, QPropertyAnimation, QEasingCurve, QUrl)
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QDesktopServices
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QToolButton, QPushButton,
                             QVBoxLayout, QHBoxLayout, QLineEdit, QProgressBar,
                             QScrollArea, QFileDialog, QSizePolicy, QMenu,
                             QGraphicsOpacityEffect, QGraphicsBlurEffect, QDialog)

import app as ui            # 仅运行期用 ui.sc()，import 期无依赖（app 也 import 本模块）
import transfer
from transfer import send_files
import glow
import sysutil
from i18n import t

RECV_CONFIRM_TIMEOUT = 170   # 接收确认等待秒数：须小于协议端 prepare-upload 的 180s
MAX_RECORDS = 50             # 传输记录条数上限，超出丢弃最旧

# 底层异常文本里的中文关键词：部分系统报错与协议层提示是中文，需要拿它们匹配原始
# 错误串。这是数据而非界面文案——不要迁移进词典、也不要翻译；返回给用户的提示
# 一律走 transfer.err.*。
_NET_ERROR_HINTS = {
    'unconfirmed': '对方未及时确认',
    'refused': '积极拒绝',
    'reset': '强迫关闭',
    'timeout': '超时',
    'offline': '不在线',
    'unreachable': '不可达',
}


def _expand_paths(paths):
    '''把文件/文件夹列表展开成 [(本地路径, 相对路径)]。

    文件 -> (p, basename)；文件夹 -> os.walk 递归展开（不跟随符号链接，
    不可读项由 os.walk 默认忽略），相对路径含顶层文件夹名、posix 分隔。
    空文件夹展开为 0 项，自然被忽略。'''
    out = []
    for p in paths:
        if os.path.isfile(p):
            out.append((p, os.path.basename(p)))
        elif os.path.isdir(p):
            base = os.path.dirname(os.path.normpath(p))
            for root, _dirs, names in os.walk(p):
                for name in names:
                    full = os.path.join(root, name)
                    rel = os.path.relpath(full, base).replace(os.sep, '/')
                    out.append((full, rel))
    return out


def _fmt_size(n):
    '''字节数转可读大小（1024 进制）。'''
    try:
        n = float(n)
    except (TypeError, ValueError):
        return '?'
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return ('%.0f' if unit == 'B' else '%.1f') % n + ' ' + unit
        n /= 1024.0
    return '%.1f TB' % n


def _fmt_speed(bps):
    '''字节/秒转可读速度。'''
    return _fmt_size(bps) + '/s'


def _fmt_eta(seconds):
    '''剩余秒数转可读时间（<=0 或非法返回空串）。'''
    if seconds is None or seconds != seconds or seconds <= 0:
        return ''
    seconds = int(seconds)
    if seconds < 60:
        return t('transfer.eta.seconds', n=max(1, seconds))
    if seconds < 3600:
        return t('transfer.eta.minutes', m=seconds // 60, s=seconds % 60)
    return t('transfer.eta.hours', h=seconds // 3600, m=seconds % 3600 // 60)


_FILE_ICON_CACHE = {}


def _file_icon(theme, size=22):
    '''记录行/接收清单的文件图标：淡底圆角块 + 图片象形（相框+太阳+山），按主题/DPI 缓存。'''
    key = (theme, size, ui.ui_scale())
    pm = _FILE_ICON_CACHE.get(key)
    if pm is not None:
        return pm
    s = ui.sc(size)
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    color = QColor({'nocturne': '#7c93b8', 'mica': '#0067c0'}.get(theme, '#7c93b8'))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    tint = QColor(color)
    tint.setAlpha(36)
    p.setPen(Qt.NoPen)
    p.setBrush(tint)
    r = ui.sc(6)
    p.drawRoundedRect(0, 0, s, s, r, r)
    w = max(1.5, ui.sc(1.4))
    p.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    x0, y0 = s * 0.22, s * 0.28          # 相框左上角
    fw = s * 0.56
    fh = s * 0.48
    p.drawRoundedRect(QRectF(x0, y0, fw, fh), ui.sc(2), ui.sc(2))
    p.drawEllipse(QPointF(x0 + fw * 0.33, y0 + fh * 0.36), fw * 0.11, fw * 0.11)   # 太阳
    p.drawLine(QPointF(x0 + fw * 0.08, y0 + fh * 0.94), QPointF(x0 + fw * 0.40, y0 + fh * 0.52))
    p.drawLine(QPointF(x0 + fw * 0.40, y0 + fh * 0.52), QPointF(x0 + fw * 0.60, y0 + fh * 0.78))
    p.drawLine(QPointF(x0 + fw * 0.60, y0 + fh * 0.78), QPointF(x0 + fw * 0.94, y0 + fh * 0.42))
    p.end()
    _FILE_ICON_CACHE[key] = pm
    return pm


_REFRESH_ICON_CACHE = {}


def _refresh_icon(theme, disabled=False):
    '''「刷新」圆箭头图标：accent 色（禁用时灰色）QPainter 矢量绘制，按主题/DPI 缓存。'''
    key = (theme, disabled, ui.ui_scale())
    pm = _REFRESH_ICON_CACHE.get(key)
    if pm is not None:
        return pm
    s = ui.sc(16)
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    accents = {'nocturne': ('#e8a33d', '#55534d'),
               'mica': ('#0067c0', '#b4b4ba')}
    color = QColor(accents.get(theme, accents['nocturne'])[1 if disabled else 0])
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    w = max(1.8, ui.sc(2.0))
    p.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    pad = w + 1
    # 缺口朝右、顺时针扫 300°；终点在右上，切向即箭头指向
    p.drawArc(QRectF(pad, pad, s - 2 * pad, s - 2 * pad), 30 * 16, 300 * 16)
    cx = cy = s / 2.0
    rad = (s - 2 * pad) / 2.0
    a = math.radians(330)
    ex, ey = cx + rad * math.cos(a), cy + rad * math.sin(a)
    tx, ty = -math.sin(a), math.cos(a)
    hl = s * 0.42                          # 箭头两翼长
    for deg in (150, -150):
        ph = math.radians(deg)
        ux = tx * math.cos(ph) - ty * math.sin(ph)
        uy = tx * math.sin(ph) + ty * math.cos(ph)
        p.drawLine(QPointF(ex, ey), QPointF(ex + hl * ux, ey + hl * uy))
    p.end()
    _REFRESH_ICON_CACHE[key] = pm
    return pm


_ALIAS_ICON_CACHE = {}


def _alias_icon(kind, theme, angle=0):
    '''别名按钮图标：kind='check' 勾选 / 'spin' 转圈（angle 为弧起始角），
    accent 色 QPainter 矢量绘制，按主题/DPI/角度缓存。'''
    key = (kind, theme, angle, ui.ui_scale())
    pm = _ALIAS_ICON_CACHE.get(key)
    if pm is not None:
        return pm
    s = ui.sc(15)
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    accent = {'nocturne': '#e8a33d', 'mica': '#0067c0'}.get(theme, '#e8a33d')
    w = max(1.8, ui.sc(2))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(accent), w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    if kind == 'check':
        p.drawLine(QPointF(s * 0.24, s * 0.55), QPointF(s * 0.43, s * 0.72))
        p.drawLine(QPointF(s * 0.43, s * 0.72), QPointF(s * 0.78, s * 0.28))
    else:
        rect = QRectF(w, w, s - 2 * w, s - 2 * w)
        p.drawArc(rect, int(-angle * 16), int(270 * 16))   # 270° 弧，顺时针转
    p.end()
    _ALIAS_ICON_CACHE[key] = pm
    return pm


def _friendly_err(err):
    '''传输失败的原始错误（协议码 / 系统异常串，中英文混杂）映射为简短友好的
    提示；原始错误留在状态文字悬停提示里供排查。识别不了的一律「传输出错」。'''
    s = (err or '').lower()
    if not s:
        return ''
    if _NET_ERROR_HINTS['unconfirmed'] in s:
        return t('transfer.err.unconfirmed')
    if '10061' in s or 'connection refused' in s or _NET_ERROR_HINTS['refused'] in s:
        return t('transfer.err.offline')
    if '10054' in s or '10053' in s or 'reset' in s or 'aborted' in s or _NET_ERROR_HINTS['reset'] in s:
        return t('transfer.err.reset')
    if '10060' in s or 'timed out' in s or 'timeout' in s or _NET_ERROR_HINTS['timeout'] in s:
        return t('transfer.err.timeout')
    if _NET_ERROR_HINTS['offline'] in s:
        return t('transfer.err.offline')
    if '10051' in s or 'unreachable' in s or _NET_ERROR_HINTS['unreachable'] in s:
        return t('transfer.err.unreachable')
    if 'getaddrinfo' in s or '11001' in s or '11004' in s:
        return t('transfer.err.not_found')
    if 'errno 28' in s or 'no space' in s:
        return t('transfer.err.no_space')
    if 'errno 13' in s or 'permission' in s:
        return t('transfer.err.permission')
    if 'errno 2]' in s or 'no such file' in s:
        return t('transfer.err.missing')
    if 'no sessionid' in s:
        return t('transfer.err.no_session')
    if 'http 4' in s:
        return t('transfer.err.rejected')
    if 'http 5' in s or 'internal error' in s:
        return t('transfer.err.peer_error')
    return t('transfer.err.generic')


def _reveal_in_explorer(path):
    '''资源管理器打开所在文件夹并选中该文件。
    路径必须归一化并带引号：正斜杠或含空格时 /select 会退化成只打开文件夹不选中。
    必须传整条字符串命令：列表形式会被 list2cmdline 再加一层引号，explorer 解析不了。'''
    subprocess.Popen('explorer.exe /select,"%s"' % os.path.normpath(path))


def _default_save_dir(cfg):
    '''接收保存目录：配置优先，缺省 ~/Downloads/Zbox。'''
    d = cfg.transfer_dir
    if isinstance(d, str) and d:
        return d
    return os.path.join(os.path.expanduser('~'), 'Downloads', 'Zbox')


class _RecvDialog(QDialog):
    '''接收确认小弹窗：无边框置顶 Tool；Esc / Alt+F4 等同点「拒绝」
    （路由回 TransferWidget._recv_reject，保证阻塞中的 HTTP 线程被正常唤醒）。'''

    def __init__(self, parent, on_reject):
        super(_RecvDialog, self).__init__(
            parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self._on_reject = on_reject

    def reject(self):
        try:
            self._on_reject()
        except Exception:
            self.hide()


class _ElideLabel(QLabel):
    '''记录行名称标签：按实际宽度尾部省略（「…」），
    宽度变化时重新截断；完整文本攻e tooltip。'''
    def __init__(self, full):
        super(_ElideLabel, self).__init__()
        self._full = full
        self._relide()

    def resizeEvent(self, e):
        super(_ElideLabel, self).resizeEvent(e)
        self._relide()

    def _relide(self):
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideRight,
                                                    max(self.width(), ui.sc(8))))


class _ClickRow(glow.GlowCard):
    '''可整行点击的容器（设备选择用）。继承共享灯效卡片：默认无光，
    传输记录行在「传输中」时由 _update_record 点亮彩色跑马灯。'''
    clicked = Signal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super(_ClickRow, self).mouseReleaseEvent(e)


class TransferInfoDialog(QDialog):
    '''传输页门禁层 / 设置窗的「?」共用的说明弹窗：解释局域网传输 + 移动端入口。
    样式复用设置窗（#settingsDlg / #settingsPanel 区段）。'''

    DOWNLOAD_URL = 'https://zbox.wzyjc.cn/#download'

    def __init__(self, parent=None):
        super(TransferInfoDialog, self).__init__(parent)
        self.setObjectName('settingsDlg')
        self.setWindowTitle(t('transfer.info.title'))
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
        title = QLabel(t('transfer.info.heading'))
        title.setObjectName('setTitle')
        tb.addWidget(title)
        tb.addStretch(1)
        close = QToolButton()
        close.setObjectName('closeBtn')
        close.setText('✕')
        close.setFixedSize(ui.sc(28), ui.sc(24))
        close.setToolTip(t('common.close'))
        close.clicked.connect(self.reject)
        tb.addWidget(close)
        lay.addLayout(tb)

        def para(text, name='infoText'):
            lb = QLabel(text)
            lb.setObjectName(name)
            lb.setWordWrap(True)
            lay.addWidget(lb)
            return lb

        para(t('transfer.info.desc'))
        para(t('common.what_happens'), 'transferTitle')
        para(t('transfer.info.what'))
        para(t('transfer.info.security_title'), 'transferTitle')
        para(t('transfer.info.security'))
        para(t('transfer.info.mobile_title'), 'transferTitle')
        para(t('transfer.info.mobile'))

        btn_row = QHBoxLayout()
        btn_row.setSpacing(ui.sc(8))
        apk = QPushButton(t('transfer.download_apk'))
        apk.setObjectName('setBtn')
        apk.setCursor(Qt.PointingHandCursor)
        apk.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.DOWNLOAD_URL)))
        btn_row.addWidget(apk)
        btn_row.addStretch(1)
        ok = QPushButton(t('common.got_it'))
        ok.setObjectName('setSave')
        ok.setCursor(Qt.PointingHandCursor)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btn_row.addWidget(ok)
        lay.addLayout(btn_row)

        para(t('transfer.info.footer'), 'transferHint')

        self.setFixedWidth(ui.sc(320))
        self.adjustSize()
        # 英文文案换行后行数比中文多：adjustSize 按未换行的 sizeHint 定高会截掉段落，
        # 固定宽度后按布局的实际换行高度补足（中文本来够高则保持原高）。
        self.setFixedHeight(max(self.height(),
                                self.layout().totalHeightForWidth(self.width())))


class MobileGuideDialog(QDialog):
    '''「搜索不到设备」引导弹窗：提示同 WiFi + 装移动端，跳转官网下载页。
    样式复用设置窗（#settingsDlg / #settingsPanel 区段）。'''

    def __init__(self, parent=None):
        super(MobileGuideDialog, self).__init__(parent)
        self.setObjectName('settingsDlg')
        self.setWindowTitle(t('transfer.not_found'))
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
        title = QLabel(t('transfer.not_found'))
        title.setObjectName('setTitle')
        tb.addWidget(title)
        tb.addStretch(1)
        close = QToolButton()
        close.setObjectName('closeBtn')
        close.setText('\u2715')
        close.setFixedSize(ui.sc(28), ui.sc(24))
        close.setToolTip(t('common.close'))
        close.clicked.connect(self.reject)
        tb.addWidget(close)
        lay.addLayout(tb)

        para = QLabel(t('transfer.mobile_guide'))
        para.setObjectName('infoText')
        para.setWordWrap(True)
        lay.addWidget(para)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(ui.sc(8))
        dl = QPushButton(t('transfer.download_apk'))
        dl.setObjectName('setBtn')
        dl.setCursor(Qt.PointingHandCursor)
        dl.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl(TransferInfoDialog.DOWNLOAD_URL)))
        btn_row.addWidget(dl)
        btn_row.addStretch(1)
        ok = QPushButton(t('common.got_it'))
        ok.setObjectName('setSave')
        ok.setCursor(Qt.PointingHandCursor)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btn_row.addWidget(ok)
        lay.addLayout(btn_row)

        self.setFixedWidth(ui.sc(300))
        self.adjustSize()


class TransferWidget(QWidget):
    '''传输 tab。传输功能默认关闭：页面盖高斯模糊门禁层（「启用传输」+「?」说明），
    开启后才开始监听端口；启用失败（端口被占）门禁层切「不可用」提示形态。
    服务生命周期（TransferServer / Discovery 的创建与停止）由本类自持。'''

    notify = Signal(str, str)                       # 托盘气泡（标题, 内容）
    enabled_changed = Signal(bool)                  # 开关状态变化（设置窗同步勾选用）
    sig_devices = Signal()                          # 设备列表需刷新
    sig_scan_done = Signal()                        # 子网扫描结束
    sig_progress = Signal(str, str, object, object)       # 接收进度 session_id, file_id, done, total
    sig_file_done = Signal(str, str, str)           # session_id, file_id, saved_path
    sig_session_done = Signal(str)                  # session_id
    sig_cancelled = Signal(str)                     # session_id
    sig_recv_request = Signal(object, object, object)   # view, result, event
    sig_recv_timeout = Signal(str)                  # 确认超时 session_id
    sig_send_progress = Signal(str, object, object)       # 记录 key, done, total
    sig_send_done = Signal(str, bool, str)          # 记录 key, ok, err
    sig_firewall = Signal()                         # 检测到防火墙阻止规则
    sig_fw_result = Signal(str)                     # 防火墙修复结果 ok/error

    def __init__(self, cfg, device_info, parent=None, auto_start=True):
        super(TransferWidget, self).__init__(parent)
        self.cfg = cfg
        self.server = None
        self.discovery = None
        self._service_started = False   # 未 start 过的 server 不能 stop（shutdown 会死等）
        self.device_info = device_info
        self.theme_key = 'nocturne'
        self._files = []             # 待发送的本地路径
        self._selected_fp = None     # 选中设备的 fingerprint
        self._devices = {}           # 主动注册来的设备 {fp: (DeviceInfo, ip, last_seen)}
        self._dev_sig = None         # 设备行渲染签名（没变不重建，防闪烁）
        self._records = {}           # 记录 key -> dict
        self._rec_keys = []          # 记录顺序（新的在前）
        self._pending = None         # 待确认的接收请求 (session_id, key, result, event)
        self._expired = set()        # 已超时作废的接收确认 session_id
        self._progress_ts = {}       # 接收进度节流：{session_id: 上次 emit 时间}
        self._scanning = False
        self._fw_warned = False    # 防火墙拦截提示：每会话最多一次
        self._save_dir = _default_save_dir(cfg)
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.pane = QFrame()
        self.pane.setObjectName('transferRoot')
        pl = QVBoxLayout(self.pane)
        pl.setContentsMargins(ui.sc(8), ui.sc(8), ui.sc(8), ui.sc(8))
        pl.setSpacing(ui.sc(6))
        root.addWidget(self.pane)

        # ---- 本机别名 ----
        alias_row = QHBoxLayout()
        alias_row.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        alias_row.setSpacing(ui.sc(8))
        lab = QLabel(t('transfer.alias'))
        lab.setObjectName('transferLabel')
        self.alias_edit = QLineEdit(device_info.alias if device_info else '')
        self.alias_edit.setObjectName('aliasEdit')
        self.alias_edit.setMaxLength(32)
        self.alias_edit.editingFinished.connect(self._alias_commit)
        self._alias_busy = False           # 打钩按钮转圈期间屏蔽重复点击
        self._alias_angle = 0              # 转圈弧当前起始角
        self._alias_timer = QTimer(self)
        self._alias_timer.setInterval(50)
        self._alias_timer.timeout.connect(self._alias_spin)
        self.alias_ok_btn = QToolButton()
        self.alias_ok_btn.setObjectName('aliasOkBtn')
        self.alias_ok_btn.setIconSize(QSize(ui.sc(15), ui.sc(15)))
        self.alias_ok_btn.setIcon(QIcon(_alias_icon('check', self.theme_key)))
        self.alias_ok_btn.setToolTip(t('transfer.alias.tooltip'))
        self.alias_ok_btn.clicked.connect(self._alias_btn_clicked)
        alias_row.addWidget(lab)
        alias_row.addWidget(self.alias_edit, 1)
        alias_row.addWidget(self.alias_ok_btn)
        pl.addLayout(alias_row)

        # 更新成功浮窗：pane 子控件绝对定位（按钮正上方坐标系），
        # 不抢鼠标事件；_toast_seq 防止连续点击时旧的淡出定时器误杀新浮窗
        self.alias_toast = QLabel(t('transfer.alias.updated'), self.pane)
        self.alias_toast.setObjectName('aliasToast')
        self.alias_toast.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.alias_toast.hide()
        self._toast_opacity = QGraphicsOpacityEffect(self.alias_toast)
        self._toast_opacity.setOpacity(0.0)
        self.alias_toast.setGraphicsEffect(self._toast_opacity)
        self._toast_anim = None
        self._toast_seq = 0

        # ---- 设备列表 ----
        dev_head = QHBoxLayout()
        dev_head.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        dev_title = QLabel(t('transfer.devices'))
        dev_title.setObjectName('transferTitle')
        self.refresh_btn = QToolButton()
        self.refresh_btn.setObjectName('refreshBtn')
        self.refresh_btn.setIcon(QIcon(_refresh_icon(self.theme_key)))
        self.refresh_btn.setIconSize(QSize(ui.sc(16), ui.sc(16)))
        self.refresh_btn.setFixedSize(ui.sc(26), ui.sc(26))
        self.refresh_btn.setToolTip(t('common.refresh'))
        self.refresh_btn.clicked.connect(self._refresh_clicked)
        dev_head.addWidget(dev_title)
        dev_head.addStretch(1)
        dev_head.addWidget(self.refresh_btn)
        pl.addLayout(dev_head)

        self.dev_scroll = QScrollArea()
        self.dev_scroll.setObjectName('transferScroll')
        self.dev_scroll.setWidgetResizable(True)
        self.dev_scroll.setFrameShape(QFrame.NoFrame)
        self.dev_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.dev_scroll.setFixedHeight(ui.sc(96))
        self.dev_box = QWidget()
        self.dev_box.setObjectName('transferBox')
        self.dev_lay = QVBoxLayout(self.dev_box)
        self.dev_lay.setContentsMargins(ui.sc(4), 0, ui.sc(4), 0)
        self.dev_lay.setSpacing(ui.sc(2))
        self.dev_lay.addStretch(1)
        self.dev_scroll.setWidget(self.dev_box)
        pl.addWidget(self.dev_scroll)

        # ---- 发送区：整段虚线拖放区（可点击选文件）+ 等高发送按钮 ----
        send_row = QHBoxLayout()
        send_row.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        send_row.setSpacing(ui.sc(8))
        self.pick_btn = QToolButton()
        self.pick_btn.setObjectName('pickBtn')
        self.pick_btn.setText(t('transfer.pick'))
        self.pick_btn.setFixedHeight(ui.sc(40))
        self.pick_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.pick_btn.clicked.connect(self._pick_files)
        self.send_btn = QPushButton(t('transfer.send'))
        self.send_btn.setObjectName('sendBtn')
        self.send_btn.setFixedHeight(ui.sc(40))
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self._send_clicked)
        send_row.addWidget(self.pick_btn, 1)
        send_row.addWidget(self.send_btn)
        pl.addLayout(send_row)

        # ---- 传输记录 ----
        rec_head = QHBoxLayout()
        rec_head.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        rt = QLabel(t('transfer.records'))
        rt.setObjectName('transferTitle')
        rec_head.addWidget(rt)
        rec_head.addStretch(1)
        pl.addLayout(rec_head)

        self.rec_scroll = QScrollArea()
        self.rec_scroll.setObjectName('transferScroll')
        self.rec_scroll.setWidgetResizable(True)
        self.rec_scroll.setFrameShape(QFrame.NoFrame)
        self.rec_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rec_box = QWidget()
        self.rec_box.setObjectName('transferBox')
        self.rec_lay = QVBoxLayout(self.rec_box)
        self.rec_lay.setContentsMargins(ui.sc(4), 0, ui.sc(4), 0)
        self.rec_lay.setSpacing(ui.sc(4))
        self.rec_lay.addStretch(1)
        self.rec_scroll.setWidget(self.rec_box)
        pl.addWidget(self.rec_scroll, 1)

        self.rec_empty = QLabel(t('transfer.records.empty'))
        self.rec_empty.setObjectName('transferHint')
        self.rec_empty.setAlignment(Qt.AlignCenter)
        self.rec_lay.insertWidget(0, self.rec_empty)

        # ---- 接收确认窗：独立小弹窗（宽度固定、高度按内容自适应）----
        self.recv = _RecvDialog(self, self._recv_reject)
        self.recv.setObjectName('recvDialog')
        self.recv.setFixedWidth(ui.sc(320))
        rl = QVBoxLayout(self.recv)
        rl.setContentsMargins(ui.sc(18), ui.sc(16), ui.sc(18), ui.sc(14))
        rl.setSpacing(ui.sc(10))
        title = QLabel(t('transfer.recv.title'))
        title.setObjectName('transferTitle')
        # 来源行：来自 Pixel 6 · 1 个文件 · 共 2.4 MB
        self.recv_from = QLabel()
        self.recv_from.setObjectName('recvFromLine')
        # 文件清单卡片（虚线框）：每行 图标 + 文件名，吸满中部空间
        file_card = QFrame()
        file_card.setObjectName('recvFileCard')
        self.recv_files_lay = QVBoxLayout(file_card)
        self.recv_files_lay.setContentsMargins(ui.sc(12), ui.sc(9), ui.sc(12), ui.sc(9))
        self.recv_files_lay.setSpacing(ui.sc(6))
        self._recv_icons = []                # 行图标：主题切换时要重绘
        dir_row = QHBoxLayout()
        dir_row.setSpacing(ui.sc(6))
        self.recv_dir = QLabel()
        self.recv_dir.setObjectName('recvDir')
        self.recv_dir.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        chg = QToolButton()
        chg.setObjectName('linkBtn')        # 无边框链接样式
        chg.setText(t('transfer.recv.change'))
        chg.setCursor(Qt.PointingHandCursor)
        chg.clicked.connect(self._recv_change_dir)
        dir_row.addWidget(self.recv_dir, 1)
        dir_row.addWidget(chg)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(ui.sc(10))
        no = QPushButton(t('transfer.recv.reject'))
        no.setObjectName('setBtn')          # 复用设置窗按钮样式
        yes = QPushButton(t('transfer.recv.accept'))
        yes.setObjectName('setSave')
        no.clicked.connect(self._recv_reject)
        yes.clicked.connect(self._recv_accept)
        btn_row.addStretch(1)
        btn_row.addWidget(no)
        btn_row.addWidget(yes)
        rl.addWidget(title)
        rl.addWidget(self.recv_from)
        rl.addWidget(file_card)
        rl.addLayout(dir_row)
        rl.addLayout(btn_row)
        self.recv.hide()

        # ---- 信号接线（全部在主线程执行） ----
        self.sig_devices.connect(self._refresh_devices)
        self.sig_scan_done.connect(self._scan_done)
        self.sig_progress.connect(self._on_progress)
        self.sig_file_done.connect(self._on_file_done)
        self.sig_session_done.connect(self._on_session_done)
        self.sig_cancelled.connect(self._on_cancelled)
        self.sig_recv_request.connect(self._show_recv)
        self.sig_recv_timeout.connect(self._on_recv_timeout)
        self.sig_send_progress.connect(self._on_send_progress)
        self.sig_send_done.connect(self._on_send_done)
        self.sig_firewall.connect(self._on_firewall_blocked)
        self.sig_fw_result.connect(self._on_fw_result)

        # ---- 门禁层：未开启传输时盖住整页（内容高斯模糊）----
        self._build_gate()

        self._refresh_devices()

        # auto_start=False（截图自检）：不起服务也不盖门禁层，按功能态渲染
        if not auto_start:
            return
        if bool(cfg.data.get('transfer_enabled')):
            if not self.enable_service():
                self._show_gate('occupied')   # 端口被占：提示，确定后回到未开启态
        else:
            self._show_gate('enable')

    # ---------------- 通用 ----------------

    def set_theme(self, key):
        '''主题切换：颜色全走 QSS；绘制的位图图标（记录/清单/刷新/别名）这里按主题重刷。'''
        self.theme_key = key
        try:
            for rec in getattr(self, '_records', {}).values():
                lab = rec.get('icon_lab')
                if lab is not None:
                    lab.setPixmap(_file_icon(key))
            for ic in getattr(self, '_recv_icons', []):
                ic.setPixmap(_file_icon(key, 20))
            if getattr(self, 'refresh_btn', None) is not None:
                self.refresh_btn.setIcon(
                    QIcon(_refresh_icon(key, not self.refresh_btn.isEnabled())))
            if getattr(self, 'alias_ok_btn', None) is not None:
                kind = 'spin' if self._alias_busy else 'check'
                self.alias_ok_btn.setIcon(QIcon(_alias_icon(kind, key, self._alias_angle)))
        except Exception:
            pass

    # ---------------- 服务生命周期 ----------------

    def service_enabled(self):
        return self.server is not None

    def _wire_server(self, server, discovery):
        '''网络回调接线：后台线程里只发信号，不碰 UI。'''
        server.on_device_found = self._cb_device_found
        server.on_receive_request = self._cb_receive_request
        server.on_progress = self._cb_progress   # 经 100ms 节流的中间函数
        server.on_file_done = self.sig_file_done.emit
        server.on_session_done = self.sig_session_done.emit
        server.on_cancelled = self.sig_cancelled.emit
        discovery.on_device_found = self._cb_device_found

    def enable_service(self):
        '''启动端口监听 + 设备发现；端口被占返回 False（界面保持门禁层）。'''
        if self.server is not None:
            return True
        try:
            server = transfer.TransferServer(self.device_info)
        except Exception:
            return False
        discovery = transfer.Discovery(self.device_info)
        self._wire_server(server, discovery)
        server.start()
        discovery.start()
        self.server = server
        self.discovery = discovery
        self._service_started = True
        self._check_firewall()
        return True

    def disable_service(self):
        '''停止监听并释放端口，清空设备列表。'''
        server, discovery = self.server, self.discovery
        self.server = None
        self.discovery = None
        self._devices = {}
        self._selected_fp = None
        self._refresh_devices()
        if server is None:
            return
        for attr in ('on_device_found', 'on_receive_request', 'on_progress',
                     'on_file_done', 'on_session_done', 'on_cancelled'):
            setattr(server, attr, None)
        discovery.on_device_found = None
        if self._service_started:
            discovery.stop()
            server.stop()
            self._service_started = False

    def set_enabled(self, on):
        '''界面开关入口（传输页「启用传输」/ 设置窗勾选共用）。
        开启失败（端口被占）→ 门禁层切「不可用」形态，返回 False。'''
        try:
            if on:
                if self.enable_service():
                    self.cfg.set('transfer_enabled', True)
                    self._hide_gate()
                    self.enabled_changed.emit(True)
                    return True
                self.cfg.set('transfer_enabled', False)
                self._show_gate('occupied')
                self.enabled_changed.emit(False)
                return False
            self.disable_service()
            self.cfg.set('transfer_enabled', False)
            self._show_gate('enable')
            self.enabled_changed.emit(False)
            return True
        except Exception:
            return False

    def shutdown_service(self):
        '''程序退出：只停真正 start 过的服务。'''
        try:
            if self._service_started and self.server is not None:
                self.discovery.stop()
                self.server.stop()
                self._service_started = False
        except Exception:
            pass

    # ---------------- Windows 防火墙 ----------------

    def _check_firewall(self):
        '''服务启动后后台查一次防火墙阻止规则（每会话最多提示一次）。
        首次启用时系统安全警告被点「取消」会留下针对本程序 exe 的阻止规则：
        出站正常（别的设备能发现本机）、入站被静默丢弃（发现不了别人、收不到文件）。'''
        if self._fw_warned:
            return
        def work():
            try:
                if sysutil.firewall_blocked():
                    self._fw_warned = True
                    self.sig_firewall.emit()
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _on_firewall_blocked(self):
        '''命中阻止规则：弹窗引导一键修复（需管理员权限）。'''
        if self.server is None:     # 检测期间传输已被关闭
            return
        from video_ui import _ConfirmDialog   # 运行期导入：避开 import 期循环
        dlg = _ConfirmDialog(
            self, title=t('transfer.fw.title'),
            text=t('transfer.fw.text'),
            ok_text=t('transfer.fw.fix'))
        if dlg.exec() != QDialog.Accepted:
            return
        threading.Thread(target=self._fix_firewall, daemon=True).start()

    def _fix_firewall(self):
        try:
            r = sysutil.fix_firewall_rules()
        except Exception:
            r = 'error'
        if r != 'cancelled':            # 用户在 UAC 弹窗点「否」：静默
            self.sig_fw_result.emit(r)

    def _on_fw_result(self, r):
        from video_ui import _ConfirmDialog   # 运行期导入：避开 import 期循环
        if r == 'ok':
            _ConfirmDialog(self, title=t('transfer.fw.ok_title'),
                           text=t('transfer.fw.ok_text'),
                           ok_text=t('transfer.fw.dismiss')).exec()
        else:
            _ConfirmDialog(self, title=t('transfer.fw.fail_title'),
                           text=t('transfer.fw.fail_text'),
                           ok_text=t('transfer.fw.dismiss')).exec()

    # ---------------- 门禁层 ----------------

    def _build_gate(self):
        '''门禁层：与接收确认层同款的页内遮罩（pane 的兄弟，不随 pane 一起模糊）。'''
        self._blur = None
        self._gate_mode = 'enable'
        self.gate = QFrame(self)
        self.gate.setObjectName('transferGate')
        gl = QVBoxLayout(self.gate)
        gl.setContentsMargins(ui.sc(18), ui.sc(16), ui.sc(18), ui.sc(14))
        gl.setSpacing(ui.sc(10))
        gl.addStretch(1)
        self.gate_msg = QLabel(t('transfer.gate.occupied'))
        self.gate_msg.setObjectName('transferHint')
        self.gate_msg.setAlignment(Qt.AlignCenter)
        gl.addWidget(self.gate_msg)
        self.gate_ok = QPushButton(t('transfer.gate.enable'))
        self.gate_ok.setObjectName('setSave')           # 复用设置窗主按钮样式
        self.gate_ok.setCursor(Qt.PointingHandCursor)
        self.gate_ok.clicked.connect(self._gate_ok_clicked)
        gl.addWidget(self.gate_ok, 0, Qt.AlignCenter)
        # 「?」圆形说明按钮：放在「启用传输」正下方居中
        self.gate_help = QToolButton()
        self.gate_help.setObjectName('gateHelpBtn')
        self.gate_help.setText('?')
        self.gate_help.setFixedSize(ui.sc(20), ui.sc(20))
        self.gate_help.setCursor(Qt.PointingHandCursor)
        self.gate_help.setToolTip(t('settings.transfer.help'))
        self.gate_help.clicked.connect(lambda: TransferInfoDialog(self).exec())
        gl.addWidget(self.gate_help, 0, Qt.AlignCenter)
        gl.addStretch(1)
        self.gate.hide()

    def _show_gate(self, mode):
        '''mode='enable'：启用按钮 + 「?」；mode='occupied'：端口被占提示 + 确定。'''
        try:
            self._gate_mode = mode
            self.gate_msg.setVisible(mode == 'occupied')
            self.gate_ok.setText(t('common.ok') if mode == 'occupied'
                                 else t('transfer.gate.enable'))
            self.gate_help.setVisible(mode != 'occupied')
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
            if self._gate_mode == 'occupied':
                # 「确定」：回到未开启态
                self.cfg.set('transfer_enabled', False)
                self._show_gate('enable')
                self.enabled_changed.emit(False)
            else:
                # 启动期间禁用按钮防连点并显示 loading：成功后门禁层隐藏，
                # 失败已切「确定」形态，异常返回（未切形态）则恢复按钮文字
                self.gate_ok.setEnabled(False)
                self.gate_ok.setText(t('transfer.gate.enabling'))
                self.gate_ok.repaint()
                self.set_enabled(True)
                self.gate_ok.setEnabled(True)
                if self._gate_mode == 'enable':
                    self.gate_ok.setText(t('transfer.gate.enable'))
        except Exception:
            pass

    def resizeEvent(self, e):
        super(TransferWidget, self).resizeEvent(e)
        try:
            if hasattr(self, 'gate'):
                self.gate.setGeometry(self.rect())
        except Exception:
            pass

    def dragEnterEvent(self, e):
        try:
            if self.server is not None and e.mimeData().hasUrls() and \
                    any(u.isLocalFile() for u in e.mimeData().urls()):
                e.acceptProposedAction()
                self._set_drop_highlight(True)
        except Exception:
            pass

    def dragLeaveEvent(self, e):
        self._set_drop_highlight(False)
        super(TransferWidget, self).dragLeaveEvent(e)

    def _set_drop_highlight(self, on):
        '''拖拽悬停时高亮「选择文件」按钮（QSS 动态属性切换）。'''
        try:
            self.pick_btn.setProperty('drop', 'true' if on else 'false')
            self.pick_btn.style().unpolish(self.pick_btn)
            self.pick_btn.style().polish(self.pick_btn)
        except Exception:
            pass

    def dropEvent(self, e):
        self._set_drop_highlight(False)
        try:
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            self._set_files(self._files + _expand_paths([p for p in paths if p]))
        except Exception:
            pass

    # ---------------- 本机别名 ----------------

    def _alias_commit(self):
        try:
            alias = self.alias_edit.text().strip()
            if not alias or self.device_info is None or alias == self.device_info.alias:
                return
            self.device_info.alias = alias
            self.cfg.set('transfer_alias', alias)
        except Exception:
            pass

    def _alias_btn_clicked(self):
        '''打钩按钮：提交别名后图标转圈约 0.8s 再变回勾选，作为更新成功的反馈
        （别名提交本身是同步即成的，转圈纯为可感知的确认动效）。'''
        try:
            if self._alias_busy:
                return
            alias = self.alias_edit.text().strip()
            if not alias or self.device_info is None:
                return
            if alias != self.device_info.alias:
                self.device_info.alias = alias
                self.cfg.set('transfer_alias', alias)
            self.alias_edit.clearFocus()
            self._alias_busy = True
            self._alias_angle = 0
            self._alias_spin()
            self._alias_timer.start()
            QTimer.singleShot(800, self._alias_done)
        except Exception:
            pass

    def _alias_spin(self):
        self._alias_angle = (self._alias_angle + 30) % 360
        self.alias_ok_btn.setIcon(QIcon(_alias_icon('spin', self.theme_key, self._alias_angle)))

    def _alias_done(self):
        try:
            self._alias_timer.stop()
            self._alias_busy = False
            self.alias_ok_btn.setIcon(QIcon(_alias_icon('check', self.theme_key)))
            self._show_alias_toast()
        except Exception:
            pass

    def _show_alias_toast(self):
        '''成功浮窗：淡入 -> 停留约 1s -> 淡出，定位在打钩按钮左侧。'''
        try:
            if self._toast_anim is not None:
                self._toast_anim.stop()
            toast = self.alias_toast
            toast.adjustSize()
            pos = self.alias_ok_btn.pos()          # 按钮父控件就是 pane
            x = pos.x() - toast.width() - ui.sc(8)
            y = pos.y() + (self.alias_ok_btn.height() - toast.height()) // 2
            toast.move(max(0, x), max(0, y))
            toast.raise_()
            toast.show()
            self._toast_anim = QPropertyAnimation(self._toast_opacity, b'opacity', self)
            self._toast_anim.setDuration(160)
            self._toast_anim.setStartValue(self._toast_opacity.opacity())
            self._toast_anim.setEndValue(1.0)
            self._toast_anim.start()
            self._toast_seq += 1
            seq = self._toast_seq
            QTimer.singleShot(1100, lambda s=seq: self._hide_alias_toast(s))
        except Exception:
            pass

    def _hide_alias_toast(self, seq):
        try:
            if seq != self._toast_seq or not self.alias_toast.isVisible():
                return
            if self._toast_anim is not None:
                self._toast_anim.stop()
            self._toast_anim = QPropertyAnimation(self._toast_opacity, b'opacity', self)
            self._toast_anim.setDuration(260)
            self._toast_anim.setStartValue(self._toast_opacity.opacity())
            self._toast_anim.setEndValue(0.0)
            self._toast_anim.finished.connect(self.alias_toast.hide)
            self._toast_anim.start()
        except Exception:
            pass

    # ---------------- 设备列表 ----------------

    def _cb_device_found(self, info, ip):
        '''发现/注册回调（网络线程）：登记主动注册来的设备，发信号让主线程刷新。'''
        try:
            self._devices[info.fingerprint] = (info, ip, time.time())
            self.sig_devices.emit()
        except Exception:
            pass

    def _refresh_devices(self):
        '''主线程：合并组播/扫描（discovery，自带 TTL）与主动注册的设备，重建行。'''
        try:
            merged = {}
            if self.discovery is not None:
                got = self.discovery.get_devices()
                for info, ip in (got.values() if isinstance(got, dict) else got):
                    merged[info.fingerprint] = (info, ip)
            for fp, (info, ip, seen) in list(self._devices.items()):
                if fp not in merged:
                    merged[fp] = (info, ip)
            self._render_devices(merged)
        except Exception:
            pass

    def _render_devices(self, merged):
        if self._selected_fp is None:
            self._selected_fp = next(iter(merged), None)   # 仅首次默认选中第一台
        elif self._selected_fp not in merged:
            self._selected_fp = None   # 原选中离线：不静默跳台，等用户显式重选
        sig = sorted((fp, info.alias, ip, fp == self._selected_fp)
                     for fp, (info, ip) in merged.items())
        if sig == self._dev_sig:
            self._sync_send_enabled()
            return
        self._dev_sig = sig
        while self.dev_lay.count() > 1:   # 末尾是 stretch
            item = self.dev_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not merged:
            hint = QLabel(t('transfer.devices.empty'))
            hint.setWordWrap(True)
            hint.setObjectName('transferHint')
            hint.setAlignment(Qt.AlignCenter)
            self.dev_lay.insertWidget(0, hint)
            nofind = QToolButton()
            nofind.setObjectName('linkBtn')     # 无边框链接样式
            nofind.setText(t('transfer.not_found'))
            nofind.setCursor(Qt.PointingHandCursor)
            nofind.clicked.connect(self._show_mobile_guide)
            self.dev_lay.insertWidget(1, nofind, alignment=Qt.AlignCenter)
        else:
            for fp, (info, ip) in sorted(merged.items(),
                                         key=lambda kv: kv[1][0].alias.lower()):
                row = _ClickRow()
                row.setObjectName('deviceRow')
                row.setProperty('sel', 'true' if fp == self._selected_fp else 'false')
                row.setCursor(Qt.PointingHandCursor)
                lay = QHBoxLayout(row)
                lay.setContentsMargins(ui.sc(8), ui.sc(5), ui.sc(8), ui.sc(5))
                lay.setSpacing(ui.sc(8))
                chip = QLabel({'mobile': t('transfer.device.mobile'),
                               'desktop': t('transfer.device.desktop')}
                              .get(info.device_type, t('transfer.device.other')))
                chip.setObjectName('deviceType')
                name = QLabel(info.alias or ip)
                name.setObjectName('deviceAlias')
                name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                online = QLabel(t('transfer.device.online'))
                online.setObjectName('deviceOnline')
                row.setToolTip(ip)
                lay.addWidget(chip)
                lay.addWidget(name, 1)
                lay.addWidget(online)
                row.clicked.connect(lambda fp=fp: self._select_device(fp))
                self.dev_lay.insertWidget(self.dev_lay.count() - 1, row)
        self._sync_send_enabled()

    def _show_mobile_guide(self):
        try:
            MobileGuideDialog(self).exec()
        except Exception:
            pass

    def _select_device(self, fp):
        try:
            self._selected_fp = fp
            self._refresh_devices()
        except Exception:
            pass

    def _refresh_clicked(self):
        '''「刷新」：LocalSend 语义——清空列表、重新宣告一次，只信本次应答；
        组播宽限（3s）内一台设备都没有才回退 /24 子网扫描（减少请求）。'''
        try:
            if self.discovery is None or self._scanning:
                return
            self._scanning = True
            self.refresh_btn.setEnabled(False)
            self.refresh_btn.setIcon(QIcon(_refresh_icon(self.theme_key, True)))
            self._devices = {}
            self.discovery.clear_devices()
            self._selected_fp = None
            self._refresh_devices()
            self.discovery.announce()
            QTimer.singleShot(3000, self._refresh_grace_done)
        except Exception:
            pass

    def _refresh_grace_done(self):
        '''组播宽限结束：已有设备直接收尾；仍为空则起子网扫描兜底。'''
        try:
            known = bool(self._devices)
            if not known and self.discovery is not None:
                known = bool(self.discovery.get_devices())
            if known or self.discovery is None:
                self._scan_done()
                return
            threading.Thread(target=self._scan_worker,
                             name='transfer-scan', daemon=True).start()
        except Exception:
            self._scan_done()

    def _scan_worker(self):
        try:
            self.discovery.scan_subnet()
        except Exception:
            pass
        self.sig_scan_done.emit()

    def _scan_done(self):
        try:
            self._scanning = False
            self.refresh_btn.setEnabled(True)
            self.refresh_btn.setIcon(QIcon(_refresh_icon(self.theme_key)))
            self._refresh_devices()
        except Exception:
            pass

    # ---------------- 发送 ----------------

    def _pick_files(self):
        try:
            menu = QMenu(self)
            act_files = menu.addAction(t('transfer.pick_files'))
            act_dir = menu.addAction(t('transfer.pick_folder'))
            act = menu.exec_(self.pick_btn.mapToGlobal(self.pick_btn.rect().bottomLeft()))
            if act is act_files:
                paths, _ = QFileDialog.getOpenFileNames(self, t('transfer.pick_files.title'))
            elif act is act_dir:
                d = QFileDialog.getExistingDirectory(self, t('transfer.pick_folder.title'))
                paths = [d] if d else []
            else:
                paths = []
            if paths:
                self._set_files(self._files + _expand_paths(paths))
        except Exception:
            pass

    def _set_files(self, files):
        try:
            seen = set()
            self._files = [t for t in files if not (t[0] in seen or seen.add(t[0]))]
            if self._files:
                total = 0
                for p, _rel in self._files:
                    try:
                        total += os.path.getsize(p)
                    except OSError:
                        pass
                self.pick_btn.setText(t('transfer.files.selected',
                                        count=len(self._files),
                                        size=_fmt_size(total)))
                self.pick_btn.setToolTip('\n'.join(rel for _p, rel in self._files))
            else:
                self.pick_btn.setText(t('transfer.pick'))
                self.pick_btn.setToolTip('')
            self._sync_send_enabled()
        except Exception:
            pass

    def _sync_send_enabled(self):
        try:
            self.send_btn.setEnabled(bool(self._selected_fp) and bool(self._files))
        except Exception:
            pass

    def _send_clicked(self):
        try:
            fp = self._selected_fp
            if not fp or not self._files:
                return
            merged = self._devices_merged()
            if fp not in merged:      # 刚离线：刷新列表后放弃本次发送
                self._refresh_devices()
                return
            info, ip = merged[fp]
            files = list(self._files)
            names = [rel for _p, rel in files]
            total = 0
            for p, _rel in files:
                try:
                    total += os.path.getsize(p)
                except OSError:
                    pass
            key = self._add_record('up', names, total, info.alias or ip,
                                   fp=fp, files=files)
            cancel_event = self._records[key]['cancel_event']
            self._set_files([])
            threading.Thread(target=self._send_worker,
                             args=(key, ip, info.port, files, cancel_event),
                             name='transfer-send', daemon=True).start()
        except Exception:
            pass

    def _devices_merged(self):
        '''当前可见设备 {fp: (DeviceInfo, ip)}（与 _refresh_devices 同一口径）。'''
        merged = {}
        if self.discovery is not None:
            got = self.discovery.get_devices()
            for info, ip in (got.values() if isinstance(got, dict) else got):
                merged[info.fingerprint] = (info, ip)
        for fp, (info, ip, seen) in list(self._devices.items()):
            if fp not in merged:
                merged[fp] = (info, ip)
        return merged

    def _send_worker(self, key, ip, port, files, cancel_event, base=0, idx_map=None):
        '''工作线程：send_files 阻塞调用，进度/结果经信号回主线程。
        base/idx_map 供断点续传的重试：base = 前几轮已传完的字节数（进度从这里继续，
        总大小保持原值），idx_map = 本轮子清单在原始清单中的下标（completed_idx 记账换算用）。'''
        sizes = []
        for p, _rel in files:
            try:
                sizes.append(os.path.getsize(p))
            except OSError:
                sizes.append(0)
        total_all = base + sum(sizes)

        last_emit = [0.0]
        last_idx = [-1]      # 上传顺序进行：当前下标之前的文件都已传完
        finished = [set()]

        def on_progress(index, done, _total):
            # 100ms 节流；当前文件的完成帧必发（否则进度会卡在 99%）
            if index > last_idx[0]:
                last_idx[0] = index
            if sizes[index] and done >= sizes[index]:
                finished[0].add(index)
            now = time.time()
            if done < sizes[index] and now - last_emit[0] < 0.1:
                return
            last_emit[0] = now
            self.sig_send_progress.emit(key, base + sum(sizes[:index]) + done,
                                        total_all)

        def on_done(ok, err):
            if not ok:
                # 记录已传完的文件（换算回原始清单下标并与前几轮合并），
                # 供「重试」断点续传跳过
                done_local = set(range(max(last_idx[0], 0))) | finished[0]
                if idx_map is not None:
                    done_local = set(idx_map[i] for i in done_local)
                rec = self._records.get(key)
                if rec is not None:
                    rec['completed_idx'] = sorted(
                        set(rec.get('completed_idx') or []) | done_local)
            self.sig_send_done.emit(key, bool(ok), '%s' % (err or ''))

        try:
            send_files(ip, port, files, on_progress=on_progress, on_done=on_done,
                       device_info=self.device_info, cancel_event=cancel_event)
        except Exception as exc:
            # 核心层已兜底，理论不可达；双保险防线程静默死
            self.sig_send_done.emit(key, False, '%s' % exc)

    def _on_send_progress(self, key, done, total):
        try:
            rec = self._records.get(key)
            if rec is None or rec['state'] not in ('wait', 'busy'):
                return
            rec['state'] = 'busy'
            rec['done'] = done
            if total:
                rec['total'] = total
            self._update_record(rec)
        except Exception:
            pass

    def _on_send_done(self, key, ok, err):
        try:
            rec = self._records.get(key)
            if rec is None:
                return
            rec.pop('err_friendly', None)   # 新一轮结果：丢弃重试前的展示文案
            if ok:
                rec['state'] = 'done'
                rec['done'] = rec['total']
            elif err == 'rejected':
                rec['state'] = 'rejected'
            elif err == 'cancelled':
                rec['state'] = 'cancelled'
            else:
                rec['state'] = 'fail'
                rec['err'] = err
            self._update_record(rec)
        except Exception:
            pass

    def _cancel_send(self, key):
        '''取消按钮：置位该发送任务的 cancel_event，结果以 on_done 为准。'''
        try:
            rec = self._records.get(key)
            if rec is None or rec['direction'] != 'up':
                return
            ev = rec.get('cancel_event')
            if ev is None or rec['state'] not in ('wait', 'busy'):
                return
            ev.set()
            rec['state'] = 'cancelling'      # 先显示「取消中…」，等 on_done('cancelled') 落实
            self._update_record(rec)
        except Exception:
            pass

    def _retry_send(self, key):
        '''失败记录重试：断点续传（文件粒度）——上一轮已传完的文件跳过不重发；
        中断的文件接收端已清理半成品，从头重传。复传原记录行。'''
        try:
            rec = self._records.get(key)
            if not rec or rec['direction'] != 'up' or rec['state'] != 'fail':
                return
            files = rec.get('files') or []
            if not files:
                return
            merged = self._devices_merged()
            if rec.get('fp') not in merged:      # 对端不在线：刷新设备列表并更新失败文案
                self._refresh_devices()
                rec['err'] = ''
                rec['err_friendly'] = t('transfer.err.offline')
                self._update_record(rec)
                return
            info, ip = merged[rec['fp']]
            done_idx = set(rec.get('completed_idx') or [])
            idx_map = [i for i in range(len(files)) if i not in done_idx]
            if not idx_map:      # 全部传完还失败（收尾阶段出错）：整批重传
                idx_map = list(range(len(files)))
                done_idx = set()
            remain = [files[i] for i in idx_map]
            # 进度不从 0 开始：已传完文件的字节数作为基数，总大小保持原值
            base = 0
            for i in done_idx:
                try:
                    base += os.path.getsize(files[i][0])
                except OSError:
                    pass
            rec['cancel_event'] = threading.Event()
            rec['state'] = 'wait'
            rec['done'] = base
            rec['err'] = ''
            rec.pop('err_friendly', None)
            rec.pop('_speed', None)
            rec.pop('_tick', None)
            rec.pop('_stat_ts', None)
            rec['state_lab'].setToolTip('')
            self._update_record(rec)
            threading.Thread(target=self._send_worker,
                             args=(key, ip, info.port, remain, rec['cancel_event']),
                             kwargs={'base': base, 'idx_map': idx_map},
                             name='transfer-send', daemon=True).start()
        except Exception:
            pass

    # ---------------- 接收 ----------------

    def _cb_receive_request(self, session):
        '''HTTP 线程阻塞调用：把请求转给主线程弹确认层，等用户决定（超时按拒绝）。

        返回保存目录 str（接受）或 None（拒绝/超时）。'''
        try:
            info = session.get('info')
            files = session.get('files') or {}
            names = []
            total = 0
            for fid, meta in files.items():
                meta = meta if isinstance(meta, dict) else {}
                path = meta.get('path')
                if isinstance(path, str) and path.strip():
                    names.append(path)   # 文件夹传输：显示目录结构
                else:
                    names.append(os.path.basename(str(meta.get('fileName') or '')) or fid)
                try:
                    total += int(meta.get('size') or 0)
                except (TypeError, ValueError):
                    pass
            view = {'session_id': session.get('id'),
                    'alias': getattr(info, 'alias', '') or session.get('ip') or '',
                    'names': names, 'total': total}
            result = {'dir': None}
            event = threading.Event()
            self.sig_recv_request.emit(view, result, event)
            if event.wait(RECV_CONFIRM_TIMEOUT):
                return result['dir']
            self._expired.add(view['session_id'])   # 标记已超时：迟到的「接受」按拒绝处理
            self.sig_recv_timeout.emit(view['session_id'])
        except Exception:
            pass
        return None

    def _cb_progress(self, session_id, file_id, done, total):
        '''接收进度回调（HTTP 线程）：100ms 节流，完成帧必发。'''
        try:
            now = time.time()
            finished = bool(total) and done >= total
            if not finished and now - self._progress_ts.get(session_id, 0.0) < 0.1:
                return
            self._progress_ts[session_id] = now
            self.sig_progress.emit(session_id, file_id, done, total)
        except Exception:
            pass

    def _show_recv(self, view, result, event):
        '''主线程：弹面板内接收确认层。一次只确认一个，并发的直接拒。'''
        try:
            if self._pending is not None:
                event.set()   # result['dir'] 仍为 None → 协议端按拒绝
                return
            key = self._add_record('down', view['names'], view['total'], view['alias'])
            rec = self._records.get(key)
            if rec is not None:
                rec['session_id'] = view['session_id']
            self._pending = (view['session_id'], key, result, event)
            self._save_dir = _default_save_dir(self.cfg)
            self.recv_from.setText(t('transfer.recv.summary',
                                     alias=view['alias'], count=len(view['names']),
                                     size=_fmt_size(view['total'])))
            self._fill_recv_files(view['names'])
            self.recv_dir.setText(self._recv_dir_text(self._save_dir))
            self.recv_dir.setToolTip(self._save_dir)
            # 按内容定高、居中于面板，向上滑入 180ms
            self.recv.adjustSize()
            g = self.window().frameGeometry()
            w, h = self.recv.width(), self.recv.height()
            x = g.x() + (g.width() - w) // 2
            y = g.y() + (g.height() - h) // 2
            self.recv.setGeometry(x, y + ui.sc(24), w, h)
            self.recv.show()
            self.recv.raise_()
            self.recv.activateWindow()
            ui.round_corners(self.recv)   # winId 已创建：Win11 DWM 圆角 / Win10 遮罩
            anim = QPropertyAnimation(self.recv, b'geometry', self)
            anim.setDuration(180)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.setStartValue(QRect(x, y + ui.sc(24), w, h))
            anim.setEndValue(QRect(x, y, w, h))
            anim.start(QPropertyAnimation.DeleteWhenStopped)
            self.notify.emit(t('transfer.recv.title'),
                             t('transfer.recv.request', alias=view['alias'],
                               count=len(view['names'])))
        except Exception:
            # 防僵尸 _pending：一次异常后不再把所有接收静默拒绝到重启
            self._pending = None
            try:
                self.recv.hide()
            except Exception:
                pass
            event.set()

    def _recv_dir_text(self, d):
        '''「保存到：<路径>」按弹窗可用宽度中段省略（尾部目录名始终可见，全路径在 tooltip）。'''
        avail = ui.sc(320) - ui.sc(36) - ui.sc(56)   # 弹宽 - 左右边距 - 「更改…」按钮
        return self.recv_dir.fontMetrics().elidedText(
            t('transfer.recv.save_to', path=d), Qt.ElideMiddle, avail)

    def _fill_recv_files(self, names):
        '''重建接收确认层的文件清单行（图标 + 文件名，最多 8 行）。'''
        while self.recv_files_lay.count():
            item = self.recv_files_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._recv_icons = []
        shown = names[:8]
        for nm in shown:
            row = QWidget()
            row.setObjectName('recvFileRow')
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(ui.sc(8))
            ic = QLabel()
            ic.setObjectName('transferIcon')
            ic.setFixedSize(ui.sc(20), ui.sc(20))
            ic.setPixmap(_file_icon(self.theme_key, 20))
            self._recv_icons.append(ic)
            lb = QLabel(nm)
            lb.setObjectName('recvFileName')
            lb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            hl.addWidget(ic)
            hl.addWidget(lb, 1)
            self.recv_files_lay.addWidget(row)
        if len(names) > len(shown):
            more = QLabel(t('transfer.recv.more', count=len(names)))
            more.setObjectName('recvFileMore')
            self.recv_files_lay.addWidget(more)

    def _close_recv(self):
        '''关掉确认层并唤醒 HTTP 线程（无论接受/拒绝/超时都只走这里）。'''
        pending = self._pending
        self._pending = None
        try:
            self.recv.hide()
        except Exception:
            pass
        if pending is not None:
            pending[3].set()

    def _recv_accept(self):
        try:
            if self._pending is None:
                return
            session_id, key, result, event = self._pending
            if session_id in self._expired:
                # 协议端已超时返回，这次接受无效：按拒绝处理（不置 busy）
                rec = self._records.get(key)
                if rec is not None:
                    rec['state'] = 'rejected'
                    self._update_record(rec)
                return   # finally 里照常 _close_recv()
            d = self._save_dir
            try:
                os.makedirs(d, exist_ok=True)
            except OSError:
                try:
                    d = os.path.join(os.path.expanduser('~'), 'Downloads', 'Zbox')
                    os.makedirs(d, exist_ok=True)
                except OSError:
                    d = None   # 目录不可用：result 保持 None，协议端按拒绝
            rec = self._records.get(key)
            if rec is not None:
                rec['state'] = 'busy' if d else 'rejected'
                self._update_record(rec)
            if d:
                result['dir'] = d
        except Exception:
            pass
        finally:
            self._close_recv()

    def _recv_reject(self):
        try:
            if self._pending is not None:
                rec = self._records.get(self._pending[1])
                if rec is not None:
                    rec['state'] = 'rejected'
                    self._update_record(rec)
        except Exception:
            pass
        finally:
            self._close_recv()

    def _recv_change_dir(self):
        try:
            d = QFileDialog.getExistingDirectory(self.recv, t('transfer.pick_dir'), self._save_dir)
            if d:
                self._save_dir = d
                self.cfg.set('transfer_dir', d)
                self.recv_dir.setText(self._recv_dir_text(d))
                self.recv_dir.setToolTip(d)
        except Exception:
            pass

    def _on_recv_timeout(self, session_id):
        '''确认超时（HTTP 线程已按拒绝返回）：关掉还挂着的确认层并记「已拒绝」。'''
        try:
            if self._pending is not None and self._pending[0] == session_id:
                rec = self._records.get(self._pending[1])
                if rec is not None:
                    rec['state'] = 'rejected'
                    self._update_record(rec)
                self._close_recv()   # event.set() 无害：HTTP 线程已超时返回
                self._expired.discard(session_id)
        except Exception:
            pass

    def _find_recv_record(self, session_id):
        for rec in self._records.values():
            if rec.get('session_id') == session_id:
                return rec
        return None

    def _on_progress(self, session_id, file_id, done, total):
        try:
            rec = self._find_recv_record(session_id)
            if rec is None or rec['state'] not in ('wait', 'busy'):
                return
            rec['files'][file_id] = done
            rec['done'] = sum(rec['files'].values())
            rec['state'] = 'busy'
            self._update_record(rec)
        except Exception:
            pass

    def _on_file_done(self, session_id, file_id, saved_path):
        try:
            rec = self._find_recv_record(session_id)
            if rec is None:
                return
            rec['saved'].append(saved_path)
            rec['row'].setToolTip('\n'.join(rec['saved']))
        except Exception:
            pass

    def _on_session_done(self, session_id):
        try:
            self._progress_ts.pop(session_id, None)
            rec = self._find_recv_record(session_id)
            if rec is None:
                return
            rec['state'] = 'done'
            rec['done'] = rec['total']
            self._update_record(rec)
            self.notify.emit(t('transfer.done_title'),
                             t('transfer.saved', name=rec['name']))
        except Exception:
            pass

    def _on_cancelled(self, session_id):
        try:
            self._progress_ts.pop(session_id, None)
            rec = self._find_recv_record(session_id)
            if rec is None:
                return
            rec['state'] = 'cancelled'
            self._update_record(rec)
        except Exception:
            pass

    # ---------------- 传输记录 ----------------

    def _add_record(self, direction, names, total, peer='', fp='', files=None):
        '''新建一条记录并插到记录区顶部，返回 key。direction: 'up' 发 / 'down' 收。
        peer 为对端别名：记录文字形如「Vacation.jpg · 发送至 Pixel 6」。
        fp/files 仅发送记录需要（失败重试用）：fp 是对端指纹，files 是 (本地路径, 相对路径) 清单。'''
        key = uuid.uuid4().hex
        # 文件夹传输（多个文件同属一个顶层目录）显示文件夹名而不是「N 个文件」
        if len(names) == 1:
            disp_name, tip = names[0], names[0]
        elif all('/' in n for n in names) and \
                len(set(n.split('/')[0] for n in names)) == 1:
            disp_name = tip = names[0].split('/')[0]
        else:
            disp_name = t('transfer.n_files', count=len(names))
            tip = '\n'.join(names)
        row = _ClickRow()
        row.setObjectName('transferRow')
        # 接收完成的记录才有交互（单击打开 / 右键菜单，见 _record_clicked/_record_menu）
        row.clicked.connect(lambda k=key: self._record_clicked(k))
        row.setContextMenuPolicy(Qt.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda pos, k=key: self._record_menu(k, pos))
        lay = QVBoxLayout(row)
        lay.setContentsMargins(ui.sc(8), ui.sc(5), ui.sc(8), ui.sc(6))
        lay.setSpacing(ui.sc(3))
        top = QHBoxLayout()
        top.setSpacing(ui.sc(6))
        icon = QLabel()
        icon.setObjectName('transferIcon')
        icon.setFixedSize(ui.sc(22), ui.sc(22))
        icon.setPixmap(_file_icon(getattr(self, 'theme_key', 'nocturne')))
        display = disp_name
        if peer:
            display += t('transfer.peer.to' if direction == 'up' else 'transfer.peer.from',
                         name=peer)
        name = _ElideLabel(display)
        name.setObjectName('transferName')
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        name.setToolTip(tip)      # 悬停显示完整名称
        state = QLabel()
        state.setObjectName('transferState')
        top.addWidget(icon)
        top.addWidget(name, 1)
        top.addWidget(state)
        cancel_btn = None
        retry_btn = None
        cancel_event = None
        if direction == 'up':
            # 发送方取消入口：仅「等待确认 / 传输中」可见（见 _update_record）
            cancel_event = threading.Event()
            cancel_btn = QToolButton()
            cancel_btn.setObjectName('cancelBtn')
            cancel_btn.setText(t('common.cancel'))
            cancel_btn.clicked.connect(
                lambda checked=False, k=key: self._cancel_send(k))
            top.addWidget(cancel_btn)
            # 失败重试：断点续传（文件粒度，已传完的文件跳过），仅 fail 态可见
            retry_btn = QToolButton()
            retry_btn.setObjectName('cancelBtn')
            retry_btn.setText(t('common.retry'))
            retry_btn.setToolTip(t('transfer.retry.tooltip'))
            retry_btn.clicked.connect(
                lambda checked=False, k=key: self._retry_send(k))
            retry_btn.hide()
            top.addWidget(retry_btn)
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(ui.sc(5))
        # 传输中三栏状态行（对照视频卡 dl_state_row）：已传输/总大小 · 剩余时间 · 速度，仅 busy/cancelling 可见
        stat_box = QWidget()
        stat_row = QHBoxLayout(stat_box)
        stat_row.setContentsMargins(0, 0, 0, 0)
        stat_row.setSpacing(ui.sc(6))
        size_lab = QLabel()
        eta_lab = QLabel()
        speed_lab = QLabel()
        for lab in (size_lab, eta_lab, speed_lab):
            lab.setObjectName('transferState')
            lab.setProperty('state', 'busy')
        stat_row.addWidget(size_lab)
        stat_row.addStretch(1)
        stat_row.addWidget(eta_lab)
        stat_row.addStretch(1)
        stat_row.addWidget(speed_lab)
        stat_box.hide()
        lay.addLayout(top)
        lay.addWidget(bar)
        lay.addWidget(stat_box)
        self.rec_empty.hide()
        self.rec_lay.insertWidget(0, row)
        # 新记录滑入：高度从 0 展开（不用透明度特效，避免破坏文字 ClearType）
        try:
            h = row.sizeHint().height()
            if h > 0:
                row.setMaximumHeight(0)
                anim = QPropertyAnimation(row, b'maximumHeight', self)
                anim.setDuration(180)
                anim.setEasingCurve(QEasingCurve.OutCubic)
                anim.setStartValue(0)
                anim.setEndValue(h)
                anim.finished.connect(lambda: row.setMaximumHeight(16777215))
                anim.start(QPropertyAnimation.DeleteWhenStopped)
        except Exception:
            row.setMaximumHeight(16777215)
        full_display = disp_name + (
            t('transfer.peer.to' if direction == 'up' else 'transfer.peer.from', name=peer)
            if peer else '')
        rec = {'key': key, 'direction': direction, 'name': full_display, 'total': total,
               'done': 0, 'files': {}, 'saved': [], 'state': 'wait', 'err': '',
               'session_id': None, 'row': row, 'bar': bar, 'state_lab': state,
               'icon_lab': icon, 'stat_box': stat_box, 'size_lab': size_lab,
               'eta_lab': eta_lab, 'speed_lab': speed_lab,
               'cancel_btn': cancel_btn, 'cancel_event': cancel_event,
               'retry_btn': retry_btn, 'fp': fp, 'files': list(files or []),
               'completed_idx': []}
        self._records[key] = rec
        self._rec_keys.insert(0, key)
        self._update_record(rec)
        while len(self._rec_keys) > MAX_RECORDS:
            old = self._rec_keys.pop()
            old_rec = self._records.pop(old, None)
            if old_rec is not None:
                self.rec_lay.removeWidget(old_rec['row'])
                old_rec['row'].deleteLater()
        return key

    def _record_clicked(self, key):
        '''接收成功的记录：单击打开文件（一次收了多个文件则定位到所在文件夹）。'''
        try:
            rec = self._records.get(key)
            if not rec or rec['direction'] != 'down' or rec['state'] != 'done':
                return
            paths = [p for p in rec['saved'] if os.path.exists(p)]
            if not paths:
                return
            if len(paths) == 1:
                os.startfile(paths[0])
            else:
                _reveal_in_explorer(paths[0])
        except Exception:
            pass

    def _record_menu(self, key, pos):
        '''接收成功的记录右键：打开文件位置（选中该文件）/ 删除记录（不删除文件）。'''
        try:
            rec = self._records.get(key)
            if not rec or rec['direction'] != 'down' or rec['state'] != 'done':
                return
            paths = [p for p in rec['saved'] if os.path.exists(p)]
            menu = QMenu(self)
            act_reveal = menu.addAction(t('transfer.record.reveal')) if paths else None
            act_del = menu.addAction(t('transfer.record.delete'))
            act = menu.exec(rec['row'].mapToGlobal(pos))
            if act is None:
                return
            if act_reveal is not None and act is act_reveal:
                _reveal_in_explorer(paths[0])
            elif act is act_del:
                self._remove_record(key)
        except Exception:
            pass

    def _remove_record(self, key):
        rec = self._records.pop(key, None)
        if rec is None:
            return
        if key in self._rec_keys:
            self._rec_keys.remove(key)
        self.rec_lay.removeWidget(rec['row'])
        rec['row'].deleteLater()
        if not self._records:
            self.rec_empty.show()

    def _animate_bar(self, rec, target):
        '''进度条平滑过渡（150ms 缓出），消除一跳一跳的阶梯感。'''
        bar = rec['bar']
        try:
            if bar.value() == target:
                return
            anim = QPropertyAnimation(bar, b'value', self)
            anim.setDuration(150)
            anim.setStartValue(bar.value())
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start(QPropertyAnimation.DeleteWhenStopped)
        except Exception:
            bar.setValue(target)

    def _update_record(self, rec):
        '''按 rec 的状态刷新状态文字与进度条（主线程）。'''
        state = rec['state']
        total = rec['total'] or 0
        if state == 'wait':
            text = t('transfer.state.waiting_peer') if rec['direction'] == 'up' \
                else t('transfer.state.waiting_you')
        elif state == 'busy':
            pct = int(rec['done'] * 100 / total) if total else 0
            text = t('transfer.state.transferring', percent=pct)
            now = time.time()
            tick = rec.get('_tick')
            if tick is None:
                rec['_tick'] = (now, rec['done'])      # 首个进度帧只建立基准
            else:
                last_ts, last_done = tick
                if rec['done'] > last_done and now - last_ts > 0.2:
                    speed = (rec['done'] - last_done) / (now - last_ts)
                    prev = rec.get('_speed') or 0.0
                    rec['_speed'] = speed if not prev else prev * 0.5 + speed * 0.5
                    rec['_tick'] = (now, rec['done'])
            # 三栏数字 2s 节流刷新（进度条不在此列，保持平滑）；进入 busy 立即刷一帧
            if now - rec.get('_stat_ts', 0.0) >= 2.0:
                rec['_stat_ts'] = now
                if total:
                    rec['size_lab'].setText('%s / %s' % (_fmt_size(rec['done']),
                                                         _fmt_size(total)))
                if rec.get('_speed'):
                    rec['speed_lab'].setText(_fmt_speed(rec['_speed']))
                    if total and rec['done'] < total:
                        rec['eta_lab'].setText(
                            t('transfer.state.eta',
                              time=_fmt_eta((total - rec['done']) / rec['_speed'])))
        elif state == 'done':
            text = t('transfer.state.done')
        elif state == 'rejected':
            text = t('transfer.state.rejected')
        elif state == 'cancelled':
            text = t('transfer.state.cancelled')
        elif state == 'cancelling':
            text = t('transfer.state.cancelling')
        else:
            friendly = rec.get('err_friendly') or _friendly_err(rec.get('err'))
            text = t('transfer.state.failed_detail', reason=friendly) \
                if friendly else t('transfer.state.failed')
            rec['state_lab'].setToolTip(
                rec.get('err') or rec.get('err_friendly') or '')   # 原始错误留悬停排查
        rec['state_lab'].setText(text)
        # 接收完成的记录可单击打开 / 右键管理，给个手型提示（其余状态无交互）
        rec['row'].setCursor(Qt.PointingHandCursor
                             if rec['direction'] == 'down' and state == 'done'
                             else Qt.ArrowCursor)
        if rec['state_lab'].property('state') != state:
            rec['state_lab'].setProperty('state', state)
            rec['state_lab'].style().unpolish(rec['state_lab'])
            rec['state_lab'].style().polish(rec['state_lab'])
        rec['row'].set_glow('run' if state == 'busy' else '')
        rec['bar'].setVisible(state in ('busy', 'cancelling'))
        rec['stat_box'].setVisible(state in ('busy', 'cancelling'))
        target = 1000 if state == 'done' else (int(rec['done'] * 1000 / total) if total else 0)
        self._animate_bar(rec, target)
        btn = rec.get('cancel_btn')
        if btn is not None:
            btn.setVisible(state in ('wait', 'busy'))
        rbtn = rec.get('retry_btn')
        if rbtn is not None:
            rbtn.setVisible(state == 'fail')
