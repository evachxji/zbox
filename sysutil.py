# -*- coding: utf-8 -*-
"""系统集成：开机自启 + 桌面右键菜单（HKCU，无需管理员，Win7/10/11 通用）。"""
import os
import sys
import winreg

APP_NAME = 'ZviberPanel'
MENU_TITLE = '悬浮日历待办'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
SHELL_KEY = r'Software\Classes\Directory\Background\shell\ZviberPanel'


def appdata_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    p = os.path.join(base, 'ZviberPanel')
    if not os.path.isdir(p):
        os.makedirs(p)
    return p


def launcher_cmd(toggle=False):
    """冻结为 exe 时直接启动自身；源码运行优先用 pythonw.exe 实现无窗口静默。"""
    if getattr(sys, 'frozen', False):
        cmd = '"%s"' % sys.executable
    else:
        exe = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        if not os.path.exists(exe):
            exe = sys.executable
        script = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main.pyw'))
        cmd = '"%s" "%s"' % (exe, script)
    return cmd + (' --toggle' if toggle else '')


def _get(root, path, name):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def autostart_get():
    return _get(winreg.HKEY_CURRENT_USER, RUN_KEY, APP_NAME)


def autostart_set():
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, launcher_cmd())


def autostart_remove():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, APP_NAME)
    except OSError:
        pass


def context_menu_install(icon_path=None):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SHELL_KEY) as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, MENU_TITLE)
        if icon_path and os.path.exists(icon_path):
            winreg.SetValueEx(k, 'Icon', 0, winreg.REG_SZ, icon_path)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SHELL_KEY + r'\command') as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, launcher_cmd(toggle=True))


def context_menu_remove():
    for sub in (SHELL_KEY + r'\command', SHELL_KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
        except OSError:
            pass
