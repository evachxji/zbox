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
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction, QActionGroup, QFileDialog

import app as ui
import sysutil
from themes import THEMES, THEME_ORDER

IPC_KEY = 'zviber-panel-v1'


def notify_existing():
    s = QLocalSocket()
    s.connectToServer(IPC_KEY)
    if s.waitForConnected(600):
        s.write(b'toggle')
        s.flush()
        s.waitForBytesWritten(600)
        return True
    return False


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setQuitOnLastWindowClosed(False)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName('ZviberPanel')

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
            # 每次右键重建菜单，保证勾选状态最新
            build_menu(panel, hstore, cfg, tray, qapp, True).exec_(QCursor.pos())

    tray.activated.connect(on_tray)
    tray.show()
    def open_settings():
        ui.SettingsDialog(panel,
                          lambda: _fetch_holidays(tray, hstore, panel),
                          lambda: _import_holidays(tray, hstore, panel),
                          lambda: _reset_holidays(tray, hstore, panel)).exec_()

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
    if sock:
        sock.waitForReadyRead(300)
        sock.deleteLater()
    panel.toggle_visible()


def build_menu(panel, hstore, cfg, tray, qapp, with_visibility):
    """托盘右键菜单。"""
    menu = QMenu()
    if with_visibility:
        menu.addAction('显示 / 隐藏', panel.toggle_visible)
        menu.addSeparator()

    tm = menu.addMenu('主题')
    g = QActionGroup(tm)
    for key in THEME_ORDER:
        a = QAction(THEMES[key]['name'], tm, checkable=True)
        a.setChecked(key == panel._theme)
        a.triggered.connect(lambda _=False, k=key: panel.apply_theme(k))
        g.addAction(a)
        tm.addAction(a)

    dual = QAction('双栏显示（日历 + 待办）', menu, checkable=True)
    dual.setChecked(panel._dual)
    dual.triggered.connect(lambda on: panel.set_dual(on))
    menu.addAction(dual)

    tm2 = menu.addMenu('下班倒计时')
    for key, label, presets in (('off_noon', '午休时间', ['11:30', '12:00', '12:30', '13:00']),
                                ('off_evening', '下班时间', ['17:00', '17:30', '18:00', '18:30', '19:00'])):
        sub = tm2.addMenu(label)
        g2 = QActionGroup(sub)
        cur = cfg.data.get(key)
        for p in presets:
            a = QAction(p, sub, checkable=True)
            a.setChecked(p == cur)
            a.triggered.connect(lambda _=False, k=key, v=p: cfg.set(k, v))
            g2.addAction(a)
            sub.addAction(a)

    hm = menu.addMenu('节假日数据')
    hm.addAction('联网更新（今年与明年）', lambda: _fetch_holidays(tray, hstore, panel))
    hm.addAction('从 JSON 文件导入…', lambda: _import_holidays(tray, hstore, panel))
    hm.addAction('恢复内置数据', lambda: _reset_holidays(tray, hstore, panel))

    auto = QAction('开机自动启动', menu, checkable=True)
    auto.setChecked(bool(sysutil.autostart_get()))
    auto.triggered.connect(lambda on: sysutil.autostart_set() if on else sysutil.autostart_remove())
    menu.addAction(auto)
    menu.addSeparator()
    menu.addAction('退出', qapp.quit)
    return menu

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


def _import_holidays(tray, hstore, panel):
    path, _ = QFileDialog.getOpenFileName(None, '选择从 jiejiariapi.com 下载的节假日 JSON', '',
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


def _reset_holidays(tray, hstore, panel):
    hstore.reset()
    panel.refresh_holidays()
    tray.showMessage('节假日数据', '已恢复为内置官方数据', QSystemTrayIcon.Information, 2500)


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




