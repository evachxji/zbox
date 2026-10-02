# -*- coding: utf-8 -*-
"""系统集成：开机自启 + 桌面/文件夹右键菜单 + 应用列表卸载项。
默认写 HKCU（免管理员，Win7/10/11 通用）；all_users=True 写 HKLM（exe 安装向导「此计算机」选项，需管理员）。"""
import os
import shutil
import sys
import winreg

from version import APP_VERSION

APP_NAME = 'zviber'
MENU_TITLE = 'zviber桌面格子'

# 桌面右键二级菜单项：(注册表子键名, 显示文字, exe 命令行参数)
# 子键名的字母序就是菜单顺序，故带 A_/B_… 前缀
MENU_ITEMS = [
    ('A_NewBox', '新建格子', '--new-box'),
    ('B_NewFolderBox', '新建文件夹格子', '--pick-folder'),
    ('C_Toggle', '显示 / 隐藏卡片', '--toggle'),
    ('D_Settings', '设置', '--settings'),
    ('E_About', '关于', '--about'),
    ('F_Quit', '退出', '--quit'),
]
# 2026-10 改版前的一代子键名（当时七项、前缀不同）：整树删除时两代都要算，
# 否则改名后旧键清不掉，右键菜单新旧并存
MENU_SUBKEYS_OLD = ['A_Toggle', 'B_NewBox', 'C_NewFolderBox', 'D_ToggleBoxes',
                    'E_Settings', 'F_About', 'G_Quit']
IPC_KEY = 'zviber-panel-v2'   # 换名字时一并换版本号：旧版（-v1）与新版本互不串话
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
# 右键菜单键相对 HKCR 的路径；ExtendedSubCommandsKey 要的就是这段（不带 Software\Classes\）
SHELL_SUBKEY = r'Directory\Background\shell\zviber'
SHELL_KEY = r'Software\Classes\\' + SHELL_SUBKEY
# 文件夹（Directory）右键「添加到zviber桌面格子」静态动词：仅运行中注入，随面板启停写删
FOLDER_MENU_TEXT = '添加到zviber桌面格子'
FOLDER_SHELL_KEY = r'Software\Classes\Directory\shell\zviber'
LEGACY_SHELL_KEY = r'Software\Classes\Directory\Background\shell\ZviberPanel'  # 旧名残留，安装/退出时清掉
COMMANDSTORE_KEY = r'Software\Microsoft\Windows\CurrentVersion\Explorer\CommandStore\shell'  # 只为清理旧版残留
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\zviber'
LEGACY_UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\ZviberPanel'
PERSONALIZE_KEY = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'


def _root(all_users=False):
    return winreg.HKEY_LOCAL_MACHINE if all_users else winreg.HKEY_CURRENT_USER


def appdata_dir():
    """运行时数据目录 %APPDATA%\\zviber（配置 / 待办 / 节假日 / 格子 / 图标）。
    旧版目录名是 ZviberPanel，首次运行时整体改名搬过来，老用户的待办与格子不会丢。"""
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    p = os.path.join(base, APP_NAME)
    _migrate_appdata(base, p)
    if not os.path.isdir(p):
        os.makedirs(p)
    return p


def _migrate_appdata(base, new_dir):
    """一次性把 %APPDATA%\\ZviberPanel 改名成 %APPDATA%\\zviber。

    实测坑：面板正在运行（或资源管理器缓存着 icon.ico）时整个目录 rename 会失败，
    所以三级回退——① 整目录改名；② 逐文件搬到新目录（同名文件以新目录为准，不覆盖）；
    ③ 搬剩的（被占用的活文件）留着不动，下次启动再搬。全部搬完才删旧目录。"""
    old = os.path.join(base, 'ZviberPanel')
    if not os.path.isdir(old):
        return
    if not os.path.isdir(new_dir):
        try:
            os.rename(old, new_dir)
            return
        except OSError:
            try:
                os.makedirs(new_dir)
            except OSError:
                return
    _merge_tree(old, new_dir)
    try:
        os.rmdir(old)      # 只为「空目录残留」清场；非空会抛错，放着下次再搬
    except OSError:
        pass


def _merge_tree(old, new_dir):
    """把 old 里的文件按目录结构搬到 new_dir：同名已存在就跳过（新目录是权威），
    被占用的单个文件跳过、不打断其余搬运。"""
    for root, _dirs, names in os.walk(old, topdown=False):
        rel = os.path.relpath(root, old)
        dst_dir = new_dir if rel == '.' else os.path.join(new_dir, rel)
        for n in names:
            src = os.path.join(root, n)
            dst = os.path.join(dst_dir, n)
            if os.path.exists(dst):
                continue
            try:
                if not os.path.isdir(dst_dir):
                    os.makedirs(dst_dir)
                os.rename(src, dst)
            except OSError:
                try:
                    shutil.copy2(src, dst)
                    os.remove(src)
                except OSError:
                    pass
        if rel != '.':
            try:
                os.rmdir(root)
            except OSError:
                pass


def download_dir():
    """「下载并导入」抓到的年份 JSON 统一存这里；导入窗的「打开下载目录」开的也是它。"""
    return os.path.join(appdata_dir(), 'downloads')


def launcher_cmd(arg=None, exe=None):
    """冻结为 exe 时直接启动自身（exe 参数可指定安装后路径）；源码运行优先用 pythonw.exe 实现无窗口静默。
    arg 为命令行参数（如 --toggle），经 IPC 转发给运行中的实例。"""
    if getattr(sys, 'frozen', False):
        cmd = '"%s"' % (exe or sys.executable)
    else:
        exe = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        if not os.path.exists(exe):
            exe = sys.executable
        script = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main.pyw'))
        cmd = '"%s" "%s"' % (exe, script)
    return cmd + (' ' + arg if arg else '')


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
    """清除自启（HKCU/HKLM 均尝试；HKLM 无管理员权限时静默跳过）。
    旧名（ZviberPanel）的残留值一并清掉，免得重装后开机启动两个。"""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for name in (APP_NAME, 'ZviberPanel'):
            try:
                with winreg.OpenKey(root, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, name)
            except OSError:
                pass


def _shell_tree_subs():
    """SHELL_KEY 整棵子树的自底向上删除顺序（winreg 不能删带子键的键）。
    含三代旧结构：直链 command、子项误放父项 shell\\ 的级联版、CommandStore 短命版。"""
    names = [n for n, _t, _a in MENU_ITEMS] + MENU_SUBKEYS_OLD
    subs = [SHELL_KEY + r'\shell\%s\command' % n for n in names]
    subs += [SHELL_KEY + r'\shell\%s' % n for n in names]
    subs += [SHELL_KEY + r'\shell', SHELL_KEY + r'\command', SHELL_KEY]
    legacy = ['Toggle', 'NewBox', 'NewFolderBox', 'ToggleBoxes', 'Settings', 'About', 'Quit']
    subs += [COMMANDSTORE_KEY + r'\ZviberPanel.%s\command' % n for n in legacy]
    subs += [COMMANDSTORE_KEY + r'\ZviberPanel.%s' % n for n in legacy]
    subs += [SHELL_KEY + r'\shell\%s\command' % n for n in legacy]
    subs += [SHELL_KEY + r'\shell\%s' % n for n in legacy]
    return subs


def _delete_shell_tree(root):
    for sub in _shell_tree_subs():
        try:
            winreg.DeleteKey(root, sub)
        except OSError:
            pass
    _delete_folder_shell_tree(root)


def _delete_folder_shell_tree(root):
    """文件夹右键项（Directory\\shell\\zviber）：先删 command 再删键（winreg 不能删带子键的键）。
    折进 _delete_shell_tree：它的全部调用点（安装/卸载/启停切换）语义都是「删干净」。"""
    for sub in (FOLDER_SHELL_KEY + r'\command', FOLDER_SHELL_KEY):
        try:
            winreg.DeleteKey(root, sub)
        except OSError:
            pass


def _delete_legacy_shell_tree(root):
    """旧名 SHELL_KEY（ZviberPanel）整棵子树的删除顺序。"""
    names = [n for n, _t, _a in MENU_ITEMS] + MENU_SUBKEYS_OLD
    subs = [LEGACY_SHELL_KEY + r'\shell\%s\command' % n for n in names]
    subs += [LEGACY_SHELL_KEY + r'\shell\%s' % n for n in names]
    subs += [LEGACY_SHELL_KEY + r'\shell', LEGACY_SHELL_KEY + r'\command', LEGACY_SHELL_KEY]
    legacy = ['Toggle', 'NewBox', 'NewFolderBox', 'ToggleBoxes', 'Settings', 'About', 'Quit']
    subs += [COMMANDSTORE_KEY + r'\ZviberPanel.%s\command' % n for n in legacy]
    subs += [COMMANDSTORE_KEY + r'\ZviberPanel.%s' % n for n in legacy]
    for sub in subs:
        try:
            winreg.DeleteKey(root, sub)
        except OSError:
            pass


def context_menu_remove():
    """清除右键菜单（HKCU/HKLM 均尝试；HKLM 无管理员权限时静默跳过）。"""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        _delete_shell_tree(root)
        _delete_legacy_shell_tree(root)


def legacy_integration_remove():
    """清掉旧名（ZviberPanel）留下的注册表残留：旧右键菜单树 + 旧卸载项。
    新名安装/卸载时都调一次，避免「设置→应用」里同时躺着两个卸载项、桌面右键多一个旧菜单。"""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        _delete_legacy_shell_tree(root)
        try:
            winreg.DeleteKey(root, LEGACY_UNINSTALL_KEY)
        except OSError:
            pass


def _menu_icon(exe, icon_path):
    if icon_path and os.path.exists(icon_path):
        return icon_path
    if exe:
        return exe
    return sys.executable if getattr(sys, 'frozen', False) else None


def _write_flat(root, exe, icon_path):
    """未运行形态：直链菜单项「zviber桌面格子」，单击启动程序。"""
    with winreg.CreateKey(root, SHELL_KEY) as k:
        winreg.SetValueEx(k, 'MUIVerb', 0, winreg.REG_SZ, MENU_TITLE)
        icon = _menu_icon(exe, icon_path)
        if icon:
            winreg.SetValueEx(k, 'Icon', 0, winreg.REG_SZ, icon)
    with winreg.CreateKey(root, SHELL_KEY + r'\command') as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, launcher_cmd(exe=exe))


def _write_cascade(root, exe, icon_path):
    """运行中形态：级联菜单，二级项与托盘右键一致（ExtendedSubCommandsKey 自引用）。
    两个实测坑（Win11 真机验证）：① 别用 SubCommands——它只按 HKLM 的 Explorer\\CommandStore
    解析，HKCU 的不认，免管理员安装没法用；② 父项有 command 子键会退化成直链不展开。"""
    with winreg.CreateKey(root, SHELL_KEY) as k:
        winreg.SetValueEx(k, 'MUIVerb', 0, winreg.REG_SZ, MENU_TITLE)
        winreg.SetValueEx(k, 'ExtendedSubCommandsKey', 0, winreg.REG_SZ, SHELL_SUBKEY)
        icon = _menu_icon(exe, icon_path)
        if icon:
            winreg.SetValueEx(k, 'Icon', 0, winreg.REG_SZ, icon)
    for name, text, arg in MENU_ITEMS:
        sub = SHELL_KEY + r'\shell\%s' % name
        with winreg.CreateKey(root, sub) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, text)
        with winreg.CreateKey(root, sub + r'\command') as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, launcher_cmd(arg=arg, exe=exe))


def _write_folder_item(root, exe, icon_path):
    """文件夹（Directory）右键项「添加到zviber桌面格子」：静态动词，%1 = 选中的文件夹路径。
    仅运行中存在（见 context_menu_set_running），点击经 --add-folder 由 IPC 转发给面板建格子。"""
    with winreg.CreateKey(root, FOLDER_SHELL_KEY) as k:
        winreg.SetValueEx(k, 'MUIVerb', 0, winreg.REG_SZ, FOLDER_MENU_TEXT)
        icon = _menu_icon(exe, icon_path)
        if icon:
            winreg.SetValueEx(k, 'Icon', 0, winreg.REG_SZ, icon)
    with winreg.CreateKey(root, FOLDER_SHELL_KEY + r'\command') as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ,
                          launcher_cmd(arg='--add-folder "%1"', exe=exe))


def context_menu_install(icon_path=None, exe=None, all_users=False):
    """安装时写入「未运行」形态：直链菜单项，单击启动程序。
    运行中形态（级联六项）由 context_menu_set_running 在面板启停时切换。"""
    root = _root(all_users)
    _delete_shell_tree(root)
    _write_flat(root, exe, icon_path)


def context_menu_set_running(running, icon_path=None):
    """面板启停时切换桌面右键菜单形态：运行中 = 级联六项（IPC 转发），未运行 = 直链单击启动。
    icon_path 供源码运行传入运行时生成的 ico（frozen 不用传，直接用 exe 自带图标）。
    - HKCU 安装：原地改写，退出切回直链；
    - HKLM（此计算机）安装：无权改 HKLM，运行时往 HKCU 写覆盖层（HKCR 合并视图 HKCU 优先）、
      退出删掉覆盖层回落 HKLM 直链；
    - 源码运行（无安装记录）：启动时注入级联菜单、退出时整体删除，不留残留
      （崩溃残留由下次启动时 installer.sync_context_menu() 清掉）。
    进程崩溃会让菜单停在级联态——此时点二级项会新起实例并本地执行动作，可接受的降级。
    文件夹右键「添加到zviber桌面格子」（FOLDER_SHELL_KEY）与级联菜单同生共死：只随
    running=True 注入，退出/卸载/覆盖安装时随 _delete_shell_tree 一并删除——未运行时不该
    出现，崩溃残留被点到则静默退出（main.pyw 的 --add-folder 分支）。"""
    hkcu_installed = uninstall_reg_get('InstallLocation', False)
    _delete_shell_tree(winreg.HKEY_CURRENT_USER)
    if running:
        _write_cascade(winreg.HKEY_CURRENT_USER, None, icon_path)
        _write_folder_item(winreg.HKEY_CURRENT_USER, None, icon_path)
    elif hkcu_installed and not uninstall_reg_get('InstallLocation', True):
        _write_flat(winreg.HKEY_CURRENT_USER, None, None)
    # 其余情况（HKLM 安装 / 源码运行）：删干净即可，分别回落 HKLM 直链 / 无菜单

def uninstall_reg_install(exe_path, all_users=False, size_kb=None):
    """写入「设置→应用→安装的应用」卸载项。size_kb 不给时按 exe 自身大小估算。"""
    if size_kb is None:
        size_kb = os.path.getsize(exe_path) // 1024
    vals = [
        ('DisplayName', winreg.REG_SZ, 'Zviber 桌面日历'),
        ('DisplayVersion', winreg.REG_SZ, APP_VERSION),
        ('Publisher', winreg.REG_SZ, 'Zviber'),
        ('DisplayIcon', winreg.REG_SZ, exe_path),
        ('InstallLocation', winreg.REG_SZ, os.path.dirname(exe_path)),
        ('UninstallString', winreg.REG_SZ, '"%s" --uninstall' % exe_path),
        ('NoModify', winreg.REG_DWORD, 1),
        ('NoRepair', winreg.REG_DWORD, 1),
        ('EstimatedSize', winreg.REG_DWORD, size_kb),
    ]
    with winreg.CreateKey(_root(all_users), UNINSTALL_KEY) as k:
        for name, vtype, val in vals:
            winreg.SetValueEx(k, name, 0, vtype, val)


def uninstall_reg_get(name, all_users=False):
    return _get(_root(all_users), UNINSTALL_KEY, name)


def legacy_uninstall_reg_get(name, all_users=False):
    """旧名（ZviberPanel）卸载项里的值，供安装向导识别旧版本并接管。"""
    return _get(_root(all_users), LEGACY_UNINSTALL_KEY, name)


def uninstall_reg_remove():
    """清除卸载项（HKCU/HKLM 均尝试；HKLM 无管理员权限时静默跳过）；旧名的也一并清掉。"""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key in (UNINSTALL_KEY, LEGACY_UNINSTALL_KEY):
            try:
                winreg.DeleteKey(root, key)
            except OSError:
                pass
