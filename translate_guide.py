# -*- coding: utf-8 -*-
"""首次使用截图翻译的两步准备引导窗：1) 下载文字识别组件（带进度）2) 登录豆包。

只在组件缺失时由 ShotOverlay 弹出（首次使用的判据）；下载走 ocr_runtime 的
双源镜像（国内 CDN 优先、GitHub 镜像兜底），失败可重试；登录复用
doubao_web.DoubaoLoginDialog（共享持久 profile）。完成后关闭窗口，
调用方检查 ocr_runtime.ocr_ready() 决定是否继续翻译。
"""

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QVBoxLayout)

import ocr_runtime
from i18n import t


class TranslateGuideDialog(QDialog):
    sig_progress = Signal(int, int)    # 已下载字节, 总字节（0 = 未知）
    sig_dl_done = Signal(str)          # '' = 成功，否则错误信息

    def __init__(self, parent=None):
        super(TranslateGuideDialog, self).__init__(parent)
        self.setWindowTitle(t('shot.guide.title'))
        # 复用设置窗的对话框/标签/按钮样式（两套主题都已定义），进度条样式见 themes.py
        self.setObjectName('settingsDlg')
        self.setModal(True)
        self._downloading = False
        self._logged_in = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)

        desc = QLabel(t('shot.guide.desc'))
        desc.setObjectName('setLabel')
        desc.setWordWrap(True)
        lay.addWidget(desc)

        # 步骤 1：文字识别组件
        s1 = QHBoxLayout()
        s1.setSpacing(10)
        self.step1_label = QLabel(t('shot.guide.step1'))
        self.step1_label.setObjectName('setLabel')
        self.step1_label.setWordWrap(True)
        s1.addWidget(self.step1_label, 1)
        self.dl_btn = QPushButton(t('shot.guide.download'))
        self.dl_btn.setObjectName('setBtn')
        self.dl_btn.clicked.connect(self._start_download)
        s1.addWidget(self.dl_btn)
        lay.addLayout(s1)
        self.dl_bar = QProgressBar()
        self.dl_bar.setRange(0, 100)
        self.dl_bar.setValue(0)
        self.dl_bar.hide()
        lay.addWidget(self.dl_bar)

        # 步骤 2：登录豆包
        s2 = QHBoxLayout()
        s2.setSpacing(10)
        self.step2_label = QLabel(t('shot.guide.step2'))
        self.step2_label.setObjectName('setLabel')
        self.step2_label.setWordWrap(True)
        s2.addWidget(self.step2_label, 1)
        self.login_btn = QPushButton(t('shot.guide.login'))
        self.login_btn.setObjectName('setBtn')
        self.login_btn.clicked.connect(self._open_login)
        import doubao_web
        if not doubao_web.supported():   # 系统无 Edge：步骤 2 不可用
            self.login_btn.setEnabled(False)
            self.login_btn.setToolTip(t('shot.translate.no_edge'))
        s2.addWidget(self.login_btn)
        lay.addLayout(s2)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_btn = QPushButton(t('common.close'))
        close_btn.setObjectName('setBtn')
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        lay.addLayout(bottom)

        self.sig_progress.connect(self._on_progress)
        self.sig_dl_done.connect(self._on_dl_done)
        self._refresh()

    def _refresh(self):
        if ocr_runtime.ocr_ready():
            self.step1_label.setText('%s  %s' % (t('shot.guide.step1'),
                                                 t('shot.guide.ready')))
            self.dl_btn.hide()
            self.dl_bar.hide()
        if self._logged_in:
            self.step2_label.setText('%s  %s' % (t('shot.guide.step2'),
                                                 t('shot.guide.logged_in')))
            self.login_btn.hide()

    # ---------- 组件下载 ----------

    def _start_download(self):
        if self._downloading:
            return
        self._downloading = True
        self.dl_btn.setEnabled(False)
        self.dl_bar.setValue(0)
        self.dl_bar.show()
        threading.Thread(target=self._dl_work, daemon=True).start()

    def _dl_work(self):
        try:
            ocr_runtime.download_components(
                progress_cb=lambda done, total: self.sig_progress.emit(done, total))
            self.sig_dl_done.emit('')
        except Exception as e:
            self.sig_dl_done.emit(str(e))

    def _on_progress(self, done, total):
        if total > 0:
            self.dl_bar.setRange(0, 100)
            self.dl_bar.setValue(min(100, int(done * 100 / total)))
        else:
            self.dl_bar.setRange(0, 0)   # 总长未知：滚动忙碌态

    def _on_dl_done(self, error):
        self._downloading = False
        self.dl_bar.setRange(0, 100)
        if error:
            self.dl_btn.setText(t('shot.guide.dl_failed'))
            self.dl_btn.setEnabled(True)
        else:
            self.dl_bar.setValue(100)
            self._refresh()

    # ---------- 豆包登录 ----------

    def _open_login(self):
        import doubao_web
        # 有头 Edge 登录窗（非模态 Qt 对话框）；登录成功回调标 ✓
        self._login_win = doubao_web.open_login_window(
            on_logged_in=self._on_logged_in)

    def _on_logged_in(self):
        self._logged_in = True
        self._login_win = None
        self._refresh()

class DoubaoLoginGuideDialog(QDialog):
    """豆包未登录/登录过期：截屏已退出，引导用户登录网页版豆包。
    [打开登录窗口] 开有头 Edge（doubao_web.open_login_window）；
    登录完成 → 提示翻译功能可用；用户关掉登录窗 → 按钮复位可重开。"""

    def __init__(self, parent=None):
        super(DoubaoLoginGuideDialog, self).__init__(parent)
        self.setWindowTitle(t('shot.login.guide.title'))
        from app import make_icon   # 惰性 import 防循环；标题栏用 zbox logo
        self.setWindowIcon(make_icon())
        # 强制置顶：要压在钉图窗（也是 StaysOnTop）之上，靠 show 后 raise
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setObjectName('settingsDlg')
        self._login_win = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)
        self.state_label = QLabel(t('shot.login.guide.desc'))
        self.state_label.setObjectName('loginGuideText')   # 高亮白字，更显眼
        self.state_label.setWordWrap(True)
        lay.addWidget(self.state_label)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.open_btn = QPushButton(t('shot.login.guide.open'))
        self.open_btn.setObjectName('setBtn')
        self.open_btn.clicked.connect(self._open_login)
        bottom.addWidget(self.open_btn)
        lay.addLayout(bottom)
        self.resize(360, 0)

    def _open_login(self):
        text = self.open_btn.text()
        if text == t('common.close'):
            self.accept()
            return
        self.open_btn.setEnabled(False)
        self.state_label.setText(t('shot.login.guide.waiting'))
        import doubao_web
        self._login_win = doubao_web.open_login_window(
            on_logged_in=self._on_logged_in,
            on_aborted=self._on_aborted)

    def _on_logged_in(self):
        self._login_win = None
        self.state_label.setText(t('shot.login.guide.done'))
        self.open_btn.setText(t('common.close'))
        self.open_btn.setEnabled(True)

    def _on_aborted(self):
        self._login_win = None
        self.state_label.setText(t('shot.login.guide.desc'))
        self.open_btn.setText(t('shot.login.guide.open'))
        self.open_btn.setEnabled(True)


_current_login_guide = None


def show_login_guide(parent=None):
    """弹出豆包登录引导窗并保持模块级引用：调用方（截图遮罩）随即销毁，
    局部变量持有会被 Python GC 收掉——窗口一闪而过（实测）。
    WA_DeleteOnClose + destroyed 清引用，窗关即释放。"""
    global _current_login_guide
    dlg = DoubaoLoginGuideDialog(parent)
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    _current_login_guide = dlg
    dlg.destroyed.connect(lambda *_: _clear_login_guide())
    dlg.show()
    dlg.raise_()          # 同为 StaysOnTop 的钉图窗之上靠后 raise 抢 z 序
    dlg.activateWindow()
    return dlg


def _clear_login_guide():
    global _current_login_guide
    _current_login_guide = None
