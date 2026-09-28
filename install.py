# -*- coding: utf-8 -*-
"""安装/卸载 Zviber 悬浮面板：桌面右键菜单 + 开机自启（HKCU，免管理员）。
用法：python install.py           安装
      python install.py --remove  卸载
"""
import os
import sys

import sysutil


def gen_icon(path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt5.QtWidgets import QApplication
    qapp = QApplication([])
    try:
        import app as ui
        ok = ui.make_icon().pixmap(64, 64).save(path, 'ICO')
    finally:
        qapp.quit()
    return ok


def install():
    icon = os.path.join(sysutil.appdata_dir(), 'icon.ico')
    icon_path = icon if gen_icon(icon) else None
    sysutil.context_menu_install(icon_path)
    sysutil.autostart_set()
    print('[OK] 桌面右键菜单已添加：%s' % sysutil.MENU_TITLE)
    print('[OK] 开机自启已开启：%s' % sysutil.autostart_get())
    print('[OK] 菜单命令：%s' % sysutil.launcher_cmd(toggle=True))
    if icon_path:
        print('[OK] 菜单图标：%s' % icon_path)
    else:
        print('[--] 图标生成失败，右键菜单将无图标（不影响功能）')


def remove():
    sysutil.context_menu_remove()
    sysutil.autostart_remove()
    print('[OK] 已移除桌面右键菜单与开机自启')


if __name__ == '__main__':
    if '--remove' in sys.argv:
        remove()
    else:
        install()
