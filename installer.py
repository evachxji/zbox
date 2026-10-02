# -*- coding: utf-8 -*-
"""安装/卸载：深色主题安装向导（路径/范围/进度/完成页）+ 卸载向导（可选删除个人数据）。
安装包形态：setup.pyw 打成 onefile exe，内嵌 onedir 程序目录为 payload（--add-data），
向导把 payload 整体复制到安装目录（按字节回报进度）；装出来的程序本体是 onedir（一堆小文件）。
仅冻结为 exe 时生效；源码运行（pythonw main.pyw）不受影响，仍走 install.py。
样式复用 themes.py NOCTURNE 主题与 #settingsPanel/#setBtn/#setSave 规范，仅补充少量同配色控件样式。
"""
import os
import shutil
import subprocess
import sys
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QStyle,
                             QLabel, QFrame, QToolButton, QCheckBox, QRadioButton,
                             QPushButton, QLineEdit, QProgressBar, QFileDialog,
                             QStackedLayout, QMessageBox)

import sysutil

APP_EXE = 'zviber.exe'
LEGACY_APP_EXE = 'ZviberPanel.exe'   # 旧名程序本体：覆盖重装时用来识别旧安装
APP_TITLE = 'Zviber 桌面日历'

# 向导补充样式：沿用 NOCTURNE 深色配色（#e8a33d 强调色，#e05252 危险色），%CN%/%NUM% 运行时替换
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
QLabel#pctText { color: #e8a33d; font: 700 30px "%NUM%"; }
QLabel#finishMark { color: #e8a33d; font: 600 40px "%CN%"; }

QPushButton#dangerBtn {
    background: #d64545; border: none; border-radius: 10px;
    color: #fff; font: 600 13px "%CN%"; padding: 7px 18px;
}
QPushButton#dangerBtn:hover { background: #e05252; }
QPushButton#dangerBtn:pressed { background: #b93a3a; }
"""


def install_dir(all_users=False):
    """默认安装目录：当前用户 → %LOCALAPPDATA%\\Programs\\zviber；此计算机 → Program Files\\zviber。
    旧版目录名是 ZviberPanel（大写），升级时由 _take_over_legacy 接管。"""
    if all_users:
        base = os.environ.get('ProgramFiles') or r'C:\Program Files'
    else:
        base = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'Programs')
    return os.path.join(base, sysutil.APP_NAME)


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


def _bundle_dir():
    """frozen onedir 的程序目录（exe 与 _internal\\ 所在目录）。"""
    return os.path.dirname(os.path.abspath(sys.executable))


def _payload_dir():
    """安装包内嵌的 onedir 程序目录：frozen 时在 _MEIPASS\\payload；
    源码调试安装向导时回退到构建中间产物 dist\\build\\app\\zviber。"""
    mp = getattr(sys, '_MEIPASS', None)
    if mp:
        return os.path.join(mp, 'payload')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dist', 'build', 'app',
                        sysutil.APP_NAME)


def _exe_dir():
    return os.path.normcase(_bundle_dir())


def _dir_size(path):
    """目录总字节数（onedir 程序目录体积，供空间预估与卸载项 EstimatedSize）。"""
    total = 0
    for base, _dirs, names in os.walk(path):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(base, n))
            except OSError:
                pass
    return total


def is_installed():
    """当前 frozen exe 是否正从某个安装位置运行（按应用列表注册信息识别，支持自定义路径）。"""
    if not getattr(sys, 'frozen', False):
        return False
    for au in (False, True):
        loc = sysutil.uninstall_reg_get('InstallLocation', au)
        if loc and os.path.normcase(loc) == _exe_dir():
            return True
    return _exe_dir() in (os.path.normcase(install_dir(False)), os.path.normcase(install_dir(True)))


def registered_install_dir():
    """已注册的安装目录（HKCU 优先，HKLM 兜底）；没有安装记录返回 None。
    旧名（ZviberPanel）的安装记录也算，供升级时接管。"""
    for all_users in (False, True):
        loc = sysutil.uninstall_reg_get('InstallLocation', all_users)
        if loc:
            return loc
    for all_users in (False, True):
        loc = sysutil.legacy_uninstall_reg_get('InstallLocation', all_users)
        if loc:
            return loc
    return None


def _take_over_legacy():
    """接管旧名版本：清掉 ZviberPanel 留下的注册表残留，并删掉旧安装目录。
    旧目录里只有程序文件（安装向导只允许空目录/旧安装目录），删掉不会碰到用户数据；
    用户数据是 %APPDATA%\\ZviberPanel，由 sysutil.appdata_dir() 改名搬到新目录，不在这里动。"""
    old_dir = None
    for all_users in (False, True):
        loc = sysutil.legacy_uninstall_reg_get('InstallLocation', all_users)
        if loc and os.path.normcase(loc) != os.path.normcase(_exe_dir()):
            old_dir = loc
            break
    sysutil.legacy_integration_remove()
    if old_dir and os.path.isdir(old_dir):
        # 旧版可能还在运行（旧 exe 名字不同、单实例 IPC 也不互通），先请它退出再删
        shutil.rmtree(old_dir, ignore_errors=True)


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


def _copy_tree_with_progress(src_root, dst_root, cb):
    """整目录复制，按已复制字节数回报 0-100（逐文件回调，变化时才报）。"""
    files = []
    total = 0
    for base, _dirs, names in os.walk(src_root):
        for n in names:
            p = os.path.join(base, n)
            files.append(p)
            total += os.path.getsize(p)
    done = 0
    last = -1
    for p in files:
        out = os.path.join(dst_root, os.path.relpath(p, src_root))
        d = os.path.dirname(out)
        if not os.path.isdir(d):
            os.makedirs(d)
        shutil.copy2(p, out)
        done += os.path.getsize(p)
        pct = done * 100 // total if total else 100
        if pct != last:
            last = pct
            cb(pct)


def install(path_dir, all_users=False, autostart=True, shortcut=True, progress=None):
    """把安装包内嵌的 onedir 程序目录整体复制到指定目录并注册系统集成，返回安装后的 exe 路径。
    目标目录里已有旧安装（含 zviber.exe，或旧名的 ZviberPanel.exe，_check_dir 保证无用户文件）
    时先清空再复制；旧名的安装记录/右键菜单/旧目录由 _take_over_legacy 接管清理。
    progress(pct, text) 回报进度。"""
    def report(pct, text):
        if progress:
            progress(pct, text)
    src = _payload_dir()
    _take_over_legacy()
    if os.path.normcase(src) != os.path.normcase(os.path.abspath(path_dir)):
        if os.path.isfile(os.path.join(path_dir, APP_EXE)) or \
                os.path.isfile(os.path.join(path_dir, LEGACY_APP_EXE)):
            shutil.rmtree(path_dir)  # 覆盖重装：清掉旧版全部文件（含残留的 _internal）
        os.makedirs(path_dir, exist_ok=True)
        _copy_tree_with_progress(src, path_dir, lambda p: report(p * 7 // 10, '正在复制程序文件…'))
    dst = os.path.join(path_dir, APP_EXE)
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
    sysutil.uninstall_reg_install(dst, all_users=all_users, size_kb=_dir_size(path_dir) // 1024)
    report(100, '完成')
    return dst


def uninstall(remove_user_data=False, progress=None):
    """清除全部注册表集成（HKCU/HKLM 均尝试）、桌面快捷方式，并延迟删除安装目录（exe 运行中无法删除自身）。
    remove_user_data=True 时连同 %APPDATA%\\zviber（待办、格子、配置）一起删除；默认保留，重装不丢。
    progress(pct, text) 回报进度。"""
    def report(pct, text):
        if progress:
            progress(pct, text)
    report(10, '正在移除系统集成…')
    sysutil.uninstall_reg_remove()
    sysutil.context_menu_remove()
    sysutil.autostart_remove()
    report(35, '正在删除桌面快捷方式…')
    remove_desktop_shortcut()
    if remove_user_data:
        report(60, '正在删除个人数据…')
        shutil.rmtree(sysutil.appdata_dir(), ignore_errors=True)
    if is_installed():
        report(85, '正在清理程序文件…')
        # exe 运行中无法删除自身：延迟 + 六轮重试（覆盖卸载向导完成页的存活期）
        seq = ['ping 127.0.0.1 -n 4 > nul', 'rmdir /s /q "%s"' % _bundle_dir()] * 6
        subprocess.Popen('cmd /c ' + ' & '.join(seq), creationflags=subprocess.CREATE_NO_WINDOW)
    report(100, '完成')


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
    """--uninstall 入口（也供 Windows 应用列表调用）：HKLM 安装需提权；卸载向导与安装向导同风格。"""
    if sysutil.uninstall_reg_get('InstallLocation', True) and not is_admin():
        relaunch_elevated(['--uninstall'])
        return
    UninstallWizard().exec_()


def maybe_install():
    """frozen 程序本体入口处理：--uninstall 走卸载向导。
    返回 True 表示已处理完毕，调用方应退出。程序本体不再兼任安装包（安装包是 setup.pyw 打的 exe）。"""
    if not getattr(sys, 'frozen', False):
        return False
    if '--uninstall' in sys.argv:
        _uninstall_flow()
        return True
    return False


def setup_main():
    """安装包入口（setup.pyw 打成的 onefile exe）：安装向导 / 提权安装实例。返回进程退出码。"""
    if '--install-elevated' in sys.argv:
        # 提权后的安装实例：必须先 show 再装——否则安装跑完才弹窗，进度页整段被跳过
        path = sys.argv[sys.argv.index('--install-elevated') + 1]
        wiz = InstallWizard()
        wiz.show()
        QTimer.singleShot(0, lambda: wiz.start_install(
            path, all_users=True,
            shortcut='--no-shortcut' not in sys.argv,
            autostart='--no-autostart' not in sys.argv))
        wiz.exec_()
        return 0
    if os.environ.get('ZVIBER_AUTO_INSTALL'):
        # 测试钩子：跳过向导按默认项静默安装
        _relaunch(install(install_dir()))
        return 0
    InstallWizard().exec_()
    return 0


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


class _WizardBase(QDialog):
    """安装/卸载向导共用骨架：NOCTURNE 主题、无边框圆角卡片、可拖标题栏、页面栈。"""

    def __init__(self, action):
        super().__init__()
        import app as ui
        from themes import build_qss
        self.setObjectName('settingsDlg')  # 复用主题对话框底色
        self.setWindowTitle('%s %s' % (action, APP_TITLE))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)  # 圆角外透明显示，避免首帧白闪
        self.setFixedWidth(_sc(480))
        self._drag = None

        cn, num = ui.pick_fonts()
        scale = ui.ui_scale()
        # 与 app.py 应用主题时参数一致：indicator 对勾/圆点图标与设置面板完全相同
        qss = build_qss('nocturne', cn, num, scale, ui._indicator_icons())
        self.setStyleSheet(qss + _scale_qss(_EXTRA_QSS, scale).replace('%CN%', cn).replace('%NUM%', num))

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
        lay.addLayout(self._stack)

    def _show_centered(self):
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

    def _section(self, text):
        lb = QLabel(text)
        lb.setObjectName('setLabel')
        return lb

    # ---- 共用页面 ----
    def _build_progress_page(self, status_text):
        """进度页：居中大号百分比 + 状态行 + 进度条。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(_sc(2), _sc(26), _sc(4), _sc(24))
        lay.setSpacing(_sc(8))
        self._pct = QLabel('0%')
        self._pct.setObjectName('pctText')
        self._pct.setAlignment(Qt.AlignCenter)
        self._status = QLabel(status_text)
        self._status.setObjectName('setLabel')
        self._status.setAlignment(Qt.AlignCenter)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)
        lay.addStretch(1)
        lay.addWidget(self._pct)
        lay.addWidget(self._status)
        lay.addSpacing(_sc(6))
        lay.addWidget(self._bar)
        lay.addStretch(1)
        return page

    def _build_finish_page(self, title, checkbox=None):
        """完成页：居中 ✓ 标记 + 标题 + 副说明 +（可选）勾选框 + 完成按钮。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(_sc(2), _sc(16), _sc(4), 0)
        lay.setSpacing(_sc(6))
        mark = QLabel('✓')
        mark.setObjectName('finishMark')
        mark.setAlignment(Qt.AlignCenter)
        self._finish_title = QLabel(title)
        self._finish_title.setObjectName('setTitle')
        self._finish_title.setAlignment(Qt.AlignCenter)
        lay.addStretch(1)
        lay.addWidget(mark)
        lay.addSpacing(_sc(2))
        lay.addWidget(self._finish_title)
        lay.addSpacing(_sc(8))
        if checkbox is not None:
            lay.addWidget(checkbox, 0, Qt.AlignCenter)
            lay.addSpacing(_sc(4))
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

    def _report_progress(self, pct, text):
        """安装/卸载共用的进度回报：刷界面保证复制大文件时进度可见。"""
        self._status.setText(text)
        self._bar.setValue(pct)
        self._pct.setText('%d%%' % pct)
        QApplication.processEvents()

    def _on_finish(self):
        self.accept()


class InstallWizard(_WizardBase):
    """安装向导（深色主题，与程序一致）：选项页 → 进度页 → 完成页。"""

    def __init__(self):
        super().__init__('安装')
        self._dst = None
        self._path_touched = False
        self._run_now = QCheckBox('立即启动 %s' % APP_TITLE)
        self._run_now.setChecked(True)
        self._stack.addWidget(self._build_options_page())
        self._stack.addWidget(self._build_progress_page('正在安装…'))
        self._stack.addWidget(self._build_finish_page('安装完成', checkbox=self._run_now))
        self._update_space_info()
        self._show_centered()

    # ---- 选项页 ----
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
        """只允许空目录/新目录/覆盖重装（目录里有 zviber.exe，或旧名的 ZviberPanel.exe，
        视为旧安装），避免卸载时误删用户文件。"""
        if not path.strip():
            return '请输入安装路径'
        if not os.path.splitdrive(path)[1].strip('\\/'):
            return '不能安装到磁盘根目录'
        if os.path.isdir(path):
            names = [f.lower() for f in os.listdir(path)]
            if names and not ({APP_EXE.lower(), LEGACY_APP_EXE.lower()} & set(names)):
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
                need = _dir_size(_payload_dir())
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
        try:
            self._dst = install(path, all_users, shortcut, autostart, progress=self._report_progress)
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


class UninstallWizard(_WizardBase):
    """卸载向导（与安装向导同风格）：确认页（可选删除个人数据）→ 进度页 → 完成页。"""

    def __init__(self):
        super().__init__('卸载')
        self._stack.addWidget(self._build_confirm_page())
        self._stack.addWidget(self._build_progress_page('正在卸载…'))
        self._stack.addWidget(self._build_finish_page('卸载完成'))
        self._show_centered()

    # ---- 确认页 ----
    def _build_confirm_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(_sc(2), _sc(8), _sc(4), 0)
        lay.setSpacing(_sc(8))
        t = QLabel('卸载 %s' % APP_TITLE)
        t.setObjectName('setTitle')
        lay.addWidget(t)
        desc = QLabel('将从电脑中移除程序、开机自启、桌面右键菜单与桌面快捷方式。')
        desc.setObjectName('setLabel')
        desc.setWordWrap(True)
        lay.addWidget(desc)
        lay.addSpacing(_sc(8))
        self._del_data = QCheckBox('同时删除个人数据（待办事项、格子与全部配置）')
        lay.addWidget(self._del_data)
        lay.addStretch(1)
        btns = QHBoxLayout()
        btns.setSpacing(_sc(8))
        btns.addStretch(1)
        cancel = QPushButton('取消')
        cancel.setObjectName('setBtn')
        cancel.setFixedWidth(_sc(84))
        cancel.clicked.connect(self.reject)
        ok = QPushButton('卸载')
        ok.setObjectName('dangerBtn')
        ok.setFixedWidth(_sc(84))
        ok.setDefault(True)
        ok.clicked.connect(self._on_uninstall)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)
        return page

    # ---- 卸载执行 ----
    def _on_uninstall(self):
        self._stack.setCurrentIndex(1)
        request_quit()  # 先请运行中的面板退出，避免文件占用
        self._report_progress(5, '正在等待面板退出…')
        time.sleep(1.0)
        try:
            uninstall(remove_user_data=self._del_data.isChecked(), progress=self._report_progress)
        except Exception as e:
            QMessageBox.critical(self, '卸载失败', str(e))
            self._stack.setCurrentIndex(0)
            return
        self._stack.setCurrentIndex(2)