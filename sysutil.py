# -*- coding: utf-8 -*-
"""系统集成：开机自启 + 桌面右键菜单 + 应用列表卸载项。
默认写 HKCU（免管理员，Win7/10/11 通用）；all_users=True 写 HKLM（exe 安装向导「此计算机」选项，需管理员）。"""
import os
import sys
import winreg

from version import APP_VERSION

APP_NAME = 'ZviberPanel'
MENU_TITLE = 'zviber桌面日历'
IPC_KEY = 'zviber-panel-v1'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
SHELL_KEY = r'Software\Classes\Directory\Background\shell\ZviberPanel'
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\ZviberPanel'
PERSONALIZE_KEY = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'


def _root(all_users=False):
    return winreg.HKEY_LOCAL_MACHINE if all_users else winreg.HKEY_CURRENT_USER


def appdata_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    p = os.path.join(base, 'ZviberPanel')
    if not os.path.isdir(p):
        os.makedirs(p)
    return p


def download_dir():
    """「下载并导入」抓到的年份 JSON 统一存这里；导入窗的「打开下载目录」开的也是它。"""
    return os.path.join(appdata_dir(), 'downloads')


def launcher_cmd(toggle=False, exe=None):
    """冻结为 exe 时直接启动自身（exe 参数可指定安装后路径）；源码运行优先用 pythonw.exe 实现无窗口静默。"""
    if getattr(sys, 'frozen', False):
        cmd = '"%s"' % (exe or sys.executable)
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


def system_uses_light_theme():
    """Windows「应用模式」是否为浅色（设置 → 个性化 → 颜色）。Win7 没有这项 → 按深色处理。"""
    return _get(winreg.HKEY_CURRENT_USER, PERSONALIZE_KEY, 'AppsUseLightTheme') == 1


def autostart_get():
    # HKCU 优先，HKLM 兜底（为所有用户安装时自启在 HKLM）
    return _get(winreg.HKEY_CURRENT_USER, RUN_KEY, APP_NAME) or \
        _get(winreg.HKEY_LOCAL_MACHINE, RUN_KEY, APP_NAME)


def autostart_set(exe=None, all_users=False):
    with winreg.CreateKey(_root(all_users), RUN_KEY) as k:
        winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, launcher_cmd(exe=exe))


def autostart_remove():
    """清除自启（HKCU/HKLM 均尝试；HKLM 无管理员权限时静默跳过）。"""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, APP_NAME)
        except OSError:
            pass


def context_menu_install(icon_path=None, exe=None, all_users=False):
    with winreg.CreateKey(_root(all_users), SHELL_KEY) as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, MENU_TITLE)
        if icon_path and os.path.exists(icon_path):
            winreg.SetValueEx(k, 'Icon', 0, winreg.REG_SZ, icon_path)
    with winreg.CreateKey(_root(all_users), SHELL_KEY + r'\command') as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, launcher_cmd(toggle=True, exe=exe))


def context_menu_remove():
    """清除右键菜单（HKCU/HKLM 均尝试；HKLM 无管理员权限时静默跳过）。"""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for sub in (SHELL_KEY + r'\command', SHELL_KEY):
            try:
                winreg.DeleteKey(root, sub)
            except OSError:
                pass


def uninstall_reg_install(exe_path, all_users=False):
    """写入「设置→应用→安装的应用」卸载项。"""
    vals = [
        ('DisplayName', winreg.REG_SZ, 'Zviber 桌面日历'),
        ('DisplayVersion', winreg.REG_SZ, APP_VERSION),
        ('Publisher', winreg.REG_SZ, 'Zviber'),
        ('DisplayIcon', winreg.REG_SZ, exe_path),
        ('InstallLocation', winreg.REG_SZ, os.path.dirname(exe_path)),
        ('UninstallString', winreg.REG_SZ, '"%s" --uninstall' % exe_path),
        ('NoModify', winreg.REG_DWORD, 1),
        ('NoRepair', winreg.REG_DWORD, 1),
        ('EstimatedSize', winreg.REG_DWORD, os.path.getsize(exe_path) // 1024),
    ]
    with winreg.CreateKey(_root(all_users), UNINSTALL_KEY) as k:
        for name, vtype, val in vals:
            winreg.SetValueEx(k, name, 0, vtype, val)


def uninstall_reg_get(name, all_users=False):
    return _get(_root(all_users), UNINSTALL_KEY, name)


def uninstall_reg_remove():
    """清除卸载项（HKCU/HKLM 均尝试；HKLM 无管理员权限时静默跳过）。"""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            winreg.DeleteKey(root, UNINSTALL_KEY)
        except OSError:
            pass
