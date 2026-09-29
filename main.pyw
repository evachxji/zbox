# -*- coding: utf-8 -*-
"""Zviber 悬浮面板入口：单实例 + 系统托盘 + 节假日联网更新/离线导入。
用法：pythonw main.pyw        启动并显示
      pythonw main.pyw --toggle   已运行则切换显隐（供桌面右键菜单调用）
自检：设置环境变量 ZVIBER_SHOT=<目录> 启动，自动导出两主题截图后退出。
"""
import os
import sys
from datetime import date, timedelta


from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon, QCursor
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QFileDialog

import app as ui
import installer
import sysutil
from themes import THEME_ORDER

IPC_KEY = sysutil.IPC_KEY


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
    import calendar_data as cd
    hstore = cd.HolidayStore(os.path.join(data_dir, 'holidays.json'))
    tstore = ui.TodoStore(os.path.join(data_dir, 'todos.json'))
    panel = ui.FloatingPanel(cfg, hstore, tstore)

    # IPC 服务：接收 --toggle
    server = QLocalServer(qapp)
    QLocalServer.removeServer(IPC_KEY)
    server.listen(IPC_KEY)
    server.newConnection.connect(lambda: _on_ipc(server, panel))

    # 托盘
    tray = QSystemTrayIcon(ui.make_icon(), parent=qapp)
    tray.setToolTip('Zviber 悬浮面板')
    qapp.aboutToQuit.connect(lambda: (tray.hide(), server.close()))

    def on_tray(reason):
        if reason == QSystemTrayIcon.Trigger:
            panel.toggle_visible()
        elif reason == QSystemTrayIcon.Context:
            menu = QMenu()
            menu.addAction('显示 / 隐藏', panel.toggle_visible)
            menu.addAction('设置', open_settings)
            menu.addSeparator()
            if installer.is_installed():
                menu.addAction('卸载 Zviber', lambda: _uninstall(qapp))
            menu.addAction('退出', qapp.quit)
            menu.exec_(QCursor.pos())

    tray.activated.connect(on_tray)
    tray.show()
    settings_dlg = []  # 非模态：留住引用，且已开着就不再叠一个
    def open_settings():
        if settings_dlg and settings_dlg[0].isVisible():
            settings_dlg[0].raise_()
            settings_dlg[0].activateWindow()
            return
        dlg = ui.SettingsDialog(panel,
                                lambda: _fetch_holidays(tray, hstore, panel),
                                lambda: _import_holidays(tray, hstore, panel))
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
        if '--toggle' in sys.argv and panel.isVisible():
            panel.hide()
        else:
            panel.show()
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


def _uninstall(qapp):
    from PyQt5.QtWidgets import QMessageBox
    r = QMessageBox.question(None, '卸载 Zviber',
                             '将移除右键菜单、开机自启并删除程序文件，\n'
                             '待办与配置数据（%APPDATA%\\ZviberPanel）保留。确定卸载？')
    if r == QMessageBox.Yes:
        if installer.is_all_users_install() and not installer.is_admin():
            installer.relaunch_elevated(['--uninstall'])  # HKLM 清理需管理员权限
        else:
            installer.uninstall()
        qapp.quit()


def _fetch_holidays(tray, hstore, panel):
    from PyQt5.QtWidgets import QApplication
    try:
        y = date.today().year
        n = hstore.fetch_year(y) + hstore.fetch_year(y + 1)
        panel.refresh_holidays()
        tray.showMessage('节假日数据', '联网更新成功，共导入 %d 条（%d/%d 年）' % (n, y, y + 1),
                         QSystemTrayIcon.Information, 3000)
    except Exception as e:
        tray.showMessage('节假日数据', '联网更新失败：%s\n可使用「从 JSON 文件导入」' % e,
                         QSystemTrayIcon.Warning, 4000)


_import_dlg = []  # 引导窗口是非模态的，要留住引用


def _import_holidays(tray, hstore, panel):
    """先弹引导窗口说明去哪下载，用户选定文件后再解析导入。"""
    def pick():
        path, _ = QFileDialog.getOpenFileName(None, '选择节假日 JSON（数据源页面另存的文件）', '',
                                              'JSON 文件 (*.json)')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                n = hstore.import_api_json(f.read())
            panel.refresh_holidays()
            tray.showMessage('节假日数据', '导入成功，共 %d 条' % n, QSystemTrayIcon.Information, 3000)
        except Exception as e:
            tray.showMessage('节假日数据', '导入失败：%s' % e, QSystemTrayIcon.Warning, 4000)

    _import_dlg[:] = [ui.HolidayImportDialog(panel, pick)]
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




