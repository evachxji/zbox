# -*- coding: utf-8 -*-
"""系统集成：开机自启 + 桌面/文件夹右键菜单 + 应用列表卸载项。
默认写 HKCU（免管理员，Win10/11 通用）；all_users=True 写 HKLM（exe 安装向导「此计算机」选项，需管理员）。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import winreg

from i18n import t
from version import APP_VERSION

APP_NAME = 'zbox'

# 桌面右键二级菜单项：(注册表子键名, 词典键, exe 命令行参数)
# 子键名的字母序就是菜单顺序，故带 A_/B_… 前缀；显示文字在运行时按当前语言取。
MENU_ITEM_DEFS = [
    ('A_NewBox', 'menu.new_box', '--new-box'),
    ('B_NewFolderBox', 'menu.new_folder_box', '--pick-folder'),
    ('C_Toggle', 'menu.toggle', '--toggle'),
    ('D_Settings', 'menu.settings', '--settings'),
    ('E_About', 'menu.about', '--about'),
    ('F_Quit', 'menu.quit', '--quit'),
]


def menu_title():
    """桌面右键父项文案（运行时取值，避免 import 期固化语言）。"""
    return t('app.name')


def menu_items():
    """桌面右键二级菜单项 (子键名, 显示文字, 命令行参数)。"""
    return [(name, t(key), arg) for name, key, arg in MENU_ITEM_DEFS]


def show_icons_text():
    """全隐藏态桌面右键唯一直链项文案。"""
    return t('menu.show_icons')


def folder_menu_text():
    """文件夹/盘符右键项文案。"""
    return t('menu.add_folder')


# 2026-10 改版前的一代子键名（当时七项、前缀不同）：整树删除时两代都要算，
# 否则改名后旧键清不掉，右键菜单新旧并存
MENU_SUBKEYS_OLD = ['A_Toggle', 'B_NewBox', 'C_NewFolderBox', 'D_ToggleBoxes',
                    'E_Settings', 'F_About', 'G_Quit']
SHOW_ICONS_ARG = '--show-icons'
IPC_KEY = 'zbox-panel-v1'   # 新名字从 v1 重新起：与旧版 zviber（zviber-panel-v2）天然不串话
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
# 右键菜单键相对 HKCR 的路径；ExtendedSubCommandsKey 要的就是这段（不带 Software\Classes\）
SHELL_SUBKEY = r'Directory\Background\shell\zbox'
SHELL_KEY = r'Software\Classes\\' + SHELL_SUBKEY
# 文件夹（Directory）与盘符（Drive）右键「添加到Zbox桌面格子」静态动词：仅运行中注入，随面板启停写删
FOLDER_SHELL_KEY = r'Software\Classes\Directory\shell\zbox'
DRIVE_SHELL_KEY = r'Software\Classes\Drive\shell\zbox'
LEGACY_SHELL_KEY = r'Software\Classes\Directory\Background\shell\zviber'  # 旧名残留，安装/退出时清掉
COMMANDSTORE_KEY = r'Software\Microsoft\Windows\CurrentVersion\Explorer\CommandStore\shell'  # 只为清理旧版残留
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\zbox'
LEGACY_UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\zviber'
PERSONALIZE_KEY = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'


def _root(all_users=False):
    return winreg.HKEY_LOCAL_MACHINE if all_users else winreg.HKEY_CURRENT_USER


def appdata_dir():
    """运行时数据目录 %APPDATA%\\zbox（配置 / 待办 / 节假日 / 格子 / 图标）。
    旧版目录名是 zviber，首次运行时整体改名搬过来，老用户的待办与格子不会丢。"""
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    p = os.path.join(base, APP_NAME)
    _migrate_appdata(base, p)
    if not os.path.isdir(p):
        os.makedirs(p)
    return p


def _migrate_appdata(base, new_dir):
    """一次性把 %APPDATA%\\zviber 改名成 %APPDATA%\\zbox。

    实测坑：面板正在运行（或资源管理器缓存着 icon.ico）时整个目录 rename 会失败，
    所以三级回退——① 整目录改名；② 逐文件搬到新目录（同名文件以新目录为准，不覆盖）；
    ③ 搬剩的（被占用的活文件）留着不动，下次启动再搬。全部搬完才删旧目录。"""
    old = os.path.join(base, 'zviber')
    if not os.path.isdir(old):
        return
    old_cfg = os.path.join(old, 'config.json')
    new_cfg = os.path.join(new_dir, 'config.json')
    if not os.path.isdir(new_dir):
        try:
            os.rename(old, new_dir)
            _reset_migrated_transfer(new_cfg)
            return
        except OSError:
            try:
                os.makedirs(new_dir)
            except OSError:
                return
    had_old_cfg = os.path.isfile(old_cfg)
    had_new_cfg = os.path.isfile(new_cfg)
    _merge_tree(old, new_dir)
    if had_old_cfg and not had_new_cfg and not os.path.isfile(old_cfg):
        _reset_migrated_transfer(new_cfg)   # 旧配置刚搬过来才重置；新目录已有的配置不动
    try:
        os.rmdir(old)      # 只为「空目录残留」清场；非空会抛错，放着下次再搬
    except OSError:
        pass


def _reset_migrated_transfer(cfg_path):
    """从 zviber 搬来的旧配置里 transfer_enabled 可能是 true（旧版里手动开过传输），
    升级后第一次启动不该直接监听端口、弹 Windows 防火墙授权——重置为关闭，
    想用的人在传输页手动启用一次（防火墙提示也出现在那一刻）。"""
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if not cfg.get('transfer_enabled'):
            return
        cfg['transfer_enabled'] = False
        with open(cfg_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False)
    except (ValueError, OSError):
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
    旧名（zviber）的残留值一并清掉，免得重装后开机启动两个。"""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for name in (APP_NAME, 'zviber'):
            try:
                with winreg.OpenKey(root, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, name)
            except OSError:
                pass


def _shell_tree_subs():
    """SHELL_KEY 整棵子树的自底向上删除顺序（winreg 不能删带子键的键）。
    含三代旧结构：直链 command、子项误放父项 shell\\ 的级联版、CommandStore 短命版。"""
    names = [n for n, _k, _a in MENU_ITEM_DEFS] + MENU_SUBKEYS_OLD
    subs = [SHELL_KEY + r'\shell\%s\command' % n for n in names]
    subs += [SHELL_KEY + r'\shell\%s' % n for n in names]
    subs += [SHELL_KEY + r'\shell', SHELL_KEY + r'\command', SHELL_KEY]
    legacy = ['Toggle', 'NewBox', 'NewFolderBox', 'ToggleBoxes', 'Settings', 'About', 'Quit']
    subs += [COMMANDSTORE_KEY + r'\zviber.%s\command' % n for n in legacy]
    subs += [COMMANDSTORE_KEY + r'\zviber.%s' % n for n in legacy]
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
    """文件夹/盘符右键项（Directory\\shell\\zbox、Drive\\shell\\zbox）：先删 command 再删键
    （winreg 不能删带子键的键）。折进 _delete_shell_tree：它的全部调用点
    （安装/卸载/启停切换）语义都是「删干净」。"""
    for base in (FOLDER_SHELL_KEY, DRIVE_SHELL_KEY):
        for sub in (base + r'\command', base):
            try:
                winreg.DeleteKey(root, sub)
            except OSError:
                pass


def _delete_legacy_shell_tree(root):
    """旧名 SHELL_KEY（zviber）整棵子树的删除顺序。"""
    names = [n for n, _k, _a in MENU_ITEM_DEFS] + MENU_SUBKEYS_OLD
    subs = [LEGACY_SHELL_KEY + r'\shell\%s\command' % n for n in names]
    subs += [LEGACY_SHELL_KEY + r'\shell\%s' % n for n in names]
    subs += [LEGACY_SHELL_KEY + r'\shell', LEGACY_SHELL_KEY + r'\command', LEGACY_SHELL_KEY]
    legacy = ['Toggle', 'NewBox', 'NewFolderBox', 'ToggleBoxes', 'Settings', 'About', 'Quit']
    subs += [COMMANDSTORE_KEY + r'\zviber.%s\command' % n for n in legacy]
    subs += [COMMANDSTORE_KEY + r'\zviber.%s' % n for n in legacy]
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


def context_menu_remove_zbox():
    """清 Zbox 自身的右键菜单树（HKCU/HKLM）。
    _delete_shell_tree 会顺带清掉 Zbox 菜单键下历史遗留的 zviber.* 子键，
    但不会删 zviber 自己的独立菜单键——那由 context_menu_remove / legacy_integration_remove 处理。"""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        _delete_shell_tree(root)


def legacy_integration_remove():
    """清掉旧名（zviber）留下的注册表残留：旧右键菜单树 + 旧卸载项。
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
    """未运行形态：直链菜单项「Zbox桌面格子」，单击启动程序。"""
    with winreg.CreateKey(root, SHELL_KEY) as k:
        winreg.SetValueEx(k, 'MUIVerb', 0, winreg.REG_SZ, menu_title())
        icon = _menu_icon(exe, icon_path)
        if icon:
            winreg.SetValueEx(k, 'Icon', 0, winreg.REG_SZ, icon)
    with winreg.CreateKey(root, SHELL_KEY + r'\command') as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, launcher_cmd(exe=exe))


def _write_show_icons(root, exe, icon_path):
    """全隐藏形态：直链单项「显示桌面图标」，单击恢复桌面图标 + 格子 + 面板。
    结构与 _write_flat 相同（SHELL_KEY + command），整树删除逻辑无需改。"""
    with winreg.CreateKey(root, SHELL_KEY) as k:
        winreg.SetValueEx(k, 'MUIVerb', 0, winreg.REG_SZ, show_icons_text())
        icon = _menu_icon(exe, icon_path)
        if icon:
            winreg.SetValueEx(k, 'Icon', 0, winreg.REG_SZ, icon)
    with winreg.CreateKey(root, SHELL_KEY + r'\command') as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ,
                          launcher_cmd(arg=SHOW_ICONS_ARG, exe=exe))


def _write_cascade(root, exe, icon_path):
    """运行中形态：级联菜单，二级项与托盘右键一致（ExtendedSubCommandsKey 自引用）。
    两个实测坑（Win11 真机验证）：① 别用 SubCommands——它只按 HKLM 的 Explorer\\CommandStore
    解析，HKCU 的不认，免管理员安装没法用；② 父项有 command 子键会退化成直链不展开。"""
    with winreg.CreateKey(root, SHELL_KEY) as k:
        winreg.SetValueEx(k, 'MUIVerb', 0, winreg.REG_SZ, menu_title())
        winreg.SetValueEx(k, 'ExtendedSubCommandsKey', 0, winreg.REG_SZ, SHELL_SUBKEY)
        icon = _menu_icon(exe, icon_path)
        if icon:
            winreg.SetValueEx(k, 'Icon', 0, winreg.REG_SZ, icon)
    for name, text, arg in menu_items():
        sub = SHELL_KEY + r'\shell\%s' % name
        with winreg.CreateKey(root, sub) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, text)
        with winreg.CreateKey(root, sub + r'\command') as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, launcher_cmd(arg=arg, exe=exe))


def _write_folder_item(root, exe, icon_path):
    """文件夹（Directory）/盘符（Drive）右键项「添加到Zbox桌面格子」：静态动词，%1 = 选中路径。
    仅运行中存在（见 context_menu_set_running），点击经 --add-folder 由 IPC 转发给面板建格子。
    盘符右键走 HKCR\\Drive，%1 = 盘根（F:\\），main.pyw 的 --add-folder 分支已兜住
    尾反斜杠吃掉闭合引号与 "F:" 两种形态。"""
    for base in (FOLDER_SHELL_KEY, DRIVE_SHELL_KEY):
        with winreg.CreateKey(root, base) as k:
            winreg.SetValueEx(k, 'MUIVerb', 0, winreg.REG_SZ, folder_menu_text())
            icon = _menu_icon(exe, icon_path)
            if icon:
                winreg.SetValueEx(k, 'Icon', 0, winreg.REG_SZ, icon)
        with winreg.CreateKey(root, base + r'\command') as k:
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
    文件夹/盘符右键「添加到Zbox桌面格子」（FOLDER_SHELL_KEY / DRIVE_SHELL_KEY）与级联菜单同生共死：只随
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


def context_menu_set_icons_hidden(hidden, icon_path=None):
    """双击桌面全隐藏后，把桌面右键收成唯一直链项「显示桌面图标」；恢复后切回级联六项。
    隐藏态只可能由运行中的 toggle_all 造成，故与 context_menu_set_running 一样只写 HKCU
    （HKLM 安装时同样是写 HKCU 覆盖层）。单项形态下文件夹右键项一并撤掉
    （_delete_shell_tree 顺手删），恢复时随级联带回。"""
    if hidden:
        _delete_shell_tree(winreg.HKEY_CURRENT_USER)
        _write_show_icons(winreg.HKEY_CURRENT_USER, None, icon_path)
    else:
        context_menu_set_running(True, icon_path)


def uninstall_reg_install(exe_path, all_users=False, size_kb=None, language=None):
    """写入「设置→应用→安装的应用」卸载项。size_kb 不给时按 exe 自身大小估算；
    language 记录安装时选择的语言（空值不写），供首次启动与卸载向导选择文案。"""
    if size_kb is None:
        size_kb = os.path.getsize(exe_path) // 1024
    vals = [
        ('DisplayName', winreg.REG_SZ, t('app.name')),
        ('DisplayVersion', winreg.REG_SZ, APP_VERSION),
        ('Publisher', winreg.REG_SZ, 'Zbox'),
        ('DisplayIcon', winreg.REG_SZ, exe_path),
        ('InstallLocation', winreg.REG_SZ, os.path.dirname(exe_path)),
        ('UninstallString', winreg.REG_SZ, '"%s" --uninstall' % exe_path),
        ('NoModify', winreg.REG_DWORD, 1),
        ('NoRepair', winreg.REG_DWORD, 1),
        ('EstimatedSize', winreg.REG_DWORD, size_kb),
    ]
    if language:
        vals.append(('Language', winreg.REG_SZ, language))
    with winreg.CreateKey(_root(all_users), UNINSTALL_KEY) as k:
        for name, vtype, val in vals:
            winreg.SetValueEx(k, name, 0, vtype, val)
        if not language:
            try:
                winreg.DeleteValue(k, 'Language')   # 覆盖安装时清掉上一版残留的语言值
            except OSError:
                pass


def uninstall_reg_get(name, all_users=False):
    return _get(_root(all_users), UNINSTALL_KEY, name)


def installed_language(all_users=None):
    """安装时记录的机器语言（卸载项 Language 值）；未安装或未记录时返回 None。
    all_users=None 时先查 HKCU、再查 HKLM。"""
    roots = (all_users,) if all_users is not None else (False, True)
    for root_all_users in roots:
        value = uninstall_reg_get('Language', root_all_users)
        if value:
            return value
    return None


def legacy_uninstall_reg_get(name, all_users=False):
    """旧名（zviber）卸载项里的值，供安装向导识别旧版本并接管。"""
    return _get(_root(all_users), LEGACY_UNINSTALL_KEY, name)


def uninstall_reg_remove():
    """清除卸载项（HKCU/HKLM 均尝试；HKLM 无管理员权限时静默跳过）；旧名的也一并清掉。"""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key in (UNINSTALL_KEY, LEGACY_UNINSTALL_KEY):
            try:
                winreg.DeleteKey(root, key)
            except OSError:
                pass


def uninstall_reg_remove_zbox():
    """只清 Zbox 自身的卸载项（HKCU/HKLM）；旧名 zviber 的残留留在原处。"""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            winreg.DeleteKey(root, UNINSTALL_KEY)
        except OSError:
            pass


# ---------------- Windows 防火墙（局域网传输） ----------------
# 首次监听端口时系统弹「安全警告」，点「取消」会写入一条针对本程序 exe 的
# 「阻止」规则且不再弹窗：出站正常（别的设备能发现本机）、入站被静默丢弃
# （发现不了别人、收不到文件），端口监听本身不报错所以界面毫无提示。
# 读规则不需要管理员，删/加规则需要（经 UAC 提权）。

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _fw_exe():
    """防火墙规则按程序路径匹配：frozen 是 zbox.exe，源码运行是 python(w).exe。"""
    return os.path.realpath(sys.executable)


def _fw_rule_names():
    """防火墙规则名的中英两种写法：规则一旦创建就按名称留在系统里，
    语言切换后仍要能匹配到旧语言的规则，避免重复放行。"""
    from i18n_en import CATALOG as EN
    from i18n_zh import CATALOG as ZH
    return ZH['sysutil.fw.rule_name'], EN['sysutil.fw.rule_name']


def _fw_match_ps():
    """PowerShell 片段：按程序路径（展开环境变量、忽略大小写）筛出本程序的规则。"""
    exe = _fw_exe().replace("'", "''")
    return ("$exe = [Environment]::ExpandEnvironmentVariables('%s');" % exe +
            "Get-NetFirewallApplicationFilter -All -ErrorAction SilentlyContinue |"
            " Where-Object { [Environment]::ExpandEnvironmentVariables($_.Program) -ieq $exe } |"
            " ForEach-Object { Get-NetFirewallRule -AssociatedNetFirewallApplicationFilter $_"
            " -ErrorAction SilentlyContinue }")


def firewall_blocked():
    """存在针对本程序的「已启用 + 阻止」规则返回 True；查询失败按 False（不误报）。"""
    ps = (_fw_match_ps() +
          " | Where-Object { $_.Enabled -eq 'True' -and $_.Action -eq 'Block' } |"
          " ForEach-Object { $hit = $true }; if ($hit) { exit 1 }")
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                           capture_output=True, timeout=90, creationflags=CREATE_NO_WINDOW)
        return r.returncode == 1
    except Exception:
        return False


def fix_firewall_rules():
    """删除本程序的阻止规则并放行 53327（TCP/UDP 入站），经 UAC 提权后执行。
    返回 'ok' / 'cancelled'（用户拒绝提权）/ 'error'。"""
    exe = _fw_exe().replace("'", "''")
    zh_name, en_name = (n.replace("'", "''") for n in _fw_rule_names())
    body = (
        "$exe = [Environment]::ExpandEnvironmentVariables('%s')\n" % exe +
        "function _rules($a) {\n"
        " Get-NetFirewallApplicationFilter -All -ErrorAction SilentlyContinue |\n"
        "  Where-Object { [Environment]::ExpandEnvironmentVariables($_.Program) -ieq $exe } |\n"
        "  ForEach-Object { Get-NetFirewallRule -AssociatedNetFirewallApplicationFilter $_"
        " -ErrorAction SilentlyContinue } |\n"
        "  Where-Object { $_.Action -eq $a }\n"
        "}\n"
        "_rules 'Block' | Remove-NetFirewallRule -ErrorAction SilentlyContinue\n" +
        "$name = '%s'\n" % t('sysutil.fw.rule_name').replace("'", "''") +
        "$names = @('%s', '%s')\n" % (zh_name, en_name) +
        "function _allow {\n"
        " $names | ForEach-Object {\n"
        "  Get-NetFirewallRule -DisplayName \"$_*\" -ErrorAction SilentlyContinue\n"
        " } | Where-Object { [Environment]::ExpandEnvironmentVariables("
        "($_ | Get-NetFirewallApplicationFilter).Program) -ieq $exe }\n"
        "}\n"
        "if (-not (_allow)) {\n"
        " New-NetFirewallRule -DisplayName \"$name (TCP)\" -Direction Inbound -Action Allow"
        " -Program $exe -Protocol TCP -LocalPort 53327 -Profile Any | Out-Null\n"
        " New-NetFirewallRule -DisplayName \"$name (UDP)\" -Direction Inbound -Action Allow"
        " -Program $exe -Protocol UDP -LocalPort 53327 -Profile Any | Out-Null\n"
        "}\n"
        "if (_rules 'Block') { exit 1 }\n"
        "if (-not (_allow)) { exit 1 }\n"
        "exit 0\n")
    # 提权子进程执行临时 ps1（UTF-8 BOM，防中文规则名乱码），避免多层命令行引号转义；
    # -Wait -PassThru 取回子进程退出码：0 成功，UAC 被拒时 Start-Process 抛错走 catch
    fd, script = tempfile.mkstemp(suffix='.ps1', prefix='zbox_fw_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8-sig') as f:
            f.write(body)
        outer = ("try { $p = Start-Process -Verb RunAs -Wait -PassThru -FilePath powershell"
                 " -ArgumentList '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',"
                 "'-File','\"%s\"'; exit $p.ExitCode } catch { exit 3 }" % script)
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', outer],
                           capture_output=True, timeout=300, creationflags=CREATE_NO_WINDOW)
        if r.returncode == 3:
            return 'cancelled'
        return 'ok' if r.returncode == 0 else 'error'
    except Exception:
        return 'error'
    finally:
        try:
            os.remove(script)
        except OSError:
            pass
