# -*- coding: utf-8 -*-
"""Zviber 悬浮面板入口：单实例 + 系统托盘 + 节假日联网更新/离线导入。
用法：pythonw main.pyw        启动并显示
      pythonw main.pyw --toggle   已运行则切换显隐（供桌面右键菜单调用）
自检：设置环境变量 ZVIBER_SHOT=<目录> 启动，自动导出两主题截图后退出。
"""
import os
import platform
import re
import sys
import time
from datetime import date, datetime, timedelta


from PyQt5.QtCore import Qt, QTimer, QThread, QUrl, pyqtSignal, QCoreApplication
from PyQt5.QtGui import QIcon, QCursor, QDesktopServices
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QFileDialog

import app as ui
import boxes as bx
import calendar_data as cd
import installer
import sysutil
import transfer
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


def start_holiday_update(tray, hstore, cfg, panel, groups, manual=True, fallback_url=None,
                         on_finish=None, save_dir=None):
    """后台联网更新。manual=False 完全静默（自动更新用）；manual=True 用托盘气泡报结果，
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
            tray.showMessage('节假日数据', '更新成功：%s 共 %d 条' % ('、'.join(res['hit']), n),
                             QSystemTrayIcon.Information, 3000)
        else:
            msg = '联网更新失败：\n%s' % res['err'][:220]
            if fallback_url:
                QDesktopServices.openUrl(QUrl(fallback_url))
                msg += '\n已用浏览器打开，可另存为文件后用「选择文件导入」'
            tray.showMessage('节假日数据', msg, QSystemTrayIcon.Warning, 6000)

    w.done.connect(on_done)
    w.start()
    return True


def notify_existing():
    s = QLocalSocket()
    s.connectToServer(IPC_KEY)
    if s.waitForConnected(600):
        s.write(b'toggle')
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


def main():
    sys.excepthook = _debug_excepthook
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setQuitOnLastWindowClosed(False)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName('ZviberPanel')

    installer.sync_context_menu()  # 右键菜单只属于已安装的程序，未安装时清掉残留
    if installer.maybe_install():
        return 0  # exe 安装包：安装/卸载/取消后退出

    if notify_existing():
        return 0  # 已有实例在运行，转发 toggle 后退出

    data_dir = sysutil.appdata_dir()
    cfg = ui.Config(os.path.join(data_dir, 'config.json'))
    hstore = cd.HolidayStore(os.path.join(data_dir, 'holidays.json'))
    tstore = ui.TodoStore(os.path.join(data_dir, 'todos.json'))

    # 局域网传输：指纹持久化在 config.json（同步进 cfg.data，防 cfg.save() 回写时丢键）；
    # 别名默认电脑名（传输页可改）。端口被占时注入 None，传输页降级为「不可用」空态
    fingerprint = transfer.load_or_create_fingerprint(cfg.path)
    cfg.data['transfer_fingerprint'] = fingerprint
    alias = cfg.transfer_alias or platform.node() or 'Zviber'
    device_info = transfer.DeviceInfo.local(alias, fingerprint)
    try:
        transfer_server = transfer.TransferServer(device_info)
    except Exception:
        transfer_server = None   # 端口 53327 被占用
    discovery = transfer.Discovery(device_info) if transfer_server is not None else None
    panel = ui.FloatingPanel(cfg, hstore, tstore, transfer_server, discovery, device_info)

    # 截图自检不起服务：避免网络发现/对端接入让截图不确定。
    # 记住启动状态：未 start 过的 server 不能 stop（socketserver.shutdown() 会死等）
    transfer_started = transfer_server is not None and not os.environ.get('ZVIBER_SHOT')
    if transfer_started:
        transfer_server.start()
        discovery.start()
    # 桌面格子：截图自检模式不创建，避免格子入镜干扰面板截图
    boxmgr = None
    if not os.environ.get('ZVIBER_SHOT') and not os.environ.get('ZVIBER_GRABSCREEN'):
        boxmgr = bx.BoxManager(data_dir, panel)

    # IPC 服务：接收 --toggle
    server = QLocalServer(qapp)
    QLocalServer.removeServer(IPC_KEY)
    server.listen(IPC_KEY)
    server.newConnection.connect(lambda: _on_ipc(server, panel))

    # 托盘
    tray = QSystemTrayIcon(ui.make_icon(), parent=qapp)
    tray.setToolTip('Zviber 悬浮面板')
    def _quit_cleanup():
        tray.hide()
        server.close()
        if boxmgr:
            boxmgr.shutdown()
    qapp.aboutToQuit.connect(_quit_cleanup)

    def on_tray(reason):
        if reason == QSystemTrayIcon.Trigger:
            panel.toggle_visible()
        elif reason == QSystemTrayIcon.Context:
            menu = QMenu()
            menu.addAction('显示 / 隐藏', panel.toggle_visible)
            if boxmgr:
                menu.addSeparator()
                menu.addAction('新建格子', boxmgr.new_blank)
                menu.addAction('新建文件夹格子', lambda: boxmgr.new_folder())
                menu.addAction('显示 / 隐藏格子', boxmgr.toggle_visible)
                menu.addSeparator()
            menu.addAction('设置', open_settings)
            menu.addAction('关于', lambda: ui.AboutDialog(panel).exec_())
            menu.addSeparator()
            menu.addAction('退出', qapp.quit)
            menu.exec_(QCursor.pos())

    tray.activated.connect(on_tray)
    tray.show()

    if transfer_server is None:
        tray.showMessage('Zviber', '传输服务启动失败：端口 53327 被占用',
                         QSystemTrayIcon.Warning, 5000)

    def _transfer_notify(title, msg):
        try:
            tray.showMessage(title, msg, QSystemTrayIcon.Information, 4000)
        except Exception:
            pass
    panel.transfer.notify.connect(_transfer_notify)

    def _stop_transfer():
        try:
            if transfer_started:
                discovery.stop()
                transfer_server.stop()
        except Exception:
            pass
    qapp.aboutToQuit.connect(_stop_transfer)

    # 节假日数据：设置窗「联网更新」与导入窗里各源的「下载并导入」都走同一条后台通道
    def fetch_holidays(on_finish=None):
        return start_holiday_update(tray, hstore, cfg, panel, _holiday_groups(), on_finish=on_finish)

    def download_source(name, url, on_finish=None):
        return start_holiday_update(tray, hstore, cfg, panel, [[(name, url)]], fallback_url=url,
                                    on_finish=on_finish, save_dir=sysutil.download_dir())

    def auto_update():
        if _auto_update_due(cfg):
            start_holiday_update(tray, hstore, cfg, panel, _holiday_groups(), manual=False)

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
                                lambda: _import_holidays(tray, hstore, panel, download_source),
                                boxmgr)
        settings_dlg[:] = [dlg]
        dlg.show()

    panel.settingsRequested.connect(open_settings)

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

def _on_ipc(server, panel):
    sock = server.nextPendingConnection()
    data = b''
    if sock:
        sock.waitForReadyRead(300)
        data = bytes(sock.readAll())
        sock.deleteLater()
    if data == b'quit':
        QApplication.instance().quit()  # 卸载程序请求退出
    else:
        panel.toggle_visible()


_import_dlg = []  # 引导窗口是非模态的，要留住引用


def _import_holidays(tray, hstore, panel, on_download):
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
            tray.showMessage('节假日数据', '导入成功，共 %d 条' % n, QSystemTrayIcon.Information, 3000)
        except Exception as e:
            tray.showMessage('节假日数据', '导入失败：%s' % e, QSystemTrayIcon.Warning, 4000)

    _import_dlg[:] = [ui.HolidayImportDialog(panel, on_download, pick)]
    _import_dlg[0].show()


def _self_shot(shot_dir, panel, cfg, tstore, qapp):
    """验证用：注入示例待办，导出两主题 × 日历/待办/传输/双栏 截图后还原并退出。"""
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
        jobs.append((key, 'transfer'))
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
            panel.set_tab({'cal': 0, 'todo': 1, 'transfer': 2}[view], save=False)
        QApplication.processEvents()
        state['i'] += 1
        QTimer.singleShot(250, lambda: _grab(shot_dir, key, view, step))

    def _grab(d, key, view, nxt):
        panel.grab().save(os.path.join(d, '%s_%s.png' % (key, view)))
        nxt()

    step()


if __name__ == '__main__':
    sys.exit(main())




