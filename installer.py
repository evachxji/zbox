# -*- coding: utf-8 -*-
"""exe 安装包：深色主题安装向导（路径/范围/空间/进度）+ 自安装 + 卸载（含应用列表注册）。
仅冻结为 exe 时生效；源码运行（pythonw main.pyw）不受影响，仍走 install.py。
样式复用 themes.py NOCTURNE 主题与 #settingsPanel/#setBtn/#setSave 规范，仅补充少量同配色控件样式。
"""
import os
import shutil
import subprocess
import sys
import time

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QStyle,
                             QLabel, QFrame, QToolButton, QCheckBox, QRadioButton,
                             QPushButton, QLineEdit, QProgressBar, QFileDialog,
                             QStackedLayout, QMessageBox)

import sysutil

APP_EXE = 'ZviberPanel.exe'
APP_TITLE = 'Zviber 桌面日历'

# 安装向导补充样式：沿用 NOCTURNE 深色配色（#e8a33d 强调色），%CN% 运行时替换
_EXTRA_QSS = """
QLineEdit#pathEdit {
    background: rgba(255,255,255,24); border: 1.5px solid rgba(255,255,255,40); border-radius: 8px;
    color: #f0ede6; font: 12px "%CN%"; padding: 6px 10px; selection-background-color: rgba(232,163,61,90);
}
QLineEdit#pathEdit:focus { border-color: rgba(232,163,61,160); }
QLabel#setLabel[err="true"] { color: #e05252; }
QProgressBar {
    background: rgba(255,255,255,18); border: none; border-radius: 5px;
    min-height: 10px; max-height: 10px; color: transparent;
}
QProgressBar::chunk { background: #e8a33d; border-radius: 5px; }
"""


def install_dir(all_users=False):
    """默认安装目录：当前用户 → %LOCALAPPDATA%\\Programs；此计算机 → Program Files。"""
    if all_users:
        base = os.environ.get('ProgramFiles') or r'C:\Program Files'
    else:
        base = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'Programs')
    return os.path.join(base, 'ZviberPanel')


def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_elevated(args):
    """以管理员身份重启自身（触发 UAC）；用户拒绝时返回 False。args 需自行加引号。"""
    import ctypes
    return ctypes.windll.shell32.ShellExecuteW(None, 'runas', sys.executable,
                                               ' '.join(args), None, 1) > 32


def _exe_dir():
    return os.path.normcase(os.path.dirname(os.path.abspath(sys.executable)))


def is_installed():
    """当前 frozen exe 是否正从某个安装位置运行（按应用列表注册信息识别，支持自定义路径）。"""
    if not getattr(sys, 'frozen', False):
        return False
    for au in (False, True):
        loc = sysutil.uninstall_reg_get('InstallLocation', au)
        if loc and os.path.normcase(loc) == _exe_dir():
            return True
    return _exe_dir() in (os.path.normcase(install_dir(False)), os.path.normcase(install_dir(True)))


def is_all_users_install():
    loc = sysutil.uninstall_reg_get('InstallLocation', True)
    return bool(loc) and os.path.normcase(loc) == _exe_dir()


def registered_install_dir():
    """已注册的安装目录（HKCU 优先，HKLM 兜底）；没有安装记录返回 None。"""
    for all_users in (False, True):
        loc = sysutil.uninstall_reg_get('InstallLocation', all_users)
        if loc:
            return loc
    return None


def sync_context_menu():
    """右键菜单只属于 exe 安装：没有任何安装记录时清掉残留。
    残留来源：旧版 install.py 的源码安装、安装向导取消、卸载未清干净。"""
    if registered_install_dir() is None:
        sysutil.context_menu_remove()


def request_quit():
    """通知运行中的实例退出（卸载前调用，避免文件占用）。"""
    from PyQt5.QtNetwork import QLocalSocket
    s = QLocalSocket()
    s.connectToServer(sysutil.IPC_KEY)
    if s.waitForConnected(500):
        s.write(b'quit')
        s.flush()
        s.waitForBytesWritten(500)


def _gen_icon(path):
    import app as ui
    return ui.make_icon().pixmap(64, 64).save(path, 'ICO')


def _copy_with_progress(src, dst, cb):
    total = os.path.getsize(src)
    done = 0
    with open(src, 'rb') as f, open(dst, 'wb') as out:
        while True:
            buf = f.read(1 << 19)
            if not buf:
                break
            out.write(buf)
            done += len(buf)
            cb(done * 100 // total)
    shutil.copystat(src, dst)


def install(path_dir, all_users=False, autostart=True, shortcut=True, progress=None):
    """把当前 exe 安装到指定目录并注册系统集成，返回安装后的 exe 路径。
    progress(pct, text) 回报进度。"""
    def report(pct, text):
        if progress:
            progress(pct, text)
    if not os.path.isdir(path_dir):
        os.makedirs(path_dir)
    dst = os.path.join(path_dir, APP_EXE)
    if os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(dst):
        _copy_with_progress(sys.executable, dst, lambda p: report(p * 7 // 10, '正在复制程序文件…'))
    report(72, '正在生成图标…')
    # 此计算机安装时图标放安装目录（其他用户读不到安装者的 %APPDATA%）
    icon = os.path.join(path_dir if all_users else sysutil.appdata_dir(), 'icon.ico')
    icon_path = icon if _gen_icon(icon) else None
    report(82, '正在注册系统集成…')
    # 桌面右键菜单不设开关：安装即生效
    sysutil.context_menu_install(icon_path, exe=dst, all_users=all_users)
    if shortcut:
        report(88, '正在创建桌面快捷方式…')
        create_desktop_shortcut(dst)
    if autostart:
        sysutil.autostart_set(exe=dst, all_users=all_users)
    else:
        sysutil.autostart_remove()
    report(93, '正在写入卸载信息…')
    sysutil.uninstall_reg_install(dst, all_users=all_users)
    report(100, '完成')
    return dst


def uninstall():
    """清除全部注册表集成（HKCU/HKLM 均尝试）并延迟删除安装目录（exe 运行中无法删除自身）。
    用户数据（%APPDATA%\\ZviberPanel）保留，重装后配置与待办不丢。"""
    sysutil.uninstall_reg_remove()
    sysutil.context_menu_remove()
    sysutil.autostart_remove()
    remove_desktop_shortcut()
    if is_installed():
        # exe 运行中无法删除自身：延迟 + 四轮重试（覆盖卸载完成提示框存活期）
        target = os.path.dirname(os.path.abspath(sys.executable))
        seq = ['ping 127.0.0.1 -n 4 > nul', 'rmdir /s /q "%s"' % target] * 4
        subprocess.Popen('cmd /c ' + ' & '.join(seq), creationflags=subprocess.CREATE_NO_WINDOW)


def _desktop_dir():
    """桌面真实路径（SHGetFolderPath 兼容 OneDrive 重定向的桌面）。"""
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    try:
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser('~'), 'Desktop')


def create_desktop_shortcut(exe_path):
    """在桌面创建指向 exe 的 .lnk：借 PowerShell 的 WScript.Shell COM，免 pywin32 依赖（Win7+ 自带）。"""
    lnk = os.path.join(_desktop_dir(), '%s.lnk' % APP_TITLE)
    args = tuple(p.replace("'", "''") for p in (lnk, exe_path, os.path.dirname(exe_path), exe_path))
    ps = ("$w=New-Object -ComObject WScript.Shell;"
          "$s=$w.CreateShortcut('%s');$s.TargetPath='%s';$s.WorkingDirectory='%s';"
          "$s.IconLocation='%s,0';$s.Save()" % args)
    subprocess.call(['powershell', '-NoProfile', '-Command', ps],
                    creationflags=subprocess.CREATE_NO_WINDOW)


def remove_desktop_shortcut():
    """卸载时清掉桌面快捷方式（没有就跳过）。"""
    try:
        os.remove(os.path.join(_desktop_dir(), '%s.lnk' % APP_TITLE))
    except OSError:
        pass


def _relaunch(path):
    subprocess.Popen([path])


def _uninstall_flow():
    """--uninstall 入口（也供 Windows 应用列表调用）：HKLM 安装需提权；先请运行中的实例退出。"""
    if sysutil.uninstall_reg_get('InstallLocation', True) and not is_admin():
        relaunch_elevated(['--uninstall'])
        return
    request_quit()
    time.sleep(1.0)
    uninstall()
    box = QMessageBox(QMessageBox.Information, '卸载 Zviber',
                      '卸载完成。\n待办与配置数据保留在 %APPDATA%\\ZviberPanel。')
    from PyQt5.QtCore import QTimer
    QTimer.singleShot(3000, box.close)  # 3 秒自动关闭，免点击
    box.exec_()


def maybe_install():
    """frozen 场景入口处理；返回 True 表示已处理完毕（安装/卸载/取消），调用方应退出。"""
    if not getattr(sys, 'frozen', False):
        return False
    if '--uninstall' in sys.argv:
        _uninstall_flow()
        return True
    if '--install-elevated' in sys.argv:
        # 提权后的安装实例：直接执行安装并展示进度/完成页
        path = sys.argv[sys.argv.index('--install-elevated') + 1]
        wiz = InstallWizard()
        wiz.start_install(path, all_users=True,
                          shortcut='--no-shortcut' not in sys.argv,
                          autostart='--no-autostart' not in sys.argv)
        wiz.exec_()
        return True
    if is_installed():
        return False
    if os.environ.get('ZVIBER_SHOT') or os.environ.get('ZVIBER_GRABSCREEN'):
        return False  # 自检模式直接运行，不弹安装窗口
    if os.environ.get('ZVIBER_AUTO_INSTALL'):
        # 测试钩子：跳过向导按默认项静默安装
        _relaunch(install(install_dir()))
        return True
    InstallWizard().exec_()
    return True


def _scale_qss(css, scale):
    """与 themes.build_qss 相同规则放大 px 尺寸（补充样式走同一套缩放）。"""
    if abs(scale - 1.0) < 1e-6:
        return css
    import re
    return re.sub(r'(\d+(?:\.\d+)?)px', lambda m: '%gpx' % (round(float(m.group(1)) * scale, 2)), css)


def _sc(v):
    """按系统 DPI 缩放固定像素尺寸（与 app.sc 同一套，保证向导布局密度与设置窗口一致）。"""
    import app as ui
    return ui.sc(v)


def _fmt_size(n):
    if n >= 1 << 30:
        return '%.1f GB' % (n / (1 << 30))
    return '%.0f MB' % (n / (1 << 20))


class InstallWizard(QDialog):
    """安装向导（深色主题，与程序一致）：选项页 → 进度页 → 完成页。"""

    _KEEP = set([APP_EXE.lower(), 'icon.ico'])  # 覆盖安装时允许已存在的文件

    def __init__(self):
        super().__init__()
        import app as ui
        from themes import build_qss
        self.setObjectName('settingsDlg')  # 复用主题对话框底色
        self.setWindowTitle('安装 %s' % APP_TITLE)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)  # 圆角外透明显示，避免首帧白闪
        self.setFixedWidth(_sc(480))
        self._drag = None
        self._dst = None
        self._path_touched = False

        cn, num = ui.pick_fonts()
        scale = ui.ui_scale()
        # 与 app.py 应用主题时参数一致：indicator 对勾/圆点图标与设置面板完全相同
        qss = build_qss('nocturne', cn, num, scale, ui._indicator_icons())
        self.setStyleSheet(qss + _scale_qss(_EXTRA_QSS, scale).replace('%CN%', cn))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = QWidget()
        card.setObjectName('settingsPanel')
        root.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(_sc(18), _sc(6), _sc(14), _sc(16))
        lay.setSpacing(0)

        # 标题栏（可拖动）
        self.titlebar = QFrame()
        self.titlebar.setFixedHeight(_sc(40))
        tb = QHBoxLayout(self.titlebar)
        tb.setContentsMargins(2, 0, 0, 0)
        ico = QLabel()
        ico.setPixmap(ui.make_icon().pixmap(_sc(22), _sc(22)))
        tb.addWidget(ico)
        title = QLabel('  %s' % APP_TITLE)
        title.setObjectName('setTitle')
        tb.addWidget(title)
        ver = QLabel('v%s' % sysutil.APP_VERSION)
        ver.setObjectName('setLabel')
        tb.addWidget(ver, 0, Qt.AlignVCenter)
        tb.addStretch(1)
        close = QToolButton()
        close.setObjectName('closeBtn')
        close.setText('✕')
        close.setFixedSize(_sc(28), _sc(24))
        close.setToolTip('关闭')
        close.clicked.connect(self.reject)
        tb.addWidget(close)
        lay.addWidget(self.titlebar)

        self._stack = QStackedLayout()
        self._stack.addWidget(self._build_options_page())
        self._stack.addWidget(self._build_progress_page())
        self._stack.addWidget(self._build_finish_page())
        lay.addLayout(self._stack)
        self._update_space_info()
        # 无边框 Tool 窗口不会被系统居中，显式居中避免出现在屏幕边缘/半屏外
        self.adjustSize()
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(scr.x() + (scr.width() - self.width()) // 2,
                  scr.y() + (scr.height() - self.height()) // 2)

    # ---- 拖动无边框窗口 ----
    def mousePressEvent(self, e):
        self._drag = e.globalPos() - self.frameGeometry().topLeft() \
            if e.button() == Qt.LeftButton and self.titlebar.geometry().contains(e.pos()) else None

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    # ---- 选项页 ----
    def _section(self, text):
        lb = QLabel(text)
        lb.setObjectName('setLabel')
        return lb

    def _build_options_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(_sc(2), _sc(8), _sc(4), 0)
        lay.setSpacing(_sc(8))

        lay.addWidget(self._section('安装范围'))
        self._radio_user = QRadioButton('仅当前用户')
        self._radio_user.setChecked(True)
        self._radio_all = QRadioButton('所有用户（需要管理员权限）')
        self._radio_all.toggled.connect(self._on_scope_changed)
        lay.addWidget(self._radio_user)
        row_all = QHBoxLayout()
        row_all.setSpacing(4)
        row_all.addWidget(self._radio_all)
        shield = QLabel()
        shield.setPixmap(self.style().standardIcon(QStyle.SP_VistaShield).pixmap(_sc(14), _sc(14)))
        shield.setToolTip('需要管理员权限')
        row_all.addWidget(shield)
        row_all.addStretch(1)
        lay.addLayout(row_all)

        lay.addWidget(self._section('安装位置'))
        row = QHBoxLayout()
        row.setSpacing(8)
        self._path = QLineEdit(install_dir())
        self._path.setObjectName('pathEdit')
        self._path.textEdited.connect(self._on_path_edited)
        btn = QPushButton('浏览…')
        btn.setObjectName('setBtn')
        btn.clicked.connect(self._browse)
        row.addWidget(self._path, 1)
        row.addWidget(btn)
        lay.addLayout(row)
        self._space = QLabel()
        self._space.setObjectName('setLabel')
        lay.addWidget(self._space)

        lay.addWidget(self._section('附加选项'))
        self._shortcut = QCheckBox('创建桌面快捷方式')
        self._shortcut.setChecked(True)
        self._auto = QCheckBox('开机自动启动')
        self._auto.setChecked(True)
        lay.addWidget(self._shortcut)
        lay.addWidget(self._auto)
        lay.addStretch(1)

        btns = QHBoxLayout()
        btns.setSpacing(_sc(8))
        btns.addStretch(1)
        cancel = QPushButton('取消')
        cancel.setObjectName('setBtn')
        cancel.setFixedWidth(_sc(84))
        cancel.clicked.connect(self.reject)
        self._ok = QPushButton('安装')
        self._ok.setObjectName('setSave')
        self._ok.setFixedWidth(_sc(84))
        self._ok.setDefault(True)
        self._ok.clicked.connect(self._on_install)
        btns.addWidget(cancel)
        btns.addWidget(self._ok)
        lay.addLayout(btns)
        return page

    # ---- 进度页 / 完成页 ----
    def _build_progress_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(_sc(2), _sc(34), _sc(4), _sc(30))
        lay.setSpacing(_sc(12))
        self._status = QLabel('正在安装…')
        self._status.setObjectName('setTitle')
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        lay.addWidget(self._status)
        lay.addWidget(self._bar)
        lay.addStretch(1)
        return page

    def _build_finish_page(self):
        # 主流安装器收尾页：居中标题 + 居中「立即启动」勾选 + 居中完成按钮
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(_sc(2), _sc(14), _sc(4), 0)
        lay.setSpacing(_sc(10))
        self._finish_title = QLabel('安装完成')
        self._finish_title.setObjectName('setTitle')
        self._run_now = QCheckBox('立即启动 %s' % APP_TITLE)
        self._run_now.setChecked(True)
        lay.addStretch(1)
        lay.addWidget(self._finish_title, 0, Qt.AlignCenter)
        lay.addSpacing(_sc(18))
        lay.addWidget(self._run_now, 0, Qt.AlignCenter)
        lay.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        done = QPushButton('完成')
        done.setObjectName('setSave')
        done.setFixedWidth(_sc(84))
        done.setDefault(True)
        done.clicked.connect(self._on_finish)
        btns.addWidget(done)
        btns.addStretch(1)
        lay.addLayout(btns)
        return page

    # ---- 选项页交互 ----
    def _on_scope_changed(self):
        if not self._path_touched:
            self._path.setText(install_dir(self._radio_all.isChecked()))
        self._update_space_info()

    def _on_path_edited(self):
        self._path_touched = True
        self._update_space_info()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, '选择安装文件夹', self._path.text())
        if d:
            self._path_touched = True
            self._path.setText(d)
            self._update_space_info()

    def _check_dir(self, path):
        """只允许空目录/新目录（含覆盖重装），避免卸载时误删用户文件。"""
        if not path.strip():
            return '请输入安装路径'
        if not os.path.splitdrive(path)[1].strip('\\/'):
            return '不能安装到磁盘根目录'
        if os.path.isdir(path):
            extras = [f for f in os.listdir(path) if f.lower() not in self._KEEP]
            if extras:
                return '目标文件夹不为空，请选择空文件夹或新文件夹'
        return None

    def _update_space_info(self):
        path = self._path.text().strip()
        err = self._check_dir(path)
        if not err:
            p = path
            while not os.path.isdir(p):
                p2 = os.path.dirname(p)
                if p2 == p:
                    break
                p = p2
            try:
                free = shutil.disk_usage(p).free
                need = os.path.getsize(sys.executable)
                drive = os.path.splitdrive(os.path.abspath(p))[0]
                if need > free:
                    err = '磁盘空间不足：需要 %s，%s 盘仅剩 %s' % (_fmt_size(need), drive, _fmt_size(free))
                else:
                    self._space.setText('所需空间 %s，%s 盘可用 %s' % (_fmt_size(need), drive, _fmt_size(free)))
                    self._space.setProperty('err', False)
            except OSError:
                err = '路径无效'
        if err:
            self._space.setText(err)
            self._space.setProperty('err', True)
        self._space.style().unpolish(self._space)
        self._space.style().polish(self._space)
        self._ok.setEnabled(not err)

    def _on_install(self):
        path = self._path.text().strip()
        all_users = self._radio_all.isChecked()
        if all_users and not is_admin():
            args = ['--install-elevated', '"%s"' % path]
            if not self._shortcut.isChecked():
                args.append('--no-shortcut')
            if not self._auto.isChecked():
                args.append('--no-autostart')
            if relaunch_elevated(args):
                self.accept()  # 提权实例接管安装
            return  # UAC 被拒绝时留在选项页
        self.start_install(path, all_users, self._shortcut.isChecked(), self._auto.isChecked())

    # ---- 安装执行 ----
    def start_install(self, path, all_users, shortcut, autostart):
        """执行安装并切换到进度/完成页（提权实例直接调用）。"""
        self._stack.setCurrentIndex(1)
        self._all_users = all_users

        def prog(pct, text):
            self._status.setText(text)
            self._bar.setValue(pct)
            QApplication.processEvents()
        try:
            self._dst = install(path, all_users, shortcut, autostart, progress=prog)
        except Exception as e:
            QMessageBox.critical(self, '安装失败', str(e))
            self._stack.setCurrentIndex(0)
            return
        self._stack.setCurrentIndex(2)

    def _on_finish(self):
        if self._dst and self._run_now.isChecked():
            if self._all_users:
                # 提权实例不能直接启动（面板会带管理员身份）：借 explorer 以普通用户身份拉起
                subprocess.Popen(['explorer.exe', self._dst])
            else:
                _relaunch(self._dst)
        self.accept()
