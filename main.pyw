# -*- coding: utf-8 -*-
"""Zviber 悬浮面板入口：单实例 + 桌面右键菜单 + 节假日联网更新/离线导入。
用法：pythonw main.pyw        启动并显示
      pythonw main.pyw --toggle   已运行则切换显隐（供桌面右键菜单调用）
      pythonw main.pyw --new-box / --toggle-boxes / --settings / --about / --quit
                                  桌面右键二级菜单项：已运行则 IPC 转发，未运行则启动后本地执行（--quit 除外）
      pythonw main.pyw --pick-folder   「新建文件夹格子」：本进程弹原生目录框，路径经 IPC 发回面板
自检：设置环境变量 ZVIBER_SHOT=<目录> 启动，自动导出两主题截图后退出。
"""
import faulthandler
import os
import re
import sys
import time
from datetime import date, datetime, timedelta


from PyQt5.QtCore import Qt, QTimer, QThread, QUrl, pyqtSignal, QCoreApplication
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QApplication, QFileDialog

import app as ui
import boxes as bx
import calendar_data as cd
import installer
import sysutil
from themes import THEME_ORDER

IPC_KEY = sysutil.IPC_KEY

# Qt5 在含非 ASCII 字符的安装路径下会把插件目录里的用户名算成 ??，导致
# "no Qt platform plugin could be initialized"；这里按真实路径手动补正。
QCoreApplication.addLibraryPath(
    os.path.join(os.path.dirname(__import__('PyQt5').__file__), 'Qt5', 'plugins'))

_worker = []   # 当前后台抓取线程：留引用防 GC，也用来判断是否已在抓


class _HolidayWorker(QThread):
    """后台抓节假日：只下载 + 解析，结果交回主线程合并（绝不跨线程改 store）。
    groups 是若干组候选 (名称, URL)：每组按顺序试，取第一个成功的。
    save_dir 非空时（导入窗「下载并导入」），抓到的原始 JSON 存一份到该目录。"""

    done = pyqtSignal(object)   # {'off': {}, 'work': set(), 'hit': [源名], 'err': '失败原因'}

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
                         on_finish=None, save_dir=None):
    """后台联网更新。manual=False 完全静默（自动更新用）；manual=True 把结果写进调试日志，
    fallback_url 非空且全部失败时顺手用浏览器打开它兜底。
    on_finish 非空时在结束时（无论成败）回调一次，给按钮恢复用；已在跑则附到当前那次上。
    save_dir 非空时把抓到的原始 JSON 存到该目录（导入窗「下载并导入」用）。"""
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

    def _merge_and_report(res):
        n = hstore.merge(res['off'], res['work']) if (res['off'] or res['work']) else 0
        if n:
            panel.refresh_holidays()
        if not manual:
            return
        if n:
            ui._dbg('节假日更新成功：%s 共 %d 条' % ('、'.join(res['hit']), n))
        else:
            msg = '联网更新失败：%s' % res['err'][:220]
            if fallback_url:
                QDesktopServices.openUrl(QUrl(fallback_url))
                msg += '（已用浏览器打开，可另存为文件后用「选择文件导入」）'
            ui._dbg(msg)

    w.done.connect(on_done)
    w.start()
    return True


# 命令行参数 → IPC 消息（桌面右键二级菜单的七个项；--pick-folder 不查此表，
# 由独立进程弹完目录框后把路径包进 b'folder:' 消息发回）
IPC_ACTIONS = {
    '--toggle': b'toggle',
    '--new-box': b'new-box',
    '--toggle-boxes': b'toggle-boxes',
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
    import ctypes
    ctypes.windll.ole32.CoInitializeEx(None, 0)   # COINIT_APARTMENTTHREADED
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setQuitOnLastWindowClosed(False)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName('ZviberPanel')

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
    panel = ui.FloatingPanel(cfg, hstore, tstore)
    # 桌面格子：截图自检模式不创建，避免格子入镜干扰面板截图
    boxmgr = None
    if not os.environ.get('ZVIBER_SHOT') and not os.environ.get('ZVIBER_GRABSCREEN'):
        boxmgr = bx.BoxManager(data_dir, panel)
        icon = None  # 源码运行的右键菜单图标；frozen 用 exe 自带图标，不用生成
        if not getattr(sys, 'frozen', False):
            icon = os.path.join(data_dir, 'icon.ico')
            if not os.path.exists(icon):
                ui.make_icon().pixmap(64, 64).save(icon, 'ICO')
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
    qapp.aboutToQuit.connect(_quit_cleanup)

    # 节假日数据：设置窗「联网更新」与导入窗里各源的「下载并导入」都走同一条后台通道
    def fetch_holidays(on_finish=None):
        return start_holiday_update(hstore, cfg, panel, _holiday_groups(), on_finish=on_finish)

    def download_source(name, url, on_finish=None):
        return start_holiday_update(hstore, cfg, panel, [[(name, url)]], fallback_url=url,
                                    on_finish=on_finish, save_dir=sysutil.download_dir())

    def auto_update():
        if _auto_update_due(cfg):
            start_holiday_update(hstore, cfg, panel, _holiday_groups(), manual=False)

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
                                boxmgr)
        settings_dlg[:] = [dlg]
        dlg.show()

    panel.settingsRequested.connect(open_settings)

    # 桌面右键二级菜单的动作分发表
    actions = {b'toggle': panel.toggle_visible, b'quit': qapp.quit,
               b'settings': open_settings,
               b'about': lambda: ui.AboutDialog(panel).exec_()}
    if boxmgr:
        actions[b'new-box'] = boxmgr.new_blank
        actions[b'folder:'] = boxmgr.new_folder
        actions[b'toggle-boxes'] = boxmgr.toggle_visible
    server.newConnection.connect(lambda: _on_ipc(server, actions))
    if cli_arg and cli_arg != '--toggle':
        fn = actions.get(IPC_ACTIONS[cli_arg])
        if fn:  # 无运行实例时本地执行（截图自检没有格子，--new-box 等静默跳过）
            QTimer.singleShot(0, fn)

    if os.environ.get('ZVIBER_GRABSCREEN'):
        panel.place_initial()
        panel.show()
        QTimer.singleShot(1500, lambda: _grab_screen(panel, qapp))
        return qapp.exec_()
    shot_dir = os.environ.get('ZVIBER_SHOT')
    if shot_dir:
        QTimer.singleShot(600, lambda: _self_shot(shot_dir, panel, cfg, tstore, qapp))
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
    return qapp.exec_()


def _grab_screen(panel, qapp):
    """验证用：截取真实屏幕面板区域（含合成效果）后退出。"""
    g = panel.frameGeometry()
    pm = QApplication.primaryScreen().grabWindow(0, g.x() - 20, g.y() - 20,
                                                 g.width() + 40, g.height() + 40)
    pm.save(os.environ.get('ZVIBER_GRABSCREEN'))
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
        except Exception as e:
            ui._dbg('节假日导入失败：%s' % e)

    _import_dlg[:] = [ui.HolidayImportDialog(panel, on_download, pick)]
    _import_dlg[0].show()


def _self_shot(shot_dir, panel, cfg, tstore, qapp):
    """验证用：注入示例待办，导出两主题 × 日历/待办/双栏 截图后还原并退出。"""
    os.makedirs(shot_dir, exist_ok=True)
    backup = list(tstore.items)
    today = date.today()
    tstore.items = [
        {'id': 1, 'text': '整理 Q3 复盘文档', 'done': False, 'due': (today - timedelta(days=2)).isoformat()},
        {'id': 2, 'text': '给妈妈回电话', 'done': False, 'due': today.isoformat()},
        {'id': 3, 'text': '国庆出游订酒店', 'done': False, 'due': (today + timedelta(days=2)).isoformat()},
        {'id': 4, 'text': '缴纳水电费', 'done': True},
        {'id': 5, 'text': '周报已提交', 'done': True},
    ]
    panel.todo.rebuild()
    panel.set_dual(False, save=False)
    panel.set_tab(0, save=False)
    panel.show()
    jobs = []
    for key in THEME_ORDER:
        jobs.append((key, 'cal'))
        jobs.append((key, 'todo'))
        jobs.append((key, 'dual'))
    state = {'i': 0}

    def finish():
        tstore.items = backup
        tstore.save()
        qapp.quit()

    def step():
        if state['i'] >= len(jobs):
            finish()
            return
        key, view = jobs[state['i']]
        panel.apply_theme(key, save=False)
        if view == 'dual':
            panel.set_dual(True, save=False)
        else:
            panel.set_dual(False, save=False)
            panel.set_tab(0 if view == 'cal' else 1, save=False)
        QApplication.processEvents()
        state['i'] += 1
        QTimer.singleShot(250, lambda: _grab(shot_dir, key, view, step))

    def _grab(d, key, view, nxt):
        panel.grab().save(os.path.join(d, '%s_%s.png' % (key, view)))
        nxt()

    step()


if __name__ == '__main__':
    sys.exit(main())




