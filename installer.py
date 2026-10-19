# -*- coding: utf-8 -*-
"""安装/卸载：深色主题安装向导（语言/路径/进度/完成页）+ 卸载向导（可选删除个人数据）。
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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QFrame, QToolButton, QCheckBox, QComboBox,
                             QPushButton, QLineEdit, QProgressBar, QFileDialog,
                             QStackedLayout, QMessageBox)

import i18n
import sysutil
from i18n import t

APP_EXE = 'zbox.exe'
LEGACY_APP_EXE = 'zviber.exe'   # 旧名程序本体：覆盖重装时用来识别旧安装
# 桌面快捷方式固定用品牌名，不随界面语言变化——否则英文安装会建 Zbox.lnk、
# 中文卸载去找另一份，旧快捷方式永远删不掉
SHORTCUT_NAME = 'Zbox'
LEGACY_SHORTCUT_NAMES = ('Zbox桌面格子',)   # 改名前的快捷方式文件名，卸载时一并清理

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
    """默认安装目录：当前用户 → %LOCALAPPDATA%\\Programs\\zbox；此计算机 → Program Files\\zbox。
    旧版目录名是 zviber，升级时由 _take_over_legacy 接管。"""
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
    """以管理员身份重启自身（触发 UAC）；用户拒绝时返回 False。
    参数用 subprocess.list2cmdline 统一加引号（调用方传原始值，不要再手工包引号）；
    源码运行时 sys.executable 是 python.exe，必须先把脚本路径补到参数最前。"""
    import ctypes
    args = list(args)
    if not getattr(sys, 'frozen', False):
        args.insert(0, os.path.abspath(sys.argv[0]))
    return ctypes.windll.shell32.ShellExecuteW(
        None, 'runas', sys.executable, subprocess.list2cmdline(args), None, 1) > 32


def _bundle_dir():
    """frozen onedir 的程序目录（exe 与 _internal\\ 所在目录）。"""
    return os.path.dirname(os.path.abspath(sys.executable))


def _payload_dir():
    """安装包内嵌的 onedir 程序目录：frozen 时在 _MEIPASS\\payload；
    源码调试安装向导时回退到构建中间产物 dist\\build\\app\\zbox。"""
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
    旧名（zviber）的安装记录也算，供升级时接管。"""
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
    """接管旧名版本：清掉 zviber 留下的注册表残留，并删掉旧安装目录。
    旧目录里只有程序文件（安装向导只允许空目录/旧安装目录），删掉不会碰到用户数据；
    用户数据是 %APPDATA%\\zviber，由 sysutil.appdata_dir() 改名搬到新目录，不在这里动。"""
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
    """通知运行中的实例退出（卸载前调用，避免文件占用）。
    返回是否连上服务：全新安装时没有实例在跑，不必白等。"""
    from PySide6.QtNetwork import QLocalSocket
    s = QLocalSocket()
    s.connectToServer(sysutil.IPC_KEY)
    if s.waitForConnected(500):
        s.write(b'quit')
        s.flush()
        s.waitForBytesWritten(500)
        return True
    return False


def _process_events():
    """安装/卸载在等待或重试期间保持界面可响应；测试里没有 QApplication 时静默跳过。"""
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def _rmtree_retry(path, timeout=15.0, on_wait=None):
    """删除目录；被占用等 OSError 每 0.25s 重试，超时后抛出。
    FileNotFoundError 说明已被删掉，视为成功。"""
    deadline = time.monotonic() + timeout
    while True:
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            if on_wait:
                on_wait()
            time.sleep(0.25)
            _process_events()


def _registered_zbox_dirs():
    """所有可能装着 Zbox 的目录：注册表记录 + 两个默认安装位置。"""
    candidates = {
        sysutil.uninstall_reg_get('InstallLocation', False),
        sysutil.uninstall_reg_get('InstallLocation', True),
        install_dir(False),
        install_dir(True),
    }
    return {os.path.normpath(p) for p in candidates if p}


def _is_zbox_program_dir(path):
    """只有明确含 zbox.exe 的目录才算旧安装，避免误删用户自选目录里的文件。"""
    return os.path.isfile(os.path.join(path, APP_EXE))


def cleanup_existing_zbox(progress=None):
    """安装前清理旧 Zbox：请运行中的实例退出，删掉旧程序目录与系统集成。
    只触碰 _is_zbox_program_dir 为真的目录；%APPDATA%\\zbox 个人数据一律不动。
    旧实例退出可能要几秒（格子 shutdown 的图标位置修正），目录被占用时按 0.25s 重试、
    最长 15s；仍删不掉则抛 RuntimeError 中止安装，不带残留继续覆盖。
    progress(pct, text) 回报进度（等待旧实例退出时显示等待文案）。"""
    def report(pct, text):
        if progress:
            progress(pct, text)

    def waiting():
        report(6, t('installer.progress.waiting_exit'))

    report(4, t('installer.progress.cleaning'))
    if request_quit():
        waiting()
    errors = []
    for path in _registered_zbox_dirs():
        if not os.path.isdir(path) or not _is_zbox_program_dir(path):
            continue
        try:
            _rmtree_retry(path, on_wait=waiting)
        except OSError as exc:
            errors.append('%s: %s' % (path, exc))
    if errors:
        raise RuntimeError(t('installer.err.clean_failed', detail='\n'.join(errors)))
    sysutil.autostart_remove()
    sysutil.context_menu_remove_zbox()
    sysutil.uninstall_reg_remove_zbox()


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
    目标目录里已有旧安装（含 zbox.exe，或旧名的 zviber.exe，_check_dir 保证无用户文件）
    时先清空再复制；旧名的安装记录/右键菜单/旧目录由 _take_over_legacy 接管清理。
    progress(pct, text) 回报进度。"""
    def report(pct, text):
        if progress:
            progress(pct, text)
    cleanup_existing_zbox(progress=progress)
    src = _payload_dir()
    _take_over_legacy()
    if os.path.normcase(src) != os.path.normcase(os.path.abspath(path_dir)):
        if os.path.isfile(os.path.join(path_dir, APP_EXE)) or \
                os.path.isfile(os.path.join(path_dir, LEGACY_APP_EXE)):
            shutil.rmtree(path_dir)  # 覆盖重装：清掉旧版全部文件（含残留的 _internal）
        os.makedirs(path_dir, exist_ok=True)
        _copy_tree_with_progress(src, path_dir,
                                 lambda p: report(p * 7 // 10, t('installer.progress.copying')))
    dst = os.path.join(path_dir, APP_EXE)
    report(72, t('installer.progress.icon'))
    # 此计算机安装时图标放安装目录（其他用户读不到安装者的 %APPDATA%）
    icon = os.path.join(path_dir if all_users else sysutil.appdata_dir(), 'icon.ico')
    icon_path = icon if _gen_icon(icon) else None
    report(82, t('installer.progress.integration'))
    # 桌面右键菜单不设开关：安装即生效
    sysutil.context_menu_install(icon_path, exe=dst, all_users=all_users)
    if shortcut:
        report(88, t('installer.progress.shortcut'))
        create_desktop_shortcut(dst)
    if autostart:
        sysutil.autostart_set(exe=dst, all_users=all_users)
    else:
        sysutil.autostart_remove()
    report(93, t('installer.progress.uninstall_reg'))
    sysutil.uninstall_reg_install(
        dst, all_users=all_users, size_kb=_dir_size(path_dir) // 1024,
        language=i18n.get_language())
    report(100, t('installer.done'))
    return dst


def uninstall(remove_user_data=False, progress=None):
    """清除全部注册表集成（HKCU/HKLM 均尝试）、桌面快捷方式，并延迟删除安装目录（exe 运行中无法删除自身）。
    remove_user_data=True 时连同 %APPDATA%\\zbox（待办、格子、配置）一起删除；默认保留，重装不丢。
    progress(pct, text) 回报进度。"""
    def report(pct, text):
        if progress:
            progress(pct, text)
    report(10, t('installer.progress.remove_integration'))
    sysutil.uninstall_reg_remove()
    sysutil.context_menu_remove()
    sysutil.autostart_remove()
    report(35, t('installer.progress.remove_shortcut'))
    remove_desktop_shortcut()
    if remove_user_data:
        report(60, t('installer.progress.remove_data'))
        shutil.rmtree(sysutil.appdata_dir(), ignore_errors=True)
    if is_installed():
        report(85, t('installer.progress.remove_files'))
        # exe 运行中无法删除自身：延迟 + 六轮重试（覆盖卸载向导完成页的存活期）
        seq = ['ping 127.0.0.1 -n 4 > nul', 'rmdir /s /q "%s"' % _bundle_dir()] * 6
        subprocess.Popen('cmd /c ' + ' & '.join(seq), creationflags=subprocess.CREATE_NO_WINDOW)
    report(100, t('installer.done'))


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
    """在桌面创建指向 exe 的 .lnk：借 PowerShell 的 WScript.Shell COM，免 pywin32 依赖（Win10+ 自带）。
    文件名固定用品牌名 Zbox，不随界面语言变化。"""
    lnk = os.path.join(_desktop_dir(), '%s.lnk' % SHORTCUT_NAME)
    args = tuple(p.replace("'", "''") for p in (lnk, exe_path, os.path.dirname(exe_path), exe_path))
    ps = ("$w=New-Object -ComObject WScript.Shell;"
          "$s=$w.CreateShortcut('%s');$s.TargetPath='%s';$s.WorkingDirectory='%s';"
          "$s.IconLocation='%s,0';$s.Save()" % args)
    subprocess.call(['powershell', '-NoProfile', '-Command', ps],
                    creationflags=subprocess.CREATE_NO_WINDOW)


def remove_desktop_shortcut():
    """卸载时清掉桌面快捷方式（没有就跳过）；旧名快捷方式一并删除。"""
    desktop = _desktop_dir()
    for name in (SHORTCUT_NAME,) + LEGACY_SHORTCUT_NAMES:
        try:
            os.remove(os.path.join(desktop, '%s.lnk' % name))
        except OSError:
            pass


def _relaunch(path):
    subprocess.Popen([path])


def _uninstall_flow():
    """--uninstall 入口（也供 Windows 应用列表调用）：HKLM 安装需提权；卸载向导与安装向导同风格。"""
    if sysutil.uninstall_reg_get('InstallLocation', True) and not is_admin():
        relaunch_elevated(['--uninstall'])
        return
    UninstallWizard().exec()


def maybe_install():
    """frozen 程序本体入口处理：--uninstall 走卸载向导。
    返回 True 表示已处理完毕，调用方应退出。程序本体不再兼任安装包（安装包是 setup.pyw 打的 exe）。"""
    if not getattr(sys, 'frozen', False):
        return False
    if '--uninstall' in sys.argv:
        _uninstall_flow()
        return True
    return False


def language_from_args(argv=None):
    """解析安装器语言：--lang 显式指定优先（非法值回落系统语言），否则跟随系统界面语言。
    setup.pyw 与提权实例共用这一处解析。"""
    argv = list(sys.argv if argv is None else argv)
    if '--lang' in argv:
        i = argv.index('--lang')
        if i + 1 < len(argv):
            return i18n.resolve_language(argv[i + 1], i18n.detect_system_language())
    return i18n.detect_system_language()


_qt_translator = None


def install_qt_translator(app, language):
    """按语言装载/卸载 Qt 自带控件翻译：中文装 qtbase_zh_CN，英文用 Qt 默认。
    切换语言时先摘掉旧 translator，避免中英文案叠加。返回当前 translator（英文为 None）。"""
    global _qt_translator
    from PySide6.QtCore import QLibraryInfo, QTranslator
    if _qt_translator is not None:
        app.removeTranslator(_qt_translator)
        _qt_translator = None
    if language == i18n.ZH:
        tr = QTranslator(app)
        if tr.load('qtbase_zh_CN', QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(tr)
            _qt_translator = tr
    return _qt_translator


def setup_main():
    """安装包入口（setup.pyw 打成的 onefile exe）：安装向导 / 提权安装实例。返回进程退出码。"""
    i18n.set_language(language_from_args())
    if '--install-elevated' in sys.argv:
        # 提权后的安装实例：必须先 show 再装——否则安装跑完才弹窗，进度页整段被跳过
        path = sys.argv[sys.argv.index('--install-elevated') + 1]
        wiz = InstallWizard()
        wiz.show()
        QTimer.singleShot(0, lambda: wiz.start_install(
            path, all_users=True,
            shortcut='--no-shortcut' not in sys.argv,
            autostart='--no-autostart' not in sys.argv))
        wiz.exec()
        return 0
    if os.environ.get('ZBOX_AUTO_INSTALL'):
        # 测试钩子：跳过向导按默认项静默安装（安装范围固定为所有用户）
        _relaunch(install(install_dir(True), all_users=True))
        return 0
    InstallWizard().exec()
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

    def __init__(self):
        super().__init__()
        import app as ui
        from themes import build_qss
        self.setObjectName('settingsDlg')  # 复用主题对话框底色
        self.setWindowTitle(t('app.name'))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)  # 圆角外透明显示，避免首帧白闪
        self.setFixedWidth(_sc(480))
        self._drag = None
        self._bindings = []   # (控件, setter 方法名, 词典键)：切换语言时统一回填

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
        title = QLabel()
        title.setObjectName('setTitle')
        self._bind(title, 'app.name')
        tb.addWidget(title)
        ver = QLabel('v%s' % sysutil.APP_VERSION)
        ver.setObjectName('setLabel')
        tb.addWidget(ver, 0, Qt.AlignVCenter)
        tb.addStretch(1)
        close = QToolButton()
        close.setObjectName('closeBtn')
        close.setText('✕')
        close.setFixedSize(_sc(28), _sc(24))
        self._bind(close, 'common.close', 'setToolTip')
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

    def _bind(self, widget, key, method='setText'):
        """登记一条随语言变化的文案，并立即按当前语言写入。"""
        self._bindings.append((widget, method, key))
        getattr(widget, method)(t(key))
        return widget

    def _retranslate(self):
        """语言切换后就地回填本窗口全部已登记文案（不重建控件、不丢输入状态）。"""
        self.setWindowTitle(t('app.name'))
        for widget, method, key in self._bindings:
            getattr(widget, method)(t(key))

    def _section(self, key):
        lb = QLabel()
        lb.setObjectName('setLabel')
        return self._bind(lb, key)

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

    def _build_finish_page(self, title_key, checkbox=None):
        """完成页：居中 ✓ 标记 + 标题 + 副说明 +（可选）勾选框 + 完成按钮。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(_sc(2), _sc(16), _sc(4), 0)
        lay.setSpacing(_sc(6))
        mark = QLabel('✓')
        mark.setObjectName('finishMark')
        mark.setAlignment(Qt.AlignCenter)
        self._finish_title = QLabel()
        self._finish_title.setObjectName('setTitle')
        self._finish_title.setAlignment(Qt.AlignCenter)
        self._bind(self._finish_title, title_key)
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
        done = QPushButton()
        done.setObjectName('setSave')
        done.setFixedWidth(_sc(84))
        done.setDefault(True)
        self._bind(done, 'installer.done')
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
        super().__init__()
        self._dst = None
        self._run_now = QCheckBox()
        self._run_now.setChecked(True)
        self._bind(self._run_now, 'installer.run_now')
        self._stack.addWidget(self._build_options_page())
        self._stack.addWidget(self._build_progress_page(t('installer.installing')))
        self._stack.addWidget(self._build_finish_page('installer.installed', checkbox=self._run_now))
        self._update_space_info()
        self._show_centered()

    # ---- 选项页 ----
    def _build_options_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(_sc(2), _sc(8), _sc(4), 0)
        lay.setSpacing(_sc(8))

        lay.addWidget(self._section('installer.language'))
        self._language = QComboBox()
        self._language.setObjectName('installLanguage')
        for code, label in i18n.LANGUAGE_NAMES.items():
            self._language.addItem(label, code)
        self._language.setCurrentIndex(self._language.findData(i18n.get_language()))
        # 先设初值再连信号：构造期不触发回填
        self._language.currentIndexChanged.connect(self._select_language)
        lay.addWidget(self._language)

        lay.addWidget(self._section('installer.location'))
        row = QHBoxLayout()
        row.setSpacing(8)
        self._path = QLineEdit(install_dir(True))   # 固定所有用户安装
        self._path.setObjectName('pathEdit')
        self._path.textEdited.connect(self._on_path_edited)
        btn = QPushButton()
        btn.setObjectName('setBtn')
        self._bind(btn, 'installer.browse')
        btn.clicked.connect(self._browse)
        row.addWidget(self._path, 1)
        row.addWidget(btn)
        lay.addLayout(row)
        self._space = QLabel()
        self._space.setObjectName('setLabel')
        self._space.setWordWrap(True)   # 英文空间/错误提示较长，定宽卡片里必须折行
        lay.addWidget(self._space)

        lay.addWidget(self._section('installer.options'))
        self._shortcut = QCheckBox()
        self._shortcut.setChecked(True)
        self._bind(self._shortcut, 'installer.shortcut')
        self._auto = QCheckBox()
        self._auto.setChecked(True)
        self._bind(self._auto, 'installer.autostart')
        lay.addWidget(self._shortcut)
        lay.addWidget(self._auto)
        lay.addStretch(1)

        btns = QHBoxLayout()
        btns.setSpacing(_sc(8))
        btns.addStretch(1)
        cancel = QPushButton()
        cancel.setObjectName('setBtn')
        cancel.setFixedWidth(_sc(84))
        self._bind(cancel, 'common.cancel')
        cancel.clicked.connect(self.reject)
        self._ok = QPushButton()
        self._ok.setObjectName('setSave')
        self._ok.setFixedWidth(_sc(84))
        self._ok.setDefault(True)
        self._bind(self._ok, 'installer.install')
        self._ok.clicked.connect(self._on_install)
        btns.addWidget(cancel)
        btns.addWidget(self._ok)
        lay.addLayout(btns)
        return page

    # ---- 选项页交互 ----
    def _select_language(self, _index=None):
        """首屏语言下拉：立即切换本窗口文案，并让提权实例/卸载项继承所选语言。"""
        code = self._language.currentData()
        if not code:
            return
        i18n.set_language(code)
        install_qt_translator(QApplication.instance(), code)
        self._retranslate()
        self._update_space_info()

    def _on_path_edited(self):
        self._update_space_info()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, t('installer.pick_folder'), self._path.text())
        if d:
            self._path.setText(d)
            self._update_space_info()

    def _check_dir(self, path):
        """只允许空目录/新目录/覆盖重装（目录里有 zbox.exe，或旧名的 zviber.exe，
        视为旧安装），避免卸载时误删用户文件。"""
        if not path.strip():
            return t('installer.err.path_empty')
        if not os.path.splitdrive(path)[1].strip('\\/'):
            return t('installer.err.drive_root')
        if os.path.isdir(path):
            names = [f.lower() for f in os.listdir(path)]
            if names and not ({APP_EXE.lower(), LEGACY_APP_EXE.lower()} & set(names)):
                return t('installer.err.not_empty')
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
                    err = t('installer.err.space', need=_fmt_size(need), drive=drive,
                            free=_fmt_size(free))
                else:
                    self._space.setText(t('installer.space_info', need=_fmt_size(need),
                                          drive=drive, free=_fmt_size(free)))
                    self._space.setProperty('err', False)
            except OSError:
                err = t('installer.err.invalid_path')
        if err:
            self._space.setText(err)
            self._space.setProperty('err', True)
        self._space.style().unpolish(self._space)
        self._space.style().polish(self._space)
        self._ok.setEnabled(not err)

    def _on_install(self):
        path = self._path.text().strip().rstrip('\\/') or self._path.text().strip()
        if not is_admin():
            # 固定所有用户安装：非管理员一律提权重启，并透传语言与选项
            # 参数传原始值，引号交给 subprocess.list2cmdline（避免尾反斜杠吞掉后续参数）
            args = ['--install-elevated', path, '--lang', i18n.get_language()]
            if not self._shortcut.isChecked():
                args.append('--no-shortcut')
            if not self._auto.isChecked():
                args.append('--no-autostart')
            if relaunch_elevated(args):
                self.accept()  # 提权实例接管安装
            return  # UAC 被拒绝时留在选项页
        self.start_install(path, True, self._shortcut.isChecked(), self._auto.isChecked())

    # ---- 安装执行 ----
    def start_install(self, path, all_users, shortcut, autostart):
        """执行安装并切换到进度/完成页（提权实例直接调用）。"""
        self._stack.setCurrentIndex(1)
        self._all_users = all_users
        try:
            self._dst = install(path, all_users, shortcut, autostart, progress=self._report_progress)
        except Exception as e:
            QMessageBox.critical(self, t('installer.install_failed'), str(e))
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
        super().__init__()
        self._stack.addWidget(self._build_confirm_page())
        self._stack.addWidget(self._build_progress_page(t('installer.uninstalling')))
        self._stack.addWidget(self._build_finish_page('installer.uninstalled'))
        self._show_centered()

    # ---- 确认页 ----
    def _build_confirm_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(_sc(2), _sc(8), _sc(4), 0)
        lay.setSpacing(_sc(8))
        heading = QLabel()
        heading.setObjectName('setTitle')
        self._bind(heading, 'installer.uninstall_heading')
        lay.addWidget(heading)
        desc = QLabel()
        desc.setObjectName('setLabel')
        desc.setWordWrap(True)
        self._bind(desc, 'installer.uninstall_desc')
        lay.addWidget(desc)
        lay.addSpacing(_sc(8))
        self._del_data = QCheckBox()
        self._bind(self._del_data, 'installer.uninstall_data')
        lay.addWidget(self._del_data)
        lay.addStretch(1)
        btns = QHBoxLayout()
        btns.setSpacing(_sc(8))
        btns.addStretch(1)
        cancel = QPushButton()
        cancel.setObjectName('setBtn')
        cancel.setFixedWidth(_sc(84))
        self._bind(cancel, 'common.cancel')
        cancel.clicked.connect(self.reject)
        ok = QPushButton()
        ok.setObjectName('dangerBtn')
        ok.setFixedWidth(_sc(84))
        ok.setDefault(True)
        self._bind(ok, 'installer.uninstall')
        ok.clicked.connect(self._on_uninstall)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)
        return page

    # ---- 卸载执行 ----
    def _on_uninstall(self):
        self._stack.setCurrentIndex(1)
        request_quit()  # 先请运行中的面板退出，避免文件占用
        self._report_progress(5, t('installer.progress.wait_exit'))
        time.sleep(1.0)
        try:
            uninstall(remove_user_data=self._del_data.isChecked(), progress=self._report_progress)
        except Exception as e:
            QMessageBox.critical(self, t('installer.uninstall_failed'), str(e))
            self._stack.setCurrentIndex(0)
            return
        self._stack.setCurrentIndex(2)