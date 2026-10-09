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
import threading
from urllib.request import Request, urlopen
import time

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import (QAction, QActionGroup, QDesktopServices,
                             QPixmap, QPainter, QPainterPath)
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QToolButton, QPushButton,
                               QVBoxLayout, QHBoxLayout, QLineEdit, QProgressBar,
                               QFileDialog, QMenu, QDialog, QGraphicsBlurEffect,
                               QScrollArea)

import app as ui            # 仅运行期用 ui.sc()；import 期无依赖（app 也 import 本模块）
import video_dl


def _fmt_mb(n):
    return '%.1f MB' % (n / 1048576.0)


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


MAX_RECORDS = 20   # 下载记录条数上限，超出丢弃最旧

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


class _RecRow(QFrame):
    """下载记录行：单击打开文件。"""
    clicked = Signal()

    def mouseReleaseEvent(self, e):
        try:
            if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
                self.clicked.emit()
        except Exception:
            pass
        super(_RecRow, self).mouseReleaseEvent(e)


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
    """组件卸载确认弹窗：样式复用设置窗。"""

    def __init__(self, parent=None):
        super(_ConfirmDialog, self).__init__(parent)
        self.setObjectName('settingsDlg')
        self.setWindowTitle('卸载组件')
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
        title = QLabel('卸载组件')
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

        lb = QLabel('将删除视频解析所需的组件文件与已导入的 cookie，本功能随之关闭。'
                    '下次启用时会自动重新下载，已下载的视频不受影响。')
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
        ok = QPushButton('确认卸载')
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
        imp = QPushButton('导入 cookies.txt')
        imp.setObjectName('setSave')
        imp.setCursor(Qt.PointingHandCursor)
        imp.setDefault(True)
        imp.clicked.connect(self._import)
        btn_row.addWidget(imp)
        self.rm_btn = QPushButton('移除')
        self.rm_btn.setObjectName('setBtn')
        self.rm_btn.setCursor(Qt.PointingHandCursor)
        self.rm_btn.setToolTip('删除已导入的 cookies.txt')
        self.rm_btn.clicked.connect(self._remove)
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
                self.rm_btn.show()
            else:
                self.status_lab.setText('当前状态：未导入。点下面按钮选择刚导出的 cookies.txt。')
                self.rm_btn.hide()
        except Exception:
            pass

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
    就绪后可解析/下载视频；底栏常驻 yt-dlp / ffmpeg 版本与更新、卸载入口。"""

    enabled_changed = Signal(bool)                  # 开关状态变化（设置窗同步勾选用）
    sig_prep = Signal(str)                          # 组件准备进度文案
    sig_prep_done = Signal(bool, str, int)          # 组件准备结束 ok, err, 批次序号
    sig_parse_done = Signal(bool, object)           # 网址解析结束 ok, info(dict) 或 err(str)
    sig_thumb = Signal(bytes)                       # 封面图下载完成（空字节 = 失败）
    sig_dl_progress = Signal(object, str)           # 下载进度 percent(float|None), 详情
    sig_dl_done = Signal(bool, str)                 # 下载结束 ok, 文件名或错误
    sig_ver = Signal(str, object, str, object)      # 版本查询：yt本地, yt最新, ff本地, ff最新(None=失败)

    def __init__(self, cfg, parent=None, auto_start=True):
        super(VideoWidget, self).__init__(parent)
        self.cfg = cfg
        self.theme_key = 'nocturne'
        self._on = False             # 组件就绪、功能开启
        self._dl = None              # 进行中的 video_dl.Download
        self._parsed = None          # 已解析的 {'url','title','duration','heights','height'}
        self._parsing = False
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

        # ---- 网址行：输入框 + 解析按钮 ----
        url_row = QHBoxLayout()
        url_row.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        url_row.setSpacing(ui.sc(6))
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName('urlEdit')
        self.url_edit.setPlaceholderText('粘贴视频网址（YouTube / Bilibili 等）')
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.textChanged.connect(self._url_changed)
        self.url_edit.returnPressed.connect(self._start_parse)
        url_row.addWidget(self.url_edit, 1)
        self.parse_btn = QToolButton()
        self.parse_btn.setObjectName('parseBtn')
        self.parse_btn.setText('解 析')
        self.parse_btn.setCursor(Qt.PointingHandCursor)
        self.parse_btn.clicked.connect(self._start_parse)
        url_row.addWidget(self.parse_btn)
        pl.addLayout(url_row)

        # ---- 视频卡：解析成功才显示 ----
        self.card = QFrame()
        self.card.setObjectName('videoCard')
        cl = QHBoxLayout(self.card)
        cl.setContentsMargins(ui.sc(10), ui.sc(8), ui.sc(10), ui.sc(8))
        cl.setSpacing(ui.sc(8))
        self.thumb_lab = QLabel()
        self.thumb_lab.setObjectName('videoThumb')
        self.thumb_lab.setFixedSize(ui.sc(64), ui.sc(64))
        self.thumb_lab.hide()                # 封面取不到时不占位
        cl.addWidget(self.thumb_lab, 0, Qt.AlignVCenter)
        info_col = QVBoxLayout()
        info_col.setSpacing(ui.sc(5))
        self.title_lab = QLabel()
        self.title_lab.setObjectName('videoTitle')
        info_col.addWidget(self.title_lab)
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(ui.sc(6))
        self.dur_lab = QLabel()
        self.dur_lab.setObjectName('videoMeta')
        meta_row.addWidget(self.dur_lab)
        meta_row.addStretch(1)
        q_lab = QLabel('清晰度')
        q_lab.setObjectName('videoMeta')
        meta_row.addWidget(q_lab)
        self.quality_btn = QToolButton()
        self.quality_btn.setObjectName('qualityBtn')
        self.quality_btn.setCursor(Qt.PointingHandCursor)
        self.quality_btn.setPopupMode(QToolButton.InstantPopup)
        self.quality_menu = QMenu(self.quality_btn)
        self.quality_btn.setMenu(self.quality_menu)
        meta_row.addWidget(self.quality_btn)
        info_col.addLayout(meta_row)
        cl.addLayout(info_col, 1)
        self.card.hide()
        pl.addWidget(self.card)

        # ---- 下载按钮 ----
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        btn_row.addStretch(1)
        self.dl_btn = QPushButton('下载视频')
        self.dl_btn.setObjectName('sendBtn')
        self.dl_btn.setCursor(Qt.PointingHandCursor)
        self.dl_btn.setEnabled(False)          # 解析成功才可用
        self.dl_btn.clicked.connect(self._start_download)
        btn_row.addWidget(self.dl_btn)
        btn_row.addStretch(1)
        pl.addLayout(btn_row)

        # ---- 进度与状态 ----
        prog_row = QHBoxLayout()
        prog_row.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
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
        prog_row.addWidget(prog_card)
        pl.addLayout(prog_row)
        state_row = QHBoxLayout()
        state_row.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        state_row.setSpacing(ui.sc(6))
        state_row.addStretch(1)
        self.state_lab = QLabel('粘贴网址后点「解析」')
        self.state_lab.setObjectName('videoState')
        self.state_lab.setAlignment(Qt.AlignCenter)
        self.state_lab.setWordWrap(True)
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

        # ---- 下载记录（本次会话，新的在前，单击打开文件）----
        self.rec_title = QLabel('下载记录')
        self.rec_title.setObjectName('videoLabel')
        self.rec_title.hide()
        pl.addWidget(self.rec_title)
        self.rec_scroll = QScrollArea()
        self.rec_scroll.setObjectName('videoScroll')
        self.rec_scroll.setWidgetResizable(True)
        self.rec_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rec_scroll.hide()
        self.rec_box = QWidget()
        self.rec_box.setObjectName('videoBox')
        self.rec_lay = QVBoxLayout(self.rec_box)
        self.rec_lay.setContentsMargins(ui.sc(10), 0, ui.sc(10), 0)
        self.rec_lay.setSpacing(ui.sc(2))
        self.rec_lay.addStretch(1)
        self.rec_scroll.setWidget(self.rec_box)
        pl.addWidget(self.rec_scroll, 1)   # 吃掉剩余空间：内容少时占位，多时滚动
        pl.addStretch(1)

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
        self.sig_parse_done.connect(self._on_parse_done)
        self.sig_thumb.connect(self._on_thumb)
        self.sig_dl_progress.connect(self._on_dl_progress)
        self.sig_dl_done.connect(self._on_dl_done)
        self.sig_ver.connect(self._on_ver)

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
        """主题切换：颜色全走 QSS，本页无自绘位图，记 key 即可。"""
        self.theme_key = key

    def service_enabled(self):
        return self._on

    def shutdown(self):
        """程序退出 / 功能关闭：终止进行中的下载子进程。"""
        try:
            if self._dl is not None:
                self._dl.terminate()
        except Exception:
            pass

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
            if self._updating or self._dl is not None:
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
        self.sig_dl_progress.emit(None, '')   # 借信号回主线程恢复按钮（详情空串不改状态）

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
        self.sig_dl_done.emit(ok, '组件已更新到最新' if ok else '组件更新失败，请稍后重试')

    def _uninstall_clicked(self):
        try:
            if self._dl is not None or self._parsing or self._updating:
                self._set_state('fail', '当前有任务进行中，无法卸载')
                return
            if _ConfirmDialog(self).exec() != QDialog.Accepted:
                return
            video_dl.uninstall_tools()
            self.set_enabled(False)   # 关功能回门禁层，下次启用重新下载组件
        except Exception:
            pass

    # ---------------- 解析 ----------------

    def _url_changed(self):
        """网址改动后已解析结果作废：收起视频卡，下载按钮重新锁定。"""
        try:
            if self._parsed and self.url_edit.text().strip() != self._parsed['url']:
                self._parsed = None
                self.card.hide()
                self.thumb_lab.hide()
                self.dl_btn.setEnabled(False)
                if not self._parsing and self._dl is None:
                    self._set_state('', '网址已改动，请重新解析')
        except Exception:
            pass

    def _start_parse(self):
        try:
            if not self._on or self._parsing or self._dl is not None or self._updating:
                return
            url = self.url_edit.text().strip()
            if not url:
                self._set_state('fail', '请先粘贴视频网址')
                return
            if self._parsed and self._parsed['url'] == url:
                return   # 同一网址已解析过，直接选清晰度下载即可
            self._parsing = True
            self._parsed = None
            self.card.hide()
            self.dl_btn.setEnabled(False)
            self._set_parse_busy(True)
            self._set_state('busy', '正在解析…')
            threading.Thread(target=self._parse_work, args=(url,), daemon=True).start()
        except Exception:
            pass

    def _parse_work(self, url):
        try:
            info = video_dl.parse_video(url)
            info['url'] = url
            self.sig_parse_done.emit(True, info)
        except Exception as e:
            self.sig_parse_done.emit(False, str(e))

    def _on_parse_done(self, ok, info):
        try:
            self._parsing = False
            self._set_parse_busy(False)
            if not ok:
                if video_dl.is_cookie_error(info):
                    self._set_state('fail', '解析失败：该站点要求浏览器 cookie（无需登录账号）')
                    self.cookie_link.show()
                else:
                    self._set_state('fail', '解析失败：%s' % info)
                return
            self._parsed = info
            self.title_lab.setToolTip(info['title'] or '')
            self._elide_title()
            dur = _fmt_dur(info['duration'])
            self.dur_lab.setText(('时长 ' + dur) if dur else '')
            self._rebuild_quality_menu(info['heights'])
            self.card.show()
            self.dl_btn.setEnabled(True)
            self._set_state('', '解析成功，选择清晰度后下载')
            self.thumb_lab.hide()
            thumb_url = info.get('thumbnail') or ''
            if thumb_url:
                threading.Thread(target=self._thumb_work,
                                 args=(thumb_url,), daemon=True).start()
        except Exception:
            pass

    def _elide_title(self):
        try:
            title = (self._parsed or {}).get('title') or '（无标题）'
            w = ui.sc(196) if self.thumb_lab.isVisible() else ui.sc(268)
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

    def _set_parse_busy(self, busy):
        self.url_edit.setEnabled(not busy)
        self.parse_btn.setEnabled(not busy)
        self.parse_btn.setText('解析中…' if busy else '解 析')

    def _rebuild_quality_menu(self, heights):
        """按源视频实际提供的分辨率降序建菜单；首选最高不超过用户偏好档
        （cfg['video_quality']，手动选择时更新）的档位。"""
        self.quality_menu.clear()
        group = QActionGroup(self)
        group.setExclusive(True)
        options = [('%dP' % h, h) for h in heights] or [('自动', None)]
        m = re.match(r'(\d+)', self.cfg.data.get('video_quality') or '1080P')
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
        self.quality_btn.setText(('%dP' % default_h) if default_h else '自动')

    def _set_quality(self, height, name):
        try:
            if self._parsed:
                self._parsed['height'] = height
            self.quality_btn.setText(name)
            if height:   # 记住偏好，下次解析同档优先（「自动」不记）
                self.cfg.set('video_quality', name)
        except Exception:
            pass

    # ---------------- 下载 ----------------

    def _start_download(self):
        try:
            if not self._on or not self._parsed or self._dl is not None or self._updating:
                return
            try:
                os.makedirs(self.save_dir, exist_ok=True)
            except OSError:
                self._set_state('fail', '保存目录不可用，请重新选择')
                return
            self._dl = video_dl.Download(self._parsed['url'],
                                         self._parsed.get('height'), self.save_dir)
            self._set_busy(True)
            self.prog.setValue(0)
            self._set_state('busy', '正在下载…')
            dl = self._dl
            threading.Thread(
                target=dl.start,
                args=(lambda p, d: self.sig_dl_progress.emit(p, d),
                      lambda ok, msg: self.sig_dl_done.emit(ok, msg)),
                daemon=True).start()
        except Exception:
            pass

    def _on_dl_progress(self, pct, detail):
        try:
            if pct is None:   # 版本检查后恢复按钮（_check_work 借道）
                self.update_btn.setEnabled(True)
                return
            if self._dl is None:
                return
            self.prog.setValue(int(pct))
            self._set_state('busy', detail)
        except Exception:
            pass

    def _on_dl_done(self, ok, msg):
        try:
            self._dl = None
            self._set_busy(False)
            if ok:
                self.prog.setValue(100)
                if msg and os.path.isfile(msg):
                    self._set_state('done', '已完成：%s' % os.path.basename(msg))
                    self._add_record(os.path.basename(msg), msg)
                else:
                    self._set_state('done', '已完成' if not msg else msg)
            else:
                if video_dl.is_cookie_error(msg):
                    self._set_state('fail', '下载失败：该站点要求浏览器 cookie（无需登录账号）')
                    self.cookie_link.show()
                else:
                    self._set_state('fail', '下载失败：%s' % msg)
        except Exception:
            pass

    def _set_busy(self, busy):
        for w in (self.url_edit, self.parse_btn, self.dl_btn,
                  self.quality_btn, self.update_btn, self.uninst_btn):
            w.setEnabled(not busy)
        if busy:
            self.dl_btn.setText('下载中…')
        else:
            self.dl_btn.setText('下载视频')
            self.dl_btn.setEnabled(self._parsed is not None)

    def _set_state(self, state, text):
        if hasattr(self, 'cookie_link'):
            self.cookie_link.hide()
        self.state_lab.setProperty('state', state)
        self.state_lab.setText(text)
        self.state_lab.style().unpolish(self.state_lab)
        self.state_lab.style().polish(self.state_lab)

    # ---------------- 下载记录 ----------------

    def _add_record(self, name, path):
        try:
            row = _RecRow()
            row.setObjectName('videoRecRow')
            row.setCursor(Qt.PointingHandCursor)
            row.setToolTip('%s\n点击打开文件' % path)
            h = QHBoxLayout(row)
            h.setContentsMargins(ui.sc(6), ui.sc(3), ui.sc(6), ui.sc(3))
            h.setSpacing(ui.sc(6))
            lab = QLabel(row.fontMetrics().elidedText(name, Qt.ElideMiddle, ui.sc(240)))
            lab.setObjectName('videoRecName')
            h.addWidget(lab, 1)
            hint = QLabel('›')
            hint.setObjectName('videoMeta')
            h.addWidget(hint)
            row.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
            self.rec_lay.insertWidget(0, row)   # 顶部插入 = 新的在前
            while self.rec_lay.count() - 1 > MAX_RECORDS:   # count 含末尾 stretch
                item = self.rec_lay.itemAt(self.rec_lay.count() - 2)
                w = item.widget()
                self.rec_lay.removeItem(item)
                if w is not None:
                    w.deleteLater()
            self.rec_title.show()
            self.rec_scroll.show()
        except Exception:
            pass

    def _clear_records(self):
        try:
            for r in self.rec_box.findChildren(_RecRow):
                r.deleteLater()
            self.rec_title.hide()
            self.rec_scroll.hide()
        except Exception:
            pass

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