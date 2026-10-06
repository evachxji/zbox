# -*- coding: utf-8 -*-
"""Zbox 悬浮面板入口：单实例 + 桌面右键菜单 + 节假日联网更新/离线导入。
用法：pythonw main.pyw        启动并显示
      pythonw main.pyw --toggle   已运行则切换显隐（供桌面右键菜单调用）
      pythonw main.pyw --new-box / --settings / --about / --quit
                                  桌面右键二级菜单项：已运行则 IPC 转发，未运行则启动后本地执行（--quit 除外）
      pythonw main.pyw --pick-folder   「新建文件夹格子」：本进程弹原生目录框，路径经 IPC 发回面板
      pythonw main.pyw --add-folder <路径>   文件夹右键「添加到zbox桌面格子」：路径经 IPC 发回面板建格子
自检：设置环境变量 ZBOX_SHOT=<目录> 启动，自动导出两主题截图后退出。
"""
import ctypes
import faulthandler
import os
import platform
import re
import sys
import time
from datetime import date, datetime, timedelta


from PySide6.QtCore import Qt, QTimer, QThread, QUrl, Signal, QCoreApplication
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog

import app as ui
import boxes as bx
import calendar_data as cd
import installer
import screenshot as shotmod
import sysutil
import transfer

IPC_KEY = sysutil.IPC_KEY

# Qt5 曾在含非 ASCII 字符的安装路径下把插件目录里的用户名算成 ??，导致
# "no Qt platform plugin could be initialized"；Qt6 未复现但保留手动补正作防御。
QCoreApplication.addLibraryPath(
    os.path.join(os.path.dirname(__import__('PySide6').__file__), 'plugins'))

_worker = []   # 当前后台抓取线程：留引用防 GC，也用来判断是否已在抓


class _HolidayWorker(QThread):
    """后台抓节假日：只下载 + 解析，结果交回主线程合并（绝不跨线程改 store）。
    groups 是若干组候选 (名称, URL)：每组按顺序试，取第一个成功的。
    save_dir 非空时（导入窗「下载并导入」），抓到的原始 JSON 存一份到该目录。"""

    done = Signal(object)   # {'off': {}, 'work': set(), 'hit': [源名], 'err': '失败原因'}

    def __init__(self, groups, parent=None, save_dir=None):
        super(_HolidayWorker, self).__init__(parent)
        self.groups = groups
        self.save_dir = save_dir

    def run(self):
        off, work, hit, errs = {}, set(), [], []
        for group in self.groups:
            for name, url in group:
                try:
                    o, w = self._fetch(name, url)
                except Exception as e:
                    errs.append('%s：%s' % (name, e))
                    continue
                off.update(o)
                work |= w
                hit.append(name)
                break
        self.done.emit({'off': off, 'work': work, 'hit': hit, 'err': '；'.join(errs)})

    def _fetch(self, name, url):
        """有存档目录时抓原文、解析通过后再存（存失败不挡导入）；否则抓了直接解析。"""
        if not self.save_dir:
            return cd.fetch_url(url)
        text = cd.fetch_text(url)
        parsed = cd.parse_holiday_json(text)
        self._save_json(name, url, text)
        return parsed

    def _save_json(self, name, url, text):
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            m = re.search(r'20\d\d', url)   # URL 里抠年份做文件名；抠不到用时间戳
            tag = m.group(0) if m else datetime.now().strftime('%Y%m%d%H%M%S')
            with open(os.path.join(self.save_dir, '%s_%s.json' % (name, tag)), 'w',
                      encoding='utf-8') as f:
                f.write(text)
        except Exception:
            pass


def _holiday_groups():
    """两年 × 三个源：每年之内按 SOURCES 顺序试，两个年份都要拿到数据。"""
    y = date.today().year
    return [[(src['name'], src['url'] % year) for src in cd.SOURCES] for year in (y, y + 1)]


def _auto_update_due(cfg):
    """该不该静默更新：从没试过、上次尝试已是别的日子（每天第一次开程序），
    或距上次尝试已满 48 小时（程序长期不关）。记的是「尝试」时间，所以失败不会反复重试。"""
    try:
        ts = float(cfg.data.get('holiday_ts') or 0)
    except (TypeError, ValueError):
        return True   # 时间戳坏了：当作没试过，重试一次就会把它写成正常值
    if not ts:
        return True
    return datetime.fromtimestamp(ts).date() != date.today() or time.time() - ts >= 48 * 3600


def start_holiday_update(hstore, cfg, panel, groups, manual=True, fallback_url=None,
                         on_finish=None, save_dir=None, toast_win=None):
    """后台联网更新。manual=False 完全静默（自动更新用）；manual=True 结果经面板中央
    toast 反馈（细节仍写调试日志），fallback_url 非空且全部失败时顺手用浏览器打开它兜底。
    on_finish 非空时在结束时（无论成败）回调一次，给按钮恢复用；已在跑则附到当前那次上。
    save_dir 非空时把抓到的原始 JSON 存到该目录（导入窗「下载并导入」用）。
    toast_win 为手动结果的 toast 目标窗口（触发按钮所在窗口）；缺省或已关闭则回落面板。"""
    if _worker and _worker[0].isRunning():
        if on_finish:
            _worker[0].done.connect(lambda *_: on_finish())
        return False
    cfg.set('holiday_ts', time.time())
    w = _HolidayWorker(groups, save_dir=save_dir)
    _worker[:] = [w]

    def on_done(res):
        try:
            _merge_and_report(res)
        finally:
            if on_finish:
                on_finish()

    def show(text, **kw):
        win = toast_win
        try:
            if win is not None and not win.isVisible():
                win = None
        except RuntimeError:
            win = None
        ui.show_toast_on(win if win is not None else panel, text, **kw)

    def _merge_and_report(res):
        n = hstore.merge(res['off'], res['work']) if (res['off'] or res['work']) else 0
        if n:
            panel.refresh_holidays()
        if not manual:
            return
        if n:
            ui._dbg('节假日更新成功：%s 共 %d 条' % ('、'.join(res['hit']), n))
            show('节假日更新成功，共 %d 条' % n)
        else:
            ui._dbg('联网更新失败：%s' % res['err'][:220])
            if fallback_url:
                QDesktopServices.openUrl(QUrl(fallback_url))
                show('联网更新失败，已打开下载页，可另存后导入', ok=False, hold_ms=2600)
            else:
                show('联网更新失败，请检查网络后重试', ok=False, hold_ms=2200)

    w.done.connect(on_done)
    w.start()
    return True


# 命令行参数 → IPC 消息（桌面右键级联六项 + 全隐藏态单项；--pick-folder 不查此表，
# 由独立进程弹完目录框后把路径包进 b'folder:' 消息发回）
IPC_ACTIONS = {
    '--toggle': b'toggle',
    '--new-box': b'new-box',
    '--show-icons': b'show-icons',   # 全隐藏态桌面右键单项「显示桌面图标」
    '--settings': b'settings',
    '--about': b'about',
    '--quit': b'quit',
}


def notify_existing(msg=b'toggle'):
    """已有实例在运行则把动作（msg）转发过去，返回 True。"""
    s = QLocalSocket()
    s.connectToServer(IPC_KEY)
    if s.waitForConnected(600):
        s.write(msg)
        s.flush()
        s.waitForBytesWritten(600)
        return True
    return False


def _debug_excepthook(t, v, tb):
    """临时调试：pythonw 下槽函数异常无控制台可见，落盘到 debug_due.log。定位后移除。"""
    try:
        import traceback
        p = os.path.join(sysutil.appdata_dir(), 'debug_due.log')
        with open(p, 'a', encoding='utf-8') as f:
            f.write(''.join(traceback.format_exception(t, v, tb)))
    except Exception:
        pass


# faulthandler 的输出文件句柄要活到进程结束，放模块级
_crash_log = [None]


def main():
    sys.excepthook = _debug_excepthook
    shot_dir = os.environ.get('ZBOX_SHOT')
    if shot_dir:
        # 截图自检：冻结时间源（日历时钟/倒计时/「今天」高亮/待办日期 tag），
        # 让同机两次运行出图逐像素可比；必须在 FloatingPanel 构造之前冻结
        import selfshot
        selfshot.freeze_time()
    # 原生崩溃（Qt/C++ 层访问冲突直接杀进程）不经过 sys.excepthook，
    # faulthandler 能在崩溃瞬间把 Python 堆栈落盘
    try:
        _crash_log[0] = open(os.path.join(sysutil.appdata_dir(), 'crash_native.log'),
                             'a', encoding='utf-8')
        faulthandler.enable(_crash_log[0])
    except Exception:
        pass
    # Qt 默认把 GUI 线程的 COM 初始化为 MTA：原生壳对话框（IFileOpenDialog 等）在 MTA 下
    # 会抛 RPC_E_WRONG_THREAD（0x8001010e）致命错误（「新建文件夹格子」原生目录框闪退）。
    # 先初始化为 STA：Qt 之后再初始化只会拿到 S_FALSE，不再改变套间类型。
    # ⚠️ COINIT_APARTMENTTHREADED 是 **0x2**，不是 0（0 = COINIT_MULTITHREADED）——原来是 0，
    # 于是这里把 GUI 线程初始化成了 MTA，Qt 随后的 OleInitialize 必然返回 RPC_E_CHANGED_MODE
    # （run.cmd 启动时那句 `OleInitialize() failed: RPC_E_CHANGED_MODE`），而 OLE 没初始化
    # ⇒ **Qt 所有窗口的拖放目标都注册不上**（实测 RevokeDragDrop：MTA 下 DRAGDROP_E_NOTREGISTERED，
    # STA 下 S_OK）⇒ 往格子里拖任何文件都是红色禁止光标（用户报的 bug 1 真身）。
    ctypes.windll.ole32.CoInitializeEx(None, 0x2)   # COINIT_APARTMENTTHREADED
    # Qt6 高 DPI 恒开（Qt5 的 AA_EnableHighDpiScaling/AA_UseHighDpiPixmaps 已废弃）；
    # 取整策略对齐 Qt5.15 默认（Round）：非整数缩放比屏幕的布局与旧版一致
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.Round)
    QApplication.setQuitOnLastWindowClosed(False)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(sysutil.APP_NAME)
    # 通知归属独立应用身份：Windows 按进程/AUMID 缓存气泡图标，
    # 旧版「黄底日期」图标就是这么残留在通知里的；独立 AUMID 绕开旧缓存
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Zbox')
    except Exception:
        pass

    if installer.maybe_install():
        return 0  # --uninstall 卸载向导结束后退出（安装包是独立的 setup exe）

    if '--pick-folder' in sys.argv:
        # 「新建文件夹格子」的目录框放在独立进程里弹，而不是转发给面板开：
        # ① 面板全程不阻塞，选目录期间设置窗等照常可用；
        # ② 面板自身全是 Tool/挂带窗口且无活动窗口，原生框在面板进程里开不出可见窗口（实测隐形）。
        # 选中的路径经 IPC 发回面板建格子。
        path = QFileDialog.getExistingDirectory(None, '选择要映射的文件夹')
        if path:
            notify_existing(b'folder:' + os.path.normpath(path).encode('utf-8'))
        return 0

    if '--add-folder' in sys.argv:
        # 文件夹右键「添加到zbox桌面格子」：资源管理器经 %1 传入路径，直接包成
        # b'folder:' 消息发回面板（与 --pick-folder 同一条 IPC 通道，面板侧零改动）。
        # 菜单只在运行中注入，无实例 = 崩溃残留被点到，静默退出。
        # ⚠️ 必须在下方通用转发之前 return：--add-folder 不在 IPC_ACTIONS，
        # 落过去会被当成 b'toggle' 把运行中的面板显隐翻转。
        i = sys.argv.index('--add-folder')
        path = sys.argv[i + 1] if i + 1 < len(sys.argv) else ''
        path = path.rstrip('"')          # 防御 %1 尾部反斜杠吃掉闭合引号（"C:\" → C:"）
        if len(path) == 2 and path[1] == ':':
            path += '\\'                 # C:（C 盘当前目录，语义危险）→ C:\
        if path and os.path.isdir(path):
            notify_existing(b'folder:' + os.path.normpath(path).encode('utf-8'))
        return 0

    cli_arg = next((a for a in sys.argv[1:] if a in IPC_ACTIONS), None)
    if notify_existing(IPC_ACTIONS.get(cli_arg, b'toggle')):
        return 0  # 已有实例在运行，转发动作后退出
    if cli_arg == '--quit':
        return 0  # 没有运行中的实例可退出

    # 清旧安装的菜单残留。必须在 IPC 转发之后：源码模式没有安装记录，
    # 转发进程跑这里会把运行中面板刚注入的级联菜单当残留删掉（真实 bug）
    installer.sync_context_menu()

    data_dir = sysutil.appdata_dir()
    cfg = ui.Config(os.path.join(data_dir, 'config.json'))
    hstore = cd.HolidayStore(os.path.join(data_dir, 'holidays.json'))
    tstore = ui.TodoStore(os.path.join(data_dir, 'todos.json'))

    # 局域网传输：指纹持久化在 config.json（同步进 cfg.data，防 cfg.save() 回写时丢键）；
    # 别名默认电脑名（传输页可改）。传输功能默认关闭（cfg['transfer_enabled']），
    # 服务生命周期由传输页自持——用户在传输页点「启用传输」或设置窗勾选后才监听
    # 端口（Windows 防火墙授权提示也在那一刻才弹），端口被占时传输页给「不可用」提示
    fingerprint = transfer.load_or_create_fingerprint(cfg.path)
    cfg.data['transfer_fingerprint'] = fingerprint
    alias = cfg.transfer_alias or platform.node() or 'Zbox'
    device_info = transfer.DeviceInfo.local(alias, fingerprint)
    # 截图自检不起服务（避免网络发现/对端接入让截图不确定），传输页按功能态渲染
    panel = ui.FloatingPanel(cfg, hstore, tstore, device_info,
                             transfer_autostart=not os.environ.get('ZBOX_SHOT'))
    # 桌面格子：截图自检模式不创建，避免格子入镜干扰面板截图
    boxmgr = None
    if not os.environ.get('ZBOX_SHOT') and not os.environ.get('ZBOX_GRABSCREEN'):
        boxmgr = bx.BoxManager(data_dir, panel)
        icon = None  # 源码运行的右键菜单图标；frozen 用 exe 自带图标，不用生成
        if not getattr(sys, 'frozen', False):
            icon = os.path.join(data_dir, 'icon.ico')
            if not os.path.exists(icon):
                ui.make_icon().pixmap(64, 64).save(icon, 'ICO')
        boxmgr.menu_icon = icon   # 全隐藏态/恢复时改写右键菜单也要用同一个图标
        sysutil.context_menu_set_running(True, icon_path=icon)  # 桌面右键切级联形态

    # IPC 服务：桌面右键二级菜单 / 重复启动时把动作转发进来（actions 定义后才挂连接）
    server = QLocalServer(qapp)
    QLocalServer.removeServer(IPC_KEY)
    server.listen(IPC_KEY)

    # 无系统托盘图标：显隐/设置/退出等入口全在桌面右键菜单（运行中注入级联菜单）
    def _quit_cleanup():
        server.close()
        if boxmgr:
            boxmgr.shutdown()
            sysutil.context_menu_set_running(False)  # 桌面右键切回直链「单击启动」
        if hotkey:
            hotkey.shutdown()
    qapp.aboutToQuit.connect(_quit_cleanup)

    # 截图全局热键（配置为空 = 不启用）；设置窗修改后走 hotkey.apply 即时重注册
    hotkey = None
    if not shot_dir:   # 自检模式不注册全局热键（也不读用户的热键配置）
        hotkey = shotmod.HotkeyManager(qapp, lambda: shotmod.start_session(cfg))
        hotkey.apply(cfg.data.get('shot_hotkey'))

    # 无系统托盘，分支的托盘气泡通道整体不进：
    # ① 传输服务起不来（端口被占）——传输页门禁层会给「不可用」提示，无需另提示；
    # ② 收到文件请求——唤起面板切到传输 tab（接收确认卡片就弹在那里，不唤起用户
    #   根本看不到，会拖到对端 180s 超时）；「传输完成」等纯通知在传输页记录区可见，不打扰
    def _transfer_notify(title, msg):
        if title != '收到文件':
            return
        try:
            panel.set_tab(2, save=False)   # tabs：日历 0 / 待办 1 / 传输 2
            panel.show()
            panel.raise_()
            panel.activateWindow()
        except Exception:
            pass
    panel.transfer.notify.connect(_transfer_notify)

    def _stop_transfer():
        try:
            panel.transfer.shutdown_service()   # 只停真正 start 过的服务
        except Exception:
            pass
    qapp.aboutToQuit.connect(_stop_transfer)

    # 节假日数据：设置窗「联网更新」与导入窗里各源的「下载并导入」都走同一条后台通道
    def fetch_holidays(on_finish=None, toast_win=None):
        return start_holiday_update(hstore, cfg, panel, _holiday_groups(),
                                    on_finish=on_finish, toast_win=toast_win)

    def download_source(name, url, on_finish=None, toast_win=None):
        return start_holiday_update(hstore, cfg, panel, [[(name, url)]], fallback_url=url,
                                    on_finish=on_finish, save_dir=sysutil.download_dir(),
                                    toast_win=toast_win)

    def auto_update():
        if _auto_update_due(cfg):
            start_holiday_update(hstore, cfg, panel, _holiday_groups(), manual=False)

    if not shot_dir:   # 自检模式不触网：自动更新会 cfg.save() 把冻结的内存配置写盘
        auto_timer = QTimer(qapp)
        auto_timer.timeout.connect(auto_update)
        auto_timer.start(30 * 60 * 1000)      # 每半小时看一次到没到点
        QTimer.singleShot(5000, auto_update)  # 启动后先看一次：每天第一次开程序时更新

    settings_dlg = []  # 非模态：留住引用，且已开着就不再叠一个
    def open_settings():
        if settings_dlg and settings_dlg[0].isVisible():
            settings_dlg[0].raise_()
            settings_dlg[0].activateWindow()
            return
        dlg = ui.SettingsDialog(panel, fetch_holidays,
                                lambda: _import_holidays(hstore, panel, download_source),
                                boxmgr, hotkey.apply if hotkey else None)
        settings_dlg[:] = [dlg]
        dlg.show()

    panel.settingsRequested.connect(open_settings)

    # 桌面右键二级菜单的动作分发表
    actions = {b'toggle': panel.toggle_visible, b'quit': qapp.quit,
               b'settings': open_settings,
               b'about': lambda: ui.AboutDialog(panel).exec()}
    if boxmgr:
        actions[b'new-box'] = boxmgr.new_blank
        actions[b'show-icons'] = boxmgr.show_all
        actions[b'folder:'] = boxmgr.new_folder
    server.newConnection.connect(lambda: _on_ipc(server, actions))
    if cli_arg and cli_arg != '--toggle':
        fn = actions.get(IPC_ACTIONS[cli_arg])
        if fn:  # 无运行实例时本地执行（截图自检没有格子，--new-box 等静默跳过）
            QTimer.singleShot(0, fn)

    if os.environ.get('ZBOX_GRABSCREEN'):
        panel.place_initial()
        panel.show()
        QTimer.singleShot(1500, lambda: _grab_screen(panel, qapp))
        return qapp.exec()
    if shot_dir:
        QTimer.singleShot(600, lambda: selfshot.run(shot_dir, panel, cfg, tstore, qapp))
    else:
        panel.place_initial()
        ui._dbg('main: after place_initial pos=(%d,%d) size=(%d,%d) pinned=%s' % (
            panel.x(), panel.y(), panel.width(), panel.height(), panel._desk_pinned))
        if '--toggle' in sys.argv and panel.isVisible():
            panel.hide()
        else:
            panel.show()
        ui._dbg('main: after show visible=%s pos=(%d,%d) size=(%d,%d)' % (
            panel.isVisible(), panel.x(), panel.y(), panel.width(), panel.height()))
    return qapp.exec()


def _grab_screen(panel, qapp):
    """验证用：截取真实屏幕面板区域（含合成效果）后退出。"""
    g = panel.frameGeometry()
    pm = QApplication.primaryScreen().grabWindow(0, g.x() - 20, g.y() - 20,
                                                 g.width() + 40, g.height() + 40)
    pm.save(os.environ.get('ZBOX_GRABSCREEN'))
    qapp.quit()

def _on_ipc(server, actions):
    sock = server.nextPendingConnection()
    data = b''
    if sock:
        sock.waitForReadyRead(300)
        data = bytes(sock.readAll())
        sock.deleteLater()
    if data.startswith(b'folder:'):   # --pick-folder 独立进程选完目录回传的路径
        fn = actions.get(b'folder:')
        if fn:
            fn(data[7:].decode('utf-8'))
        return
    fn = actions.get(data)
    if fn:
        fn()


_import_dlg = []  # 引导窗口是非模态的，要留住引用


def _import_holidays(hstore, panel, on_download):
    """先弹引导窗口（三个数据源各一行 URL，可点「下载并导入」），
    也可以自己另存文件后走「选择文件导入」。"""
    def pick():
        path, _ = QFileDialog.getOpenFileName(None, '选择节假日 JSON（数据源页面另存的文件）', '',
                                              'JSON 文件 (*.json)')
        if not path:
            return
        try:
            n = hstore.import_file(path)
            panel.refresh_holidays()
            ui._dbg('节假日导入成功，共 %d 条' % n)
            _pick_toast('节假日导入成功，共 %d 条' % n)
        except Exception as e:
            ui._dbg('节假日导入失败：%s' % e)
            _pick_toast('节假日导入失败：文件格式无法识别', ok=False)

    def _pick_toast(text, **kw):
        win = None
        try:
            if _import_dlg and _import_dlg[0].isVisible():
                win = _import_dlg[0]
        except RuntimeError:
            win = None
        ui.show_toast_on(win if win is not None else panel, text, **kw)

    _import_dlg[:] = [ui.HolidayImportDialog(panel, on_download, pick)]
    _import_dlg[0].show()



if __name__ == '__main__':
    sys.exit(main())




