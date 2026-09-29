# -*- coding: utf-8 -*-
"""源码方式的系统集成：开机自启（HKCU，免管理员）。
桌面右键菜单只由 exe 安装包写入（installer.py）——源码运行不写菜单，未安装时也不会残留。
用法：python install.py           安装
      python install.py --remove  卸载
"""
import sys

import sysutil


def install():
    sysutil.autostart_set()
    print('[OK] 开机自启已开启：%s' % sysutil.autostart_get())


def remove():
    sysutil.context_menu_remove()  # 顺带清理旧版本 install.py 留下的右键菜单
    sysutil.autostart_remove()
    print('[OK] 已移除桌面右键菜单与开机自启')


if __name__ == '__main__':
    if '--remove' in sys.argv:
        remove()
    else:
        install()
