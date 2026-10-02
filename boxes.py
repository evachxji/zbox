# -*- coding: utf-8 -*-
"""桌面格子：桌面文件归类格子功能。

- 空白格子：**只是桌面文件的收纳视图，不搬动文件**（2026-10 改；旧版是把文件真搬进
  %APPDATA%\\zviber\\Boxes\\<id>\\，用户实测「属性里路径变成 AppData」「关程序后
  文件被吞掉」，故改成现在这样）。收进格子的文件留在桌面原路径（右键属性的位置就是桌面），
  只是给文件加「隐藏」属性把桌面图标藏起来；关程序/解散格子/隐藏格子时把属性还原，
  文件随即回到桌面。分组记录（rec['items'] + 隐藏属性账本 rec['attrs']）存在 boxes.json，
  下次启动自动收进格子。不在桌面的文件拖进来会先搬到桌面——「格子里的文件都在桌面」是
  这套模型的前提。拖出时先把文件挪进桌面下的隐藏暂存夹（文件本来就在桌面上，直接拖到
  桌面＝移动到它自己所在的目录，资源管理器会报「源文件名和目标文件名相同」），这样拖到
  桌面/资源管理器文件夹/别的格子都是一次真实移动；落放效果只在真会搬走时才敢报「移动」
  （报 Move 而文件没走，资源管理器会把源文件删掉）。
- 文件夹映射格子：实时映射任意磁盘文件夹，QFileSystemWatcher 监听内容变化自动刷新；
  路径失效时显示提示 + 「解散格子」按钮。
- 窗口：无边框 Tool 窗，半透明磨砂；挂桌面带免疫 Win+D（面板同款 pin_to_desktop）。
  与面板的差异：永不主动沉底（格子沉到应用窗口之下 = 用户眼里的「消失」）；
  只在被桌面整理软件表层压住时由 WinEvent 钩子/看门狗抬回表层之上。
- 双击桌面空白处显隐「桌面图标 + 全部格子 + 面板」：独立线程轮询左键沿自判双击
  （不用 WH_MOUSE_LL 全局钩子——每个系统鼠标事件都要等 Python 回调拿 GIL，拖拽时全系统
  鼠标卡顿，ctypes 回调里的崩溃还会直接闪退进程）；命中判定与旧钩子版一致。
- 视觉固定深色磨砂：格子贴在壁纸上，跟随面板明暗主题都不合适，故不挂主题系统。
  注意 WA_TranslucentBackground 会禁用 ClearType（app.py 面板因此不用它），
  格子文字少且参考软件本身就是半透明的，这里接受这个取舍。
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes

from PyQt5.QtCore import (Qt, QObject, QTimer, QThread, QUrl, QPoint, QRect, QSize,
                          QFileSystemWatcher, pyqtSignal)
from PyQt5.QtGui import QIcon, QCursor, QPainter, QColor, QPen, QFont
from PyQt5.QtWidgets import (QWidget, QDialog, QListWidget, QListWidgetItem, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QLabel, QToolButton,
                             QPushButton, QStackedLayout, QMenu, QActionGroup,
                             QMessageBox, QFileDialog, QLineEdit,
                             QAbstractItemView, QApplication, QStyle)

import app as ui   # sc / _PROG_FAMILY / _class_name / _is_desktop_surface
import sysutil

# 64 位安全的 ctypes 签名（windll 默认按 32 位 int 截断，句柄/指针高位会丢）
_h32 = ctypes.windll.user32
_h32.GetAsyncKeyState.restype = wintypes.SHORT   # SHORT 返回值，不声明会被 windll 按 32 位读
_h32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_h32.GetCursorPos.restype = wintypes.BOOL
_h32.GetCursorPos.argtypes = [ctypes.c_void_p]
_h32.GetMessageW.restype = ctypes.c_int
_h32.GetMessageW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT]
_h32.TranslateMessage.restype = wintypes.BOOL
_h32.TranslateMessage.argtypes = [ctypes.c_void_p]
_h32.DispatchMessageW.restype = ctypes.c_longlong
_h32.DispatchMessageW.argtypes = [ctypes.c_void_p]
_h32.ShowWindow.restype = wintypes.BOOL
_h32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
_h32.ScreenToClient.restype = wintypes.BOOL
_h32.ScreenToClient.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_h32.SendMessageW.restype = ctypes.c_longlong
_h32.SendMessageW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_size_t, ctypes.c_void_p]
_h32.GetWindowLongW.restype = ctypes.c_long
_h32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
_h32.GetClientRect.restype = wintypes.BOOL
_h32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_h32.AllowSetForegroundWindow.restype = wintypes.BOOL
_h32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
_h32.CreatePopupMenu.restype = ctypes.c_void_p
_h32.CreatePopupMenu.argtypes = []
_h32.DestroyMenu.restype = wintypes.BOOL
_h32.DestroyMenu.argtypes = [ctypes.c_void_p]
_h32.TrackPopupMenu.restype = wintypes.BOOL
_h32.TrackPopupMenu.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
_s32 = ctypes.windll.shell32
_s32.SHParseDisplayName.restype = ctypes.c_long
_s32.SHParseDisplayName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                    ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD)]
_s32.SHBindToParent.restype = ctypes.c_long
_s32.SHBindToParent.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
_s32.CDefFolderMenu_Create2.restype = ctypes.c_long
_s32.CDefFolderMenu_Create2.argtypes = [ctypes.c_void_p, wintypes.HWND, ctypes.c_uint,
                                        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                        ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p,
                                        ctypes.POINTER(ctypes.c_void_p)]
_s32.ILFree.argtypes = [ctypes.c_void_p]
_s32.ShellExecuteExW.restype = wintypes.BOOL
_s32.ShellExecuteExW.argtypes = [ctypes.c_void_p]
_o32 = ctypes.windll.ole32
_a32 = ctypes.windll.advapi32
_a32.RegOpenKeyExW.restype = ctypes.c_long
_a32.RegOpenKeyExW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.DWORD,
                               wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
_a32.RegCloseKey.restype = ctypes.c_long
_a32.RegCloseKey.argtypes = [ctypes.c_void_p]
_HKCR = ctypes.c_void_p(0x80000000)   # HKEY_CLASSES_ROOT
_o32.CoInitializeEx.restype = ctypes.c_long
_o32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_o32.CoUninitialize.argtypes = []
_k32 = ctypes.windll.kernel32
_k32.OpenProcess.restype = ctypes.c_void_p
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.VirtualAllocEx.restype = ctypes.c_void_p
_k32.VirtualAllocEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                wintypes.DWORD, wintypes.DWORD]
_k32.VirtualFreeEx.restype = wintypes.BOOL
_k32.VirtualFreeEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
_k32.WriteProcessMemory.restype = wintypes.BOOL
_k32.WriteProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_size_t, ctypes.c_void_p]
_k32.ReadProcessMemory.restype = wintypes.BOOL
_k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.c_void_p]
_k32.CloseHandle.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = [ctypes.c_void_p]
_k32.GetFileAttributesW.restype = wintypes.DWORD
_k32.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
_k32.SetFileAttributesW.restype = wintypes.BOOL
_k32.SetFileAttributesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
_s32.SHChangeNotify.restype = None
_s32.SHChangeNotify.argtypes = [ctypes.c_long, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]

ATTR_HIDDEN = 0x2
_INVALID_ATTRS = 0xFFFFFFFF
_SHCNE_UPDATEDIR = 0x00001000
_SHCNF_PATHW = 0x0005
_SHCNF_FLUSH = 0x1000

# 桌面图标位置修正（_DesktopIconLayout）用的 ListView 消息与样式位
_LVM_GETITEMCOUNT = 0x1004
_LVM_SETITEMPOSITION = 0x100F
_LVM_GETITEMPOSITION = 0x1010
_LVM_GETITEMSPACING = 0x1033
_LVM_GETITEMTEXTW = 0x1073
_GWL_STYLE = -16
_LVS_AUTOARRANGE = 0x0100

# 拖出空白格子时的暂存目录名（桌面下的隐藏夹，见 BoxWindow.stage_for_drag）
_STAGE_NAME = '.zviber'

SORT_CHOICES = [('name', '按名称'), ('type', '按类型'), ('mtime', '按修改时间')]

TITLE_H = 30        # 标题栏高（设计像素，运行时过 sc()）
EDGE = 10           # 边缘缩放命中宽度
MIN_W = 200 / 3       # 最小宽度（设计像素）；最小高度=标题栏高+60，写死在 setMinimumSize 里
DEF_W, DEF_H = 300, 420


def _box_qss():
    """格子局部样式表（挂在每个格子窗口上，不走全局主题）。px 手动过 sc()。"""
    qss = """
QWidget { font-family: '@CN@'; }
QLabel { color: rgba(255,255,255,225); background: transparent; }
QLabel#boxName { font-size: @TFS@px; font-weight: bold; }
QLabel#boxHint { color: rgba(255,255,255,110); font-size: @HFS@px; }
QLabel#boxInvalid1 { color: rgba(255,255,255,225); font-size: @TFS@px; }
QLabel#boxInvalid2 { color: rgba(255,255,255,160); font-size: @HFS@px; }
QToolButton { color: rgba(255,255,255,170); background: transparent; border: none;
              font-size: @BFS@px; padding: 0px; }
QToolButton:hover { background: rgba(255,255,255,28); border-radius: 4px; }
QLineEdit#boxNameEdit { color: rgba(255,255,255,235); background: rgba(255,255,255,24);
                        border: 1px solid rgba(255,255,255,70); border-radius: 3px;
                        font-size: @TFS@px; font-weight: bold; padding: 0px 2px;
                        selection-background-color: rgba(255,255,255,90); }
QListWidget { background: transparent; border: none; outline: none;
              color: rgba(255,255,255,225); font-size: @LFS@px; }
QListWidget::item { height: @IH@px; border-radius: 4px; padding-left: 4px; }
QListWidget::item:hover { background: rgba(255,255,255,16); }
QListWidget::item:selected { background: rgba(255,255,255,30); }
QScrollBar:vertical { width: @SBW@px; background: transparent; margin: 2px 2px 2px 0px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,70); border-radius: @SBR@px;
                              min-height: 24px; }
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,110); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { height: @SBW@px; background: transparent; margin: 0px 2px 2px 2px; }
QScrollBar::handle:horizontal { background: rgba(255,255,255,70); border-radius: @SBR@px;
                                min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: rgba(255,255,255,110); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QMessageBox { background: #26282f; }
QMessageBox QLabel { color: rgba(255,255,255,225); font-size: @HFS@px; }
QMenu { background: #26282f; color: #e8e6e1; border: 1px solid rgba(255,255,255,30);
        padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 4px; }
QMenu::item:selected { background: rgba(255,255,255,25); }
QMenu::separator { height: 1px; background: rgba(255,255,255,20); margin: 4px 8px; }
QPushButton { background: rgba(255,255,255,30); color: #fff; border: none;
              border-radius: 4px; padding: 5px 18px; font-size: @HFS@px; }
QPushButton:hover { background: rgba(255,255,255,55); }
"""
    vals = {'@CN@': ui.pick_fonts()[0], '@TFS@': ui.sc(12), '@HFS@': ui.sc(11),
            '@BFS@': ui.sc(11), '@LFS@': ui.sc(12), '@IH@': ui.sc(26),
            '@SBW@': ui.sc(8), '@SBR@': ui.sc(4)}
    for k, v in vals.items():
        qss = qss.replace(k, str(v))
    return qss


def desktop_dir():
    """真实桌面目录（处理 OneDrive 重定向）：SHGetFolderPath CSIDL_DESKTOPDIRECTORY。"""
    try:
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) == 0:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser('~'), 'Desktop')


def _shell_refresh(dir_path):
    """通知外壳「这个目录变了」。SHCNF_FLUSH 让资源管理器当场处理，不等它自己反应过来
    ——实测桌面图标的隐藏/恢复都在 50ms 内生效（不刷的话图标要过一会儿才消失，
    就是用户报的「拖进格子后桌面图标有延迟」）。"""
    try:
        _s32.SHChangeNotify(_SHCNE_UPDATEDIR, _SHCNF_PATHW | _SHCNF_FLUSH,
                            ctypes.c_wchar_p(dir_path), None)
    except Exception:
        pass


def _unique_name(dest_dir, name):
    """目标目录里的不重名文件名：冲突时 '名 (2).ext' 递增。"""
    if not os.path.exists(os.path.join(dest_dir, name)):
        return name
    base, ext = os.path.splitext(name)
    n = 2
    while os.path.exists(os.path.join(dest_dir, '%s (%d)%s' % (base, n, ext))):
        n += 1
    return '%s (%d)%s' % (base, n, ext)


def _recover_files(path, desk, items):
    """把 path 里的文件搬回桌面（去重后补进 items），搬空则删掉目录。
    用于启动恢复：旧版存储目录与拖拽暂存夹的残留都走这里。"""
    if not path or not os.path.isdir(path):
        return items
    try:
        for name in os.listdir(path):
            try:
                dst = os.path.join(desk, _unique_name(desk, name))
                shutil.move(os.path.join(path, name), dst)
                if dst not in items:
                    items.append(dst)
            except OSError:
                pass
    except OSError:
        pass
    try:
        if not os.listdir(path):
            os.rmdir(path)
    except OSError:
        pass
    return items


def _recycle(paths):
    """删除到回收站（SHFileOperation + FOF_ALLOWUNDO）。"""
    if not paths:
        return

    class _SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [('hwnd', ctypes.c_void_p), ('wFunc', ctypes.c_uint),
                    ('pFrom', ctypes.c_wchar_p), ('pTo', ctypes.c_wchar_p),
                    ('fFlags', ctypes.c_ushort), ('fAnyOperationsAborted', wintypes.BOOL),
                    ('hNameMappings', ctypes.c_void_p), ('lpszProgressTitle', ctypes.c_wchar_p)]

    op = _SHFILEOPSTRUCTW()
    op.wFunc = 0x3            # FO_DELETE
    op.pFrom = '\0'.join(paths) + '\0\0'
    op.fFlags = 0x40 | 0x10   # FOF_ALLOWUNDO | FOF_NOCONFIRMATION
    ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))


class BoxStore(object):
    """boxes.json：{'visible': 是否全部显示, 'boxes': [格子记录]}。
    记录字段：id / name / kind('blank'|'folder') / x,y,w,h / collapsed / locked / sort。
    folder 用 path（被映射的磁盘文件夹）；blank 用 items（收进来的桌面文件绝对路径）
    + attrs（被我们隐藏了图标的文件的原属性，退出时按它还原）。"""

    def __init__(self, path):
        self.path = path
        self.data = {'visible': True, 'boxes': []}
        self.load()

    def load(self):
        try:
            with open(self.path, 'r', encoding='utf-8-sig') as f:   # ????????? BOM
                self.data.update(json.load(f))
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False)
        except Exception:
            pass


class BoxList(QListWidget):
    """格子文件列表：拖入归类、拖出回桌面/别处、双击打开、右键菜单、Delete 删除。"""

    def __init__(self, box):
        super(BoxList, self).__init__()
        self.box = box
        self.setViewMode(QListWidget.ListMode)
        self.setIconSize(QSize(ui.sc(16), ui.sc(16)))
        self.setResizeMode(QListWidget.Adjust)
        self.setUniformItemSizes(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.itemDoubleClicked.connect(lambda it: self.box.open_path(it.data(Qt.UserRole)))
        self._menu_press_ts = 0.0   # 最近一次「点掉外壳菜单」的那按下（见 mouseDoubleClickEvent）

    def mousePressEvent(self, e):
        # 菜单正开着（或刚被点关掉）时落下的这一按，就是「点掉那个菜单」的那一下——
        # 菜单由宿主进程弹出，点它会**穿透**到下面的格子窗口上（实测：菜单弹在第一行，
        # 左键点没被菜单盖住的另一行，格子列表照样收到 press/itemClicked）。
        if _menu_open_or_just_closed():
            self._menu_press_ts = time.time()
        super(BoxList, self).mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        """双击只认左键——Qt 对**右键**也会发双击事件（实测：同一位置两次右键、间隔 60ms
        即触发 DblClick；Windows 的 500ms 双击间隔内、位移小于阈值都算）。而上面那行把
        itemDoubleClicked 直接接到 open_path（打开），于是「连续两次右键同一项」就会把它
        打开：用户实测的「第二次右键必然打开第二个文件」就是这个（位移超过 ~40px 时不触发，
        所以并非每次都犯）。这里把非左键的双击吃掉，别传给 QListWidget——传下去照样会发
        itemDoubleClicked。左键路径原样走 super()，双击打开的行为不变。

        第二道守卫同理：点掉外壳菜单的那一下也会穿透成一次**左键**按下，用户接着再点一下
        就是一次「左键+左键」的合法双击 ⇒ 白开一个文件（2026-10 用户实测：右键 A 弹菜单、
        再左键 B 就打开 B）。菜单关闭后 0.6s 内的双击一律不算数——真想双击打开，菜单
        已经关了，再点一次即可。"""
        if e.button() != Qt.LeftButton:
            e.accept()
            return
        if self._menu_press_ts and time.time() - self._menu_press_ts < 0.6:
            ui._dbg('★ 菜单关闭后 %.2fs 内的双击，不打开'
                    % (time.time() - self._menu_press_ts))
            e.accept()
            return
        super(BoxList, self).mouseDoubleClickEvent(e)

    def dragEnterEvent(self, e):
        paths = self._drag_paths(e)
        if paths:
            e.setDropAction(self.box.drag_effect())   # 见 drag_effect：报错会删文件
            e.accept()
        else:
            super(BoxList, self).dragEnterEvent(e)

    def dragMoveEvent(self, e):
        paths = self._drag_paths(e)
        if paths:
            e.setDropAction(self.box.drag_effect())
            e.accept()
        else:
            super(BoxList, self).dragMoveEvent(e)

    def dropEvent(self, e):
        if e.source() is self:
            e.ignore()   # 列表按排序填充，不支持内部拖放换位
            return
        paths = self._drag_paths(e)
        if paths:
            self.box.import_paths(paths)
            e.setDropAction(self.box.drop_effect(paths))   # 按实际搬没搬走回报
            e.accept()

    def _drag_paths(self, e):
        """外部拖进来的本地文件路径（source 是自己的列表 = 格子内部拖拽，不算）。"""
        if e.source() is self:
            return []
        return [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]

    def mimeData(self, items):
        """拖出时附带文件 URL：落到桌面/资源管理器/别的格子都是一次真实移动。
        空白格子的条目在 startDrag 里已经换成暂存路径（见 stage_for_drag）。"""
        md = super(BoxList, self).mimeData(items)
        md.setUrls([QUrl.fromLocalFile(it.data(Qt.UserRole)) for it in items])
        return md

    def startDrag(self, actions):
        """拖出前：空白格子把文件挪到桌面下的隐藏暂存夹（见 BoxWindow.stage_for_drag）。
        非挪不可——文件本来就在桌面上，直接拖到桌面＝把文件移动到它自己所在的目录，
        资源管理器会弹「源文件名和目标文件名相同」（用户实测）；挪出去之后拖到桌面
        才是一次真实的跨目录移动。拖动数据里也要换成暂存路径，否则报错照旧。"""
        items = self.selectedItems()
        saved = self.box.stage_for_drag([it.data(Qt.UserRole) for it in items])
        staged = dict(saved)
        for it in items:
            p = it.data(Qt.UserRole)
            if p in staged:
                it.setData(Qt.UserRole, staged[p])
        try:
            super(BoxList, self).startDrag(actions)
        finally:
            self.box.finish_drag_out(saved)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete:
            self.box.delete_items(self.selectedItems())
        else:
            super(BoxList, self).keyPressEvent(e)

    def _rename_item(self, it):
        """外壳菜单「重命名」→ 行内编辑（rename 动词没有文件夹视图不会生效，只能自己做）。
        编辑框里用真实文件名（含扩展名），提交即 os.rename，取消/失败都刷新恢复。"""
        path = it.data(Qt.UserRole)
        it.setText(os.path.basename(path))
        it.setFlags(it.flags() | Qt.ItemIsEditable)

        def on_changed(item):
            if item is not it:
                return
            new_name = item.text().strip()
            if new_name and new_name != os.path.basename(path) and \
                    not any(c in new_name for c in '\\/:*?"<>|'):
                new_path = os.path.join(os.path.dirname(path), new_name)
                try:
                    os.rename(path, new_path)
                except OSError:
                    pass
                else:
                    self.box.rename_item(path, new_path)

        def on_closed(*_a):
            self.itemChanged.disconnect(on_changed)
            self.itemDelegate().closeEditor.disconnect(on_closed)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.box.refresh()   # 取消则恢复显示名，改名则重建列表

        self.itemChanged.connect(on_changed)
        self.itemDelegate().closeEditor.connect(on_closed)
        self.editItem(it)

    def contextMenuEvent(self, e):
        # e.pos()/globalPos() 在非 100%% DPI 下不可信：Qt5 不换算 WM_CONTEXTMENU
        # lParam 的物理坐标（渲染 ×1.25 但事件不除），itemAt 必错位。
        # 光标实时位置 QCursor.pos() 换算是正确的，以此为准。
        pos = self.mapFromGlobal(QCursor.pos())
        it = self.itemAt(pos)
        ui._dbg('ctxmenu-event: pos=%s it=%s' % (pos, it.text() if it else None))
        if it:
            # 右键落在多选之外：先改成只选它（与资源管理器的选择语义一致）
            sel = self.selectedItems()
            if it not in sel:
                self.clearSelection()
                it.setSelected(True)
                sel = [it]
            paths = [i.data(Qt.UserRole) for i in sel]

            def _do_rename(it=it):
                try:
                    if it.listWidget() is self:   # 菜单开着时列表可能已刷新重建
                        self._rename_item(it)
                except RuntimeError:
                    pass

            gp = QCursor.pos()
            r = shell_context_menu(int(self.winId()), paths,
                                   gp.x(), gp.y(),
                                   on_rename=_do_rename)
            ui._dbg('ctxmenu: 接管结果 r=%r' % (r,))
            if r == 'rename':
                self._rename_item(it)
                return
            if r:
                return
            # ★ Qt 兜底菜单：**只有宿主与 ctypes 两条路都没接管才会走到这**。它弹在
            # 光标处、第一项是「打开」，而右键之后按键可能还按着——松开就会被当成选中它。
            ui._dbg('★ 走了 Qt 兜底菜单（宿主/ctypes 都没接管）it=%s' % it.text())
        menu = QMenu(self)
        if it:
            path = it.data(Qt.UserRole)
            menu.addAction('打开', lambda: self.box.open_path(path))
            menu.addAction('在资源管理器中显示', lambda: self.box.reveal_path(path))
            menu.addSeparator()
            menu.addAction('删除', lambda: self.box.delete_items(self.selectedItems()))
        else:
            menu.addAction('刷新', self.box.refresh)
            menu.addAction('在资源管理器中打开',
                           lambda: self.box.open_path(self.box.display_dir()))
        if menu.actions():
            act = menu.exec_(QCursor.pos())
            ui._dbg('★ Qt 兜底菜单选择: %s' % (act.text() if act else None))


class BoxConfirmDialog(QDialog):
    """格子内的二次确认弹窗：无边框 Tool 窗，结构参考面板的「关于」窗
    （可拖标题栏 + ✕ 关闭 + 右下按钮），视觉与格子本体一致——固定深色磨砂，
    不走全局主题（格子本身就不走，见模块 docstring）。"""

    def __init__(self, box, title, text, ok_text):
        super(BoxConfirmDialog, self).__init__(box, Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(_box_qss())
        self._drag = None

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        # 标题栏（可拖动）：标题 + ✕
        self.titlebar = QWidget()
        self.titlebar.setFixedHeight(ui.sc(TITLE_H))
        tb = QHBoxLayout(self.titlebar)
        tb.setContentsMargins(ui.sc(10), 0, ui.sc(6), 0)
        t = QLabel(title)
        t.setObjectName('boxName')
        tb.addWidget(t)
        tb.addStretch(1)
        close = QToolButton()
        close.setText('✕')
        close.setFixedSize(ui.sc(22), ui.sc(20))
        close.setToolTip('关闭')
        close.clicked.connect(self.reject)
        tb.addWidget(close)
        root.addWidget(self.titlebar)

        # 正文
        body = QLabel(text)
        body.setObjectName('boxInvalid1')
        body.setWordWrap(True)
        bd = QHBoxLayout()
        bd.setContentsMargins(ui.sc(12), ui.sc(6), ui.sc(12), 0)
        bd.addWidget(body, 1)
        root.addLayout(bd)

        # 右下按钮：取消 + 确认（回车默认确认，Esc 取消）
        btns = QHBoxLayout()
        btns.setContentsMargins(ui.sc(12), ui.sc(12), ui.sc(10), ui.sc(10))
        btns.setSpacing(ui.sc(8))
        btns.addStretch(1)
        ok = QPushButton(ok_text)
        ok.setCursor(Qt.PointingHandCursor)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btns.addWidget(ok)
        cancel = QPushButton('取消')
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        root.addLayout(btns)

        self.setFixedWidth(ui.sc(300))
        self.adjustSize()
        # 居中在格子窗口上
        self.move(box.geometry().center() - self.rect().center())

    def paintEvent(self, e):
        # 与 BoxWindow 同款磨砂圆角，只是更不透明一点（弹窗要压得住下面的内容）
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setBrush(QColor(25, 28, 34, 235))
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        p.drawRoundedRect(r, ui.sc(8), ui.sc(8))
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.pos().y() < self.titlebar.height():
            self._drag = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()
        else:
            super(BoxConfirmDialog, self).mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPos() - self._drag)
            e.accept()
        else:
            super(BoxConfirmDialog, self).mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        super(BoxConfirmDialog, self).mouseReleaseEvent(e)


class BoxWindow(QWidget):
    """单个桌面格子窗口。"""

    def __init__(self, mgr, rec):
        super(BoxWindow, self).__init__(None, Qt.FramelessWindowHint | Qt.Tool)
        self.mgr = mgr
        self.rec = rec
        self._desk_pinned = False
        self._desk_surface = None   # 探测到的第三方桌面表层（抬回锚点缓存）
        self._dragging = {}         # 拖出期间 {原路径: 暂存路径}（见 stage_for_drag）
        self._op = None          # ('move', 起点全局坐标, 起始几何) 或 ('resize', 边缘掩码, ...)
        self._press_pos = None   # 拖拽起点（全局坐标），用于区分点击与拖动
        self._last_drag_ts = 0.0   # 最近一次发生位移的拖拽结束时间（抑制拖拽连带的双击收起）
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        # 整窗接受拖放：只有文件列表（视口）注册了拖放目标，拖到标题栏/空白提示区/
        # 边缘这些地方 Qt 找不到接受拖放的控件，直接忽略这次拖拽——用户看到的就是
        # 鼠标变红色禁止图标、怎么都放不进去（收起状态更是整个格子都放不进去）。
        self.setAcceptDrops(True)
        self.setMinimumSize(ui.sc(MIN_W), ui.sc(TITLE_H) + ui.sc(60))
        self.setStyleSheet(_box_qss())
        self.setFont(QFont(ui.pick_fonts()[0]))

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        # 标题栏：文件夹图标 + 名称 + 收起/锁定/菜单（图标只有映射格子有，见下）
        self.title = QWidget()
        self.title.setFixedHeight(ui.sc(TITLE_H))
        tb = QHBoxLayout(self.title)
        tb.setContentsMargins(ui.sc(10), 0, ui.sc(6), 0)
        tb.setSpacing(ui.sc(4))
        self.icon = QLabel()
        self.icon.setFixedSize(ui.sc(16), ui.sc(16))
        self.icon.setScaledContents(True)
        if rec['kind'] == 'folder':
            # 映射格子：点图标打开所在文件夹
            self.icon.setCursor(Qt.PointingHandCursor)
            self.icon.setToolTip('打开所在文件夹')
        else:
            # 空白格子不显示图标——它背后没有对应的文件夹，图标只是个无意义的点缀，
            # 隐藏后布局不占位（QHBoxLayout 跳过隐藏控件），标题栏只留名称
            self.icon.hide()
        tb.addWidget(self.icon)
        self.name = QLabel(rec['name'])
        self.name.setObjectName('boxName')
        tb.addWidget(self.name, 1)
        # 双击名称后原地替换成的重命名输入框
        self.edit = QLineEdit(rec['name'])
        self.edit.setObjectName('boxNameEdit')
        self.edit.hide()
        self.edit.editingFinished.connect(self._finish_rename)
        tb.addWidget(self.edit, 1)
        self._edit_cancel = False
        self.btn_collapse = QToolButton()
        self.btn_collapse.setFixedSize(ui.sc(22), ui.sc(20))
        self.btn_collapse.clicked.connect(lambda: self.set_collapsed(not self.rec['collapsed']))
        tb.addWidget(self.btn_collapse)
        self.btn_lock = QToolButton()
        self.btn_lock.setFixedSize(ui.sc(22), ui.sc(20))
        self.btn_lock.clicked.connect(lambda: self.set_locked(not self.rec['locked']))
        tb.addWidget(self.btn_lock)
        self.btn_menu = QToolButton()
        self.btn_menu.setText('≡')
        self.btn_menu.setFixedSize(ui.sc(22), ui.sc(20))
        self.btn_menu.clicked.connect(self._show_menu)
        tb.addWidget(self.btn_menu)
        root.addWidget(self.title)

        # 内容：文件列表页 / 路径失效页
        self.pages = QStackedLayout()
        root.addLayout(self.pages, 1)  # 先装进父控件再加页面：否则第一页成为当前页，
        page_list = QWidget()          # 会被 QStackedLayout 立刻 show()，无父状态下闪出白框
        gl = QGridLayout(page_list)
        gl.setContentsMargins(ui.sc(4), 0, ui.sc(4), ui.sc(4))
        self.list = BoxList(self)
        gl.addWidget(self.list, 0, 0)
        self.hint = QLabel('拖动文件到格子中\n分类整理你的文件吧')
        self.hint.setObjectName('boxHint')
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        gl.addWidget(self.hint, 0, 0, Qt.AlignCenter)
        self.pages.addWidget(page_list)

        page_invalid = QWidget()
        il = QVBoxLayout(page_invalid)
        il.addStretch(1)
        t1 = QLabel('无法显示在桌面')
        t1.setObjectName('boxInvalid1')
        t1.setAlignment(Qt.AlignCenter)
        t2 = QLabel('文件夹路径已经失效')
        t2.setObjectName('boxInvalid2')
        t2.setAlignment(Qt.AlignCenter)
        btn = QPushButton('解散格子')
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.dissolve)
        il.addWidget(t1)
        il.addWidget(t2)
        il.addSpacing(ui.sc(10))
        il.addWidget(btn, 0, Qt.AlignCenter)
        il.addStretch(1)
        self.pages.addWidget(page_invalid)

        # 子控件默认继承顶层窗口的光标：边缘悬停设了双箭头后划入子控件不会复位。
        # 全部子控件开鼠标跟踪并装过滤器，MouseMove 时按窗口坐标同步光标；
        # 不开跟踪的话标题栏等区域收不到 MouseMove，光标会一直残留双箭头。
        for w in self.findChildren(QWidget):
            w.setMouseTracking(True)
            w.installEventFilter(self)

        # 文件夹内容变化自动刷新（300ms 去抖）
        self.watcher = QFileSystemWatcher(self)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self.refresh)
        self.watcher.directoryChanged.connect(lambda _p: self._debounce.start())

        # 桌面层级：归属桌面带（免疫 Win+D，面板同款 pin_to_desktop）+ WinEvent 钩子
        # + 500ms 看门狗。与面板的关键差异：永不主动沉底——格子被压到应用窗口之下
        # 就是用户眼里的「消失」。只在被桌面整理表层压住时抬回（表层每 ~2.5s 重建，
        # 钩子毫秒级抬回，等看门狗会闪半秒）。
        self._win_evt_cb = ui._WINEVENTPROC(self._on_win_event)   # 必须留引用，防 GC
        self._win_evt_hook = ui._u32.SetWinEventHook(ui._EVENT_SHOW, ui._EVENT_REORDER,
                                                     None, self._win_evt_cb, 0, 0, 0)
        QApplication.instance().aboutToQuit.connect(self._unhook_win_event)
        self._sink_timer = QTimer(self)
        self._sink_timer.timeout.connect(self._desktop_tick)
        self._sink_timer.start(500)

        self.resize(rec.get('w') or ui.sc(DEF_W), rec.get('h') or ui.sc(DEF_H))
        self._apply_rec_to_ui()
        self.refresh()

    # ---------- 记录 → 界面 ----------
    def _apply_rec_to_ui(self):
        self.name.setText(self.rec['name'])
        self.set_collapsed(self.rec.get('collapsed', False), save=False)
        self.set_locked(self.rec.get('locked', False), save=False)

    def _icon_for(self, path, is_dir):
        """QFileIconProvider 需要 QFileInfo；文件夹图标直接取 style 的标准图标更稳。"""
        from PyQt5.QtCore import QFileInfo
        from PyQt5.QtWidgets import QFileIconProvider
        if not hasattr(self, '_icon_provider'):
            self._icon_provider = QFileIconProvider()
        return self._icon_provider.icon(QFileInfo(path))

    def display_dir(self):
        """格子内容所在目录：映射格子是映射的目录，空白格子是桌面（文件都在桌面上）。"""
        return self.rec['path'] if self.rec['kind'] == 'folder' else desktop_dir()

    def refresh(self):
        """重新扫描填充列表；映射文件夹失效时切到失效页。
        空白格子按 rec['items'] 记账列文件（文件在桌面上），不再扫目录。"""
        if self._dragging:
            # 拖出期间不重建列表：文件此刻在暂存夹里（桌面目录变化会触发 watcher 刷新），
            # 这时候 clear() 会把拖拽源那一行清掉。拖完 finish_drag_out 会刷新。
            return
        if self.rec['kind'] == 'folder':
            path = self.rec['path']
            if not os.path.isdir(path):
                self.pages.setCurrentIndex(1)
                self._rewatch()
                return
            entries = self._scan_dir(path)
        else:
            entries = self._entries_from_items()
        self.pages.setCurrentIndex(0)
        self._rewatch()
        sort = self.rec.get('sort', 'name')
        if sort == 'mtime':
            key = lambda e: (not e[2], -e[3].st_mtime, e[0].lower())
        elif sort == 'type':
            key = lambda e: (not e[2], os.path.splitext(e[0])[1].lower(), e[0].lower())
        else:
            key = lambda e: (not e[2], e[0].lower())
        entries.sort(key=key)

        self.list.clear()
        for name, p, is_dir, st in entries:
            disp = name[:-4] if name.lower().endswith('.lnk') else name   # 快捷方式不显示 .lnk 后缀
            item = QListWidgetItem(self._icon_for(p, is_dir), disp)
            item.setData(Qt.UserRole, p)
            item.setToolTip(p)
            self.list.addItem(item)
        self.hint.setVisible(not entries and self.rec['kind'] == 'blank')
        # 标题图标只有映射格子有（空白格子隐藏了图标，只显示名称，见 __init__）
        if self.rec['kind'] == 'folder':
            pm = self._icon_for(self.rec['path'], True).pixmap(ui.sc(16), ui.sc(16))
            self.icon.setPixmap(pm)

    _FLASH_PHASES = (0.35, 1.0, 0.35, 1.0)

    def flash(self):
        """「这个文件夹已经有格子了」的提示：整体透明度闪两轮。
        单 QTimer + 相位重置，连点不会叠出多条 timer 链互相打架。"""
        self._flash_step = 0
        if getattr(self, '_flash_timer', None) is None:
            self._flash_timer = QTimer(self)   # 挂窗口 parent：格子解散随窗销毁，不回调野指针
            self._flash_timer.setInterval(110)
            self._flash_timer.timeout.connect(self._flash_tick)
        self._flash_timer.start()

    def _flash_tick(self):
        if self._flash_step < len(self._FLASH_PHASES):
            self.setWindowOpacity(self._FLASH_PHASES[self._flash_step])
            self._flash_step += 1
        else:
            self._flash_timer.stop()
            self.setWindowOpacity(1.0)   # 结束态精确回 1.0（含闪烁中被 hide/show 的路径）

    def _scan_dir(self, path):
        """映射格子的目录扫描（隐藏文件不显示）。"""
        entries = []
        try:
            for it in os.scandir(path):
                try:
                    st = it.stat()
                except OSError:
                    continue
                if getattr(st, 'st_file_attributes', 0) & ATTR_HIDDEN:
                    continue   # 隐藏文件不显示
                entries.append((it.name, it.path, it.is_dir(), st))
        except OSError:
            pass
        return entries

    def _entries_from_items(self):
        """空白格子的条目：只认记账过的路径，已消失的顺手从 items 和隐藏账本里剔除。
        拖出期间文件在暂存夹里，按暂存路径确认它还在（列表不能中途少一行）。"""
        attrs = self.rec.setdefault('attrs', {})
        items, entries, dirty = [], [], False
        for p in self.rec.get('items') or []:
            try:
                st = os.stat(self._dragging.get(p, p))
            except OSError:
                if p in self._dragging:
                    continue     # 暂存文件已被搬走：等 finish_drag_out 收尾，先别动
                attrs.pop(p, None)   # 文件不在了（被删/被搬走）：隐藏账本一起划掉
                dirty = True
                continue
            items.append(p)
            entries.append((os.path.basename(p), p, os.path.isdir(p), st))
        if dirty:
            self.rec['items'] = items
            self.mgr.save_rec(self)
        return entries

    def _rewatch(self):
        old = self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        # 空白格子看桌面：收进格子的文件在桌面被删/改名/剪切走都要跟着刷新
        watch = self.display_dir()
        if os.path.isdir(watch):
            self.watcher.addPath(watch)

    # ---------- 空白格子：桌面图标隐藏账本 ----------
    def _hide_icon(self, path):
        """把桌面图标藏起来 = 给文件加「隐藏」属性（资源管理器唯一支持的单项隐藏方式），
        原属性记进 rec['attrs'] 以便还原。本来就隐藏的（图标本来就不显示）不动、不记账。"""
        attrs = self.rec.setdefault('attrs', {})
        if path in attrs:
            return
        old = _k32.GetFileAttributesW(path)
        if old == _INVALID_ATTRS or old & ATTR_HIDDEN:
            return
        if _k32.SetFileAttributesW(path, old | ATTR_HIDDEN):
            attrs[path] = old

    def _show_icon(self, path):
        """把桌面图标放出来：还原隐藏前的属性。"""
        old = self.rec.setdefault('attrs', {}).pop(path, None)
        if old is not None and os.path.exists(path):
            _k32.SetFileAttributesW(path, old)

    def hide_icons(self):
        """收进格子：隐藏 items 的桌面图标。"""
        for p in self.rec.get('items') or []:
            self._hide_icon(p)
        _shell_refresh(desktop_dir())
        self.mgr.save_rec(self)

    def show_icons(self):
        """放回桌面：还原我们隐藏过的图标（关程序 / 解散格子 / 隐藏格子时调）。
        重新出现的图标由 Explorer 自行摆位——落在第一列从上往下第一个空位
        （用户眼里就是「跑到屏幕最左上角」，桌面满员时还会把原有图标挤下去且
        不回弹）——所以释放前后各做一次快照/修正：新图标挪到桌面图标末尾行，
        被挤的原有图标按快照摆回（_DesktopIconLayout，实测依据见其 docstring）。"""
        paths = list(self.rec.get('attrs') or {})
        lay = _DesktopIconLayout() if paths else None
        before = lay.snapshot() if lay else None
        for p in paths:
            self._show_icon(p)
        _shell_refresh(desktop_dir())
        if lay:
            if before:
                lay.fixup([os.path.basename(p) for p in paths], before)
            lay.close()
        self.mgr.save_rec(self)

    @staticmethod
    def drag_effect():
        """拖拽悬停期间回报的落放效果——**只决定鼠标旁那个徽标显示什么**，一律报「移动」。

        徽标是资源管理器按我们从 DragOver 报回的效果画的；而「源方会不会删文件」是另一件事：
        源方只在 Drop 那一步按我们报的效果决定要不要清理源文件（报 Move 而文件仍在原处 →
        它会把文件删掉；报 Copy → 什么都不做）。两件事解耦，实测（悬停报 Move + 落放报 Copy）：
        徽标显示「移动」，源文件安然无恙。所以悬停一律报「移动」：与「文件被收进格子」的直觉
        一致（也和 DeskGo 的表现一致），真正搬没搬走由 drop_effect() 按实际结果回报。"""
        return Qt.MoveAction

    @staticmethod
    def drop_effect(paths):
        """落放结束时报给拖拽源的效果：**按实际结果**——源文件都不在原处了才算「移动」。
        为什么不在拖之前就定死：万一我们没搬成（文件被占用、权限不足……），报 Move 会让
        资源管理器把源文件删掉；按结果回报就绝不会出现「没搬走却被当成搬走了」。
        桌面文件拖进空白格子属于「没搬走」（文件留在桌面原路径，只是把图标收起来）→ 报
        Copy，源方于是什么都不做，文件原地不动。"""
        if paths and all(not os.path.exists(p) for p in paths):
            return Qt.MoveAction
        return Qt.CopyAction

    def _stage_dir(self):
        """拖出期间的暂存目录（桌面下的隐藏夹）。拖完会删掉，所以正常情况下桌面
        看不到它；进程被强杀留下的残留在启动时扫回桌面（见 BoxManager._upgrade_blank_boxes）。"""
        d = os.path.join(desktop_dir(), _STAGE_NAME)
        try:
            os.makedirs(d, exist_ok=True)
            _k32.SetFileAttributesW(d, ATTR_HIDDEN)
        except OSError:
            return None
        return d

    def _clear_stage_dir(self):
        """暂存夹空了就收掉，别在用户桌面上留一个隐藏目录。"""
        d = os.path.join(desktop_dir(), _STAGE_NAME)
        try:
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
                _shell_refresh(desktop_dir())
        except OSError:
            pass

    def stage_for_drag(self, paths):
        """拖出前把文件挪到桌面下的隐藏暂存夹，返回 [(原路径, 暂存路径)]。

        为什么非挪不可：空白格子里的文件**本来就在桌面上**，直接拖到桌面就是「把文件移动
        到它自己所在的目录」，资源管理器会弹「源文件名和目标文件名相同」（用户实测）。
        挪进同盘的隐藏子目录后：拖到桌面 = 一次真实的跨目录移动（文件回到原路径），拖到
        资源管理器文件夹/别的格子也都正常。顺带在这里摘掉「隐藏」属性——否则属性跟着文件
        走，落到别的文件夹里也是隐藏的（用户会以为文件丢了）。映射格子不用这一步（文件在
        别处，不存在「搬到自己的目录」问题）。"""
        if self.rec['kind'] != 'blank' or not paths:
            return []
        stage = self._stage_dir()
        if not stage:
            return []
        saved = []
        for p in paths:
            if not os.path.exists(p):
                continue
            self._show_icon(p)   # 先把隐藏属性摘掉，别让它跟着文件走
            dst = os.path.join(stage, _unique_name(stage, os.path.basename(p)))
            try:
                shutil.move(p, dst)
            except OSError:
                continue
            saved.append((p, dst))
        if saved:
            self._dragging.update(saved)   # 拖拽期间列表要按暂存路径认这几个文件
            _shell_refresh(desktop_dir())
            self.mgr.save_rec(self)
        return saved

    def finish_drag_out(self, saved):
        """拖拽收尾：暂存文件还在 = 没被搬走（取消拖拽 / 拖回格子）→ 搬回原处继续藏着；
        暂存文件没了 = 被搬走了（拖到桌面 = 移出格子；拖到文件夹/别的格子 = 不再属于这里）
        → 从记账里去掉，文件落在新位置、不再需要隐藏。"""
        if not saved:
            return
        items = self.rec.get('items') or []
        for orig, staged in saved:
            self._dragging.pop(orig, None)
            if os.path.exists(staged):
                try:
                    shutil.move(staged, orig)
                except OSError:
                    continue
                self._hide_icon(orig)   # 还在格子里：图标继续藏着
            elif orig in items:
                items.remove(orig)
                ui._dbg('box: 拖出 → 移出格子 %s' % os.path.basename(orig))
        self.rec['items'] = items
        self._clear_stage_dir()
        _shell_refresh(desktop_dir())
        self.mgr.save_rec(self)
        self.refresh()

    # ---------- 文件操作 ----------
    def import_paths(self, paths):
        """拖入文件：文件夹格子真实移动到映射目录（跨格子拖动也是移动，跳过已在目录内/
        父目录拖进自己）；空白格子只收进账本、把桌面图标藏起来（文件不动）。"""
        if self.rec['kind'] == 'blank':
            self._group_paths(paths)
            self.refresh()
            return
        dest = os.path.normpath(self.rec['path'])
        for p in paths:
            p = os.path.normpath(p)
            if os.path.dirname(p) == dest:
                continue
            if os.path.isdir(p) and (dest == p or dest.startswith(p + os.sep)):
                continue
            try:
                shutil.move(p, os.path.join(dest, _unique_name(dest, os.path.basename(p))))
            except OSError:
                pass
        self.refresh()

    def _group_paths(self, paths):
        """收进空白格子：不在桌面的先搬到桌面（「格子里的文件都在桌面」是这套模型的前提），
        再记账 + 隐藏桌面图标；同一文件从别的空白格子里移出。"""
        desk = os.path.normpath(desktop_dir())
        items = self.rec.setdefault('items', [])
        added = []
        for p in paths:
            p = os.path.normpath(p)
            if p in items:
                continue
            if os.path.normcase(os.path.dirname(p)) != os.path.normcase(desk):
                try:
                    dst = os.path.join(desk, _unique_name(desk, os.path.basename(p)))
                    shutil.move(p, dst)
                except OSError:
                    continue
                p = dst
            items.append(p)
            added.append(p)
            self._hide_icon(p)
        self.mgr.ungroup_paths(added, self)
        _shell_refresh(desk)
        self.mgr.save_rec(self)

    # ---------- 拖入（整窗，不只列表视口） ----------
    def dragEnterEvent(self, e):
        """只有文件列表视口注册了拖放目标，拖到标题栏/空白提示区/边缘时 Qt 找不到
        接受拖放的控件就整个忽略这次拖拽（鼠标变红色禁止图标，怎么都放不进去）。
        窗口自己接一份，收起状态（整格只剩标题栏）也就能收文件了。"""
        paths = self._drag_paths(e)
        if paths:
            e.setDropAction(self.drag_effect())
            e.accept()
        else:
            super(BoxWindow, self).dragEnterEvent(e)

    def dragMoveEvent(self, e):
        paths = self._drag_paths(e)
        if paths:
            e.setDropAction(self.drag_effect())
            e.accept()
        else:
            super(BoxWindow, self).dragMoveEvent(e)

    def dropEvent(self, e):
        paths = self._drag_paths(e)
        if not paths:
            super(BoxWindow, self).dropEvent(e)
            return
        self.import_paths(paths)
        e.setDropAction(self.drop_effect(paths))   # 按实际搬没搬走回报
        e.accept()

    def _drag_paths(self, e):
        """外部拖进来的本地文件路径；格子内部拖拽（source 是自己的列表）不接。"""
        if e.source() is self.list:
            return []
        return [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]

    def rename_item(self, old, new):
        """格子里改名（外壳菜单的「重命名」）：空白格子要跟着改记账——文件在桌面，
        路径变了；隐藏属性跟着文件走，账本的键也得跟着改，否则这个文件就成了
        「藏着但不在任何格子里」。"""
        items = self.rec.get('items') or []
        if old not in items:
            return
        items[items.index(old)] = new
        self.rec['items'] = items
        attrs = self.rec.get('attrs') or {}
        if old in attrs:
            attrs[new] = attrs.pop(old)
        self.mgr.save_rec(self)

    def open_path(self, path):
        # 记下是【谁】打开的：格子里的「点了就打开」问题只有这一个出口，日志里带上
        # 调用点（如 boxes.py:247 = itemDoubleClicked）比事后猜快得多。
        f = sys._getframe(1)
        ui._dbg('open: %s ← %s:%d' % (os.path.basename(path),
                                      os.path.basename(f.f_code.co_filename), f.f_lineno))
        try:
            os.startfile(path)
        except OSError:
            pass

    def reveal_path(self, path):
        subprocess.Popen(['explorer.exe', '/select,%s' % path])

    def delete_items(self, items):
        if not items:
            return
        paths = [it.data(Qt.UserRole) for it in items]
        r = QMessageBox.question(self, '删除', '把 %d 个项目放入回收站？' % len(paths),
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes:
            _recycle(paths)
            self.refresh()

    # ---------- 格子操作 ----------
    def set_collapsed(self, on, save=True):
        self.rec['collapsed'] = on
        self.pages.currentWidget().setVisible(not on)
        self.btn_collapse.setText('▼' if on else '▲')
        self.btn_collapse.setToolTip('展开' if on else '收起')
        if on:
            self.setFixedHeight(ui.sc(TITLE_H))
        else:
            self.setMinimumHeight(ui.sc(TITLE_H) + ui.sc(60))
            self.setMaximumHeight(16777215)
            self.resize(self.width(), self.rec.get('h') or ui.sc(DEF_H))
        if save:
            self.mgr.save_rec(self)

    def set_locked(self, on, save=True):
        self.rec['locked'] = on
        self.btn_lock.setText('🔒' if on else '🔓')
        self.btn_lock.setToolTip('解锁' if on else '锁定')
        if save:
            self.mgr.save_rec(self)

    def _start_rename(self):
        """双击名称 → 原地变输入框重命名（回车/失焦确认，Esc 取消）。"""
        if self.edit.isVisible():
            return
        self._edit_cancel = False
        self.edit.setText(self.rec['name'])
        self.name.hide()
        self.edit.show()
        self.edit.setFocus()
        self.edit.selectAll()

    def _finish_rename(self):
        self.edit.hide()
        self.name.show()
        name = self.edit.text().strip()
        if not self._edit_cancel and name and name != self.rec['name']:
            self.rec['name'] = name
            self.name.setText(name)
            self.mgr.save_rec(self)

    def _confirm_dissolve(self):
        """解散二次确认：空白格子提示文件会回到桌面，映射格子提示不影响原文件夹。"""
        if self.rec['kind'] == 'blank':
            detail = '里面的文件会回到桌面（取消桌面图标隐藏）。'
        else:
            detail = '只移除格子，不影响文件夹本身。'
        dlg = BoxConfirmDialog(self, '解散格子',
                               '解散格子「%s」？%s' % (self.rec['name'], detail), '解散')
        return dlg.exec_() == QDialog.Accepted

    def dissolve(self):
        """解散格子：空白格子把桌面图标放出来（文件本来就在桌面，不搬动文件）；
        映射格子只是移除格子。"""
        if not self._confirm_dissolve():
            return
        if self.rec['kind'] == 'blank':
            self.show_icons()
        self.mgr.remove(self)

    def _show_menu(self):
        menu = QMenu(self)
        grp = QActionGroup(menu)
        for key, label in SORT_CHOICES:
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self.rec.get('sort', 'name') == key)
            grp.addAction(act)
            act.triggered.connect(lambda _c=False, k=key: self._set_sort(k))
        menu.addSeparator()
        menu.addAction('解散格子', self.dissolve)
        menu.exec_(QCursor.pos())

    def _set_sort(self, key):
        self.rec['sort'] = key
        self.mgr.save_rec(self)
        self.refresh()

    # ---------- 桌面层级 ----------
    def showEvent(self, e):
        super(BoxWindow, self).showEvent(e)
        self._ensure_band()

    def _ensure_band(self):
        hwnd = int(self.winId())
        progman = ui._u32.FindWindowW('Progman', None)
        if progman and ui._u32.GetAncestor(hwnd, ui._GA_ROOT) != progman:
            self._repin()

    def _repin(self):
        """归属桌面带。对已可见的窗口 SetParent 后 win32 侧 WS_VISIBLE 会丢
        （Qt 仍认为可见，不重绘 = 窗口消失），补一句 ShowWindow(SW_SHOWNA) 恢复。
        面板在 init 时挂接（窗口还没 show）所以没踩到；格子拖拽后是可见窗口重挂，必踩。"""
        self._desk_pinned = ui.pin_to_desktop(self)
        hwnd = int(self.winId())
        if self.isVisible() and not ui._u32.IsWindowVisible(hwnd):
            _h32.ShowWindow(hwnd, 8)   # SW_SHOWNA：恢复可见但不抢焦点

    def _desktop_tick(self):
        """看门狗必须极廉：每 tick 只做一次中心命中检测。
        probe_desktop 的 5 点 WindowFromPoint 是跨进程同步调用，命中无响应的窗口会
        阻塞主线程——4 个格子每秒 48 次探测曾把界面打到转圈假死，顺序绝不能反过来。"""
        hwnd = int(self.winId())
        if not ui._u32.IsWindow(hwnd):
            self._sink_timer.stop()
            return
        self._ensure_band()
        if self._op is not None or not self._covered_by_surface():
            return
        # 真被表层压住才做完整探测找锚点抬回（表层每 ~2.5s 重建一次，属低频路径）
        if not self._desk_surface or not ui._u32.IsWindow(self._desk_surface):
            self._desk_surface, _t = ui.probe_desktop(skip=(hwnd,))
        ui.sink_to_desktop(self, self._desk_surface)

    def _on_win_event(self, _hook, event, hwnd, idObject, _idChild, _thread, _ts):
        """桌面带内窗口的 SHOW / 容器 REORDER 事件回调。只做轻量过滤，
        真正的抬回动作丢回事件循环（钩子里直接动 z-order 有风险）。"""
        try:
            if not hwnd or not self.isVisible() or self._op is not None:
                return
            if hwnd == int(self.winId()):
                return
            if idObject not in (0, -4):   # 只看窗口本身 / 客户区级别
                return
            cls = ui._class_name(hwnd)
            if cls in ui._PROG_FAMILY:
                if event != ui._EVENT_REORDER:
                    return
            else:
                sw, sh = ui._u32.GetSystemMetrics(0), ui._u32.GetSystemMetrics(1)
                if not ui._is_desktop_surface(hwnd, sw, sh):
                    return
            QTimer.singleShot(0, self._lift_if_covered)
        except Exception:
            pass

    def _unhook_win_event(self):
        if self._win_evt_hook:
            ui._u32.UnhookWinEvent(self._win_evt_hook)
            self._win_evt_hook = None

    def _lift_if_covered(self):
        """表层重排后的即时抬回：没被压住就不动（自己的沉底也会触发 REORDER，防自激回路）。"""
        if self._covered_by_surface():
            ui.sink_to_desktop(self, self._desk_surface)

    def _covered_by_surface(self):
        """格子中心被桌面整理软件的表层压住（看不见也点不到）的判定。"""
        if not self.isVisible():
            return False
        h = ui._u32.WindowFromPoint(wintypes.POINT(self.x() + self.width() // 2,
                                                   self.y() + self.height() // 2))
        mine = int(self.winId())
        sw, sh = ui._u32.GetSystemMetrics(0), ui._u32.GetSystemMetrics(1)
        while h:
            if h == mine or ui._class_name(h) in ui._PROG_FAMILY:
                return False
            if ui._is_desktop_surface(h, sw, sh):
                return True
            h = ui._u32.GetParent(h)
        return False

    # ---------- 绘制 ----------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setBrush(QColor(25, 28, 34, 140))
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.drawRoundedRect(r, ui.sc(8), ui.sc(8))
        if self.isActiveWindow():
            p.setPen(QPen(QColor(255, 255, 255, 70), 1))
            p.drawRoundedRect(r, ui.sc(8), ui.sc(8))
        p.end()

    # ---------- 拖动 / 缩放 ----------
    def _hit_edges(self, pos):
        m = ui.sc(EDGE)
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        edges = 0
        if x < m:
            edges |= 1
        if x >= w - m:
            edges |= 2
        if y < m:
            edges |= 4
        if y >= h - m:
            edges |= 8
        return edges

    _CURSORS = {1: Qt.SizeHorCursor, 2: Qt.SizeHorCursor, 4: Qt.SizeVerCursor,
                8: Qt.SizeVerCursor, 5: Qt.SizeFDiagCursor, 10: Qt.SizeFDiagCursor,
                6: Qt.SizeBDiagCursor, 9: Qt.SizeBDiagCursor}

    def _sync_cursor(self, pos):
        """按窗口坐标刷新光标：边缘给缩放箭头，其余复位（None = 不处于可调状态）。"""
        if self.rec.get('locked') or self.rec.get('collapsed'):
            self.unsetCursor()
            return
        cur = self._CURSORS.get(self._hit_edges(pos))
        if cur is None:
            self.unsetCursor()
        else:
            self.setCursor(cur)

    def eventFilter(self, obj, e):
        # 映射格子的文件夹图标：左键按下打开所在文件夹。
        # 三类鼠标事件都吃掉——按下不放给父窗口（否则进拖动）、双击不收起、
        # 双击的第二次松开也不再开一次
        if obj is self.icon and self.rec['kind'] == 'folder':
            if e.type() == e.MouseButtonPress and e.button() == Qt.LeftButton:
                self.open_path(self.rec['path'])
                return True
            if e.type() in (e.MouseButtonRelease, e.MouseButtonDblClick):
                return True
        # 名称标签双击 → 内联重命名；吃掉事件，不再传给父窗口触发收起
        if obj is self.name and e.type() == e.MouseButtonDblClick:
            self._start_rename()
            return True
        # 输入框里 Esc 取消：失焦会触发 editingFinished，借 _edit_cancel 跳过提交
        if obj is self.edit and e.type() == e.KeyPress and e.key() == Qt.Key_Escape:
            self._edit_cancel = True
            self.edit.clearFocus()
            return True
        # 列表视口会吃掉左键按下（选中项），父窗口收不到——底部边缘和两个下角的
        # 缩放从这里起；起缩放后移动/松开同样发给视口，直接在过滤器里驱动到底。
        if obj is self.list.viewport():
            if e.type() == e.MouseButtonPress and e.button() == Qt.LeftButton \
                    and not self.rec.get('locked') and not self.rec.get('collapsed'):
                edges = self._hit_edges(obj.mapTo(self, e.pos()))
                if edges:
                    self._op = ('resize', edges, e.globalPos(), self.geometry())
                    self._press_pos = e.globalPos()
                    return True
            if self._op and self._op[0] == 'resize':
                if e.type() == e.MouseMove:
                    self._apply_resize(e.globalPos())
                    return True
                if e.type() == e.MouseButtonRelease:
                    self._finish_op(e.globalPos())
                    return True
        # 子控件上的 MouseMove 转成窗口坐标同步光标（子控件不设光标，跟随窗口）
        if e.type() == e.MouseMove and not self._op:
            self._sync_cursor(obj.mapTo(self, e.pos()))
        return super(BoxWindow, self).eventFilter(obj, e)

    def enterEvent(self, e):
        self.unsetCursor()   # 从窗外划入时复位，不残留上次的缩放箭头
        super(BoxWindow, self).enterEvent(e)

    def leaveEvent(self, e):
        self.unsetCursor()
        super(BoxWindow, self).leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton or self.rec.get('locked'):
            super(BoxWindow, self).mousePressEvent(e)
            return
        edges = 0 if self.rec.get('collapsed') else self._hit_edges(e.pos())
        if edges:
            self._op = ('resize', edges, e.globalPos(), self.geometry())
        elif e.pos().y() < ui.sc(TITLE_H):
            self._op = ('move', 0, e.globalPos(), self.geometry())
        else:
            super(BoxWindow, self).mousePressEvent(e)
        if self._op:
            self._press_pos = e.globalPos()

    def mouseMoveEvent(self, e):
        if not self._op:
            self._sync_cursor(e.pos())
            super(BoxWindow, self).mouseMoveEvent(e)
            return
        kind, edges, start_pos, start_geo = self._op
        if kind == 'move':
            self.move(start_geo.topLeft() + (e.globalPos() - start_pos))
            self.activateWindow()
        else:
            self._apply_resize(e.globalPos())

    def _apply_resize(self, global_pos):
        """按当前 _op 的边缘掩码应用缩放（mouseMoveEvent 与视口事件过滤器共用）。"""
        _kind, edges, start_pos, start_geo = self._op
        delta = global_pos - start_pos
        r = QRect(start_geo)
        if edges & 1:
            r.setLeft(start_geo.left() + delta.x())
        if edges & 2:
            r.setRight(start_geo.right() + delta.x())
        if edges & 4:
            r.setTop(start_geo.top() + delta.y())
        if edges & 8:
            r.setBottom(start_geo.bottom() + delta.y())
        if r.width() >= self.minimumWidth() and r.height() >= self.minimumHeight():
            self.setGeometry(r)
        self.activateWindow()

    def mouseReleaseEvent(self, e):
        if self._op:
            self._finish_op(e.globalPos())
        super(BoxWindow, self).mouseReleaseEvent(e)

    def _finish_op(self, global_pos):
        """拖动/缩放收尾（mouseReleaseEvent 与视口事件过滤器共用）。"""
        self._op = None
        if self._press_pos is not None and \
                (global_pos - self._press_pos).manhattanLength() > 4:
            self._last_drag_ts = time.time()
        self._press_pos = None
        self._clamp_to_screen()   # 拖出屏幕会再也够不着标题栏，钳回来
        self.rec['x'], self.rec['y'] = self.x(), self.y()
        if not self.rec.get('collapsed'):
            self.rec['w'], self.rec['h'] = self.width(), self.height()
        self.mgr.save_rec(self)
        # 不动 z-order：格子保持当前层级（拖拽激活时浮在应用之上），
        # 失焦也不沉底——用户明确要求：除双击桌面/解散外，格子永不消失

    def _clamp_to_screen(self):
        """保证至少标题栏露在屏幕内（面板同款思路，见 FloatingPanel._clamp_to_screen）。"""
        ag = QApplication.primaryScreen().availableGeometry()
        x = min(max(self.x(), ag.left() - self.width() + 80), ag.right() - 80)
        y = min(max(self.y(), ag.top()), ag.bottom() - 40)
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def mouseDoubleClickEvent(self, e):
        # 同上：Qt 对右键也发双击，不设防的话「快速两次右键标题」会平白收起格子。
        # 双击只认左键。
        if e.button() != Qt.LeftButton:
            e.accept()
            return
        # 快速连续两次点标题拖拽时，第二次 press 会被系统判成双击：
        # 若前一次点击发生了位移（是在拖不是在点），或在拖拽途中，都不收起
        if self._op is not None or time.time() - self._last_drag_ts < 0.5:
            return super(BoxWindow, self).mouseDoubleClickEvent(e)
        if e.pos().y() < ui.sc(TITLE_H) and not self._hit_edges(e.pos()):
            self.set_collapsed(not self.rec['collapsed'])
        super(BoxWindow, self).mouseDoubleClickEvent(e)


def find_desktop_listview():
    """桌面图标所在的 SysListView32：通常在 Progman/SHELLDLL_DefView 下，
    部分环境（壁纸软件等）会被挪到某个 WorkerW 下。找不到返回 None。"""
    def _lv_under(parent):
        if not parent:
            return None
        dv = ui._u32.FindWindowExW(parent, None, 'SHELLDLL_DefView', None)
        return ui._u32.FindWindowExW(dv, None, 'SysListView32', None) if dv else None
    lv = _lv_under(ui._u32.FindWindowW('Progman', None))
    if lv:
        return lv
    w = None
    while True:
        w = ui._u32.FindWindowExW(None, w, 'WorkerW', None)
        if not w:
            return None
        lv = _lv_under(w)
        if lv:
            return lv


class _LVITEMW(ctypes.Structure):
    _fields_ = [('mask', wintypes.UINT), ('iItem', ctypes.c_int),
                ('iSubItem', ctypes.c_int), ('state', wintypes.UINT),
                ('stateMask', wintypes.UINT), ('pszText', ctypes.c_void_p),
                ('cchTextMax', ctypes.c_int), ('iImage', ctypes.c_int),
                ('lParam', ctypes.c_void_p), ('iIndent', ctypes.c_int),
                ('iGroupId', ctypes.c_int), ('cColumns', wintypes.UINT),
                ('puColumns', ctypes.c_void_p), ('piColFmt', ctypes.c_void_p),
                ('iGroup', ctypes.c_int)]


class _DesktopIconLayout(object):
    """桌面图标位置的快照与修正：跨进程枚举 SysListView32 各项的显示名与坐标
    （LVM_GETITEMTEXTW / LVM_GETITEMPOSITION，结构体开在 explorer 地址空间，
    与 _desktop_icon_at 同一套做法），摆位用 LVM_SETITEMPOSITION
    （lParam 直接打包坐标，不用跨进程内存）。

    为什么需要它：空白格子释放文件（还原隐藏属性）后，重新出现的图标由 Explorer
    自行摆位——落在第一列从上往下第一个空位，用户眼里就是「跑到屏幕最左上角」；
    桌面满员（没有空位）时还会把原有图标挤下去，而被挤的图标不会回弹（位置记忆
    当场被改写），再开程序也救不回来。所以释放时：先快照全部图标位置 → 还原属性
    → 等新图标出现 → 把新图标挪到桌面末尾行（最后一行之下另起一行，全是空位
    不挤人）→ 被挤的原有图标按快照摆回。
    实测依据（Win11 自由摆放桌面）：新图标落点 = 第一列首个空位；SET 到已占用
    位置 = 占用者被挤到下一空位；SET 到空位附近的坐标会被吸附到最近网格位——
    所以目标位置只按网格估算即可，网格步长用 LVM_GETITEMSPACING 取。

    自动排列（LVS_AUTOARRANGE）的桌面：位置完全由排序规则决定，SET 会被立刻
    重排掉，干预无意义——检测到就不插手（ok=False，各方法早退）。"""

    _TX = 512          # 文本缓冲（字符数）
    _PT_OFF = 2048     # POINT 在远程缓冲里的偏移

    def __init__(self):
        self.ok = False
        self.lv = self.hp = self.buf = None
        self.rc = wintypes.RECT()
        self.cx = self.cy = 0
        lv = find_desktop_listview()
        if not lv:
            return
        style = _h32.GetWindowLongW(lv, _GWL_STYLE) & 0xFFFFFFFF
        if style & _LVS_AUTOARRANGE:
            return
        pid = wintypes.DWORD()
        ui._u32.GetWindowThreadProcessId(lv, ctypes.byref(pid))
        hp = _k32.OpenProcess(0x0008 | 0x0020 | 0x0010, False, pid.value)
        if not hp:
            return
        buf = _k32.VirtualAllocEx(hp, None, 4096, 0x1000, 0x04)   # MEM_COMMIT | PAGE_READWRITE
        if not buf:
            _k32.CloseHandle(hp)
            return
        sp = _h32.SendMessageW(lv, _LVM_GETITEMSPACING, 0, 0)
        self.cx, self.cy = sp & 0xFFFF, (sp >> 16) & 0xFFFF
        _h32.GetClientRect(lv, ctypes.byref(self.rc))
        self.lv, self.hp, self.buf = lv, hp, buf
        self.ok = bool(self.cx and self.cy)

    def close(self):
        if self.buf:
            _k32.VirtualFreeEx(self.hp, self.buf, 0, 0x8000)   # MEM_RELEASE
        if self.hp:
            _k32.CloseHandle(self.hp)
        self.ok = False

    def _write(self, off, data, size):
        nw = ctypes.c_size_t()
        return _k32.WriteProcessMemory(self.hp, self.buf + off, data, size,
                                       ctypes.byref(nw))

    def _read(self, off, data, size):
        nr = ctypes.c_size_t()
        return _k32.ReadProcessMemory(self.hp, self.buf + off, data, size,
                                      ctypes.byref(nr))

    def enum_icons(self):
        """[(index, 显示名, x, y)]：x/y 是 ListView 客户区坐标。"""
        out = []
        if not self.ok:
            return out
        ss = ctypes.sizeof(_LVITEMW)
        n = _h32.SendMessageW(self.lv, _LVM_GETITEMCOUNT, 0, 0)
        for i in range(n):
            item = _LVITEMW()
            item.mask = 1                      # LVIF_TEXT
            item.iItem = i
            item.pszText = self.buf + ss
            item.cchTextMax = self._TX
            if not self._write(0, ctypes.byref(item), ss):
                break
            _h32.SendMessageW(self.lv, _LVM_GETITEMTEXTW, i, self.buf)
            wbuf = (ctypes.c_wchar * self._TX)()
            self._read(ss, wbuf, self._TX * 2)
            pt = wintypes.POINT()
            self._write(self._PT_OFF, ctypes.byref(pt), ctypes.sizeof(pt))
            _h32.SendMessageW(self.lv, _LVM_GETITEMPOSITION, i, self.buf + self._PT_OFF)
            self._read(self._PT_OFF, ctypes.byref(pt), ctypes.sizeof(pt))
            out.append((i, wbuf.value, pt.x, pt.y))
        return out

    def snapshot(self):
        """{小写显示名: (x, y)}；不可用（自动排列 / 找不到桌面层）返回 None。"""
        if not self.ok:
            return None
        return {n.lower(): (x, y) for _, n, x, y in self.enum_icons()}

    def _set_pos(self, idx, x, y):
        _h32.SendMessageW(self.lv, _LVM_SETITEMPOSITION, idx,
                          ((y & 0xFFFF) << 16) | (x & 0xFFFF))

    @staticmethod
    def _match(icons, before, basename):
        """在枚举里找刚释放的那个文件：显示名匹配（全名优先，系统隐藏扩展名时
        退到主名）；撞名（桌面原有同主名文件）时挑「位置不在快照里」的新项。"""
        full, stem = basename.lower(), os.path.splitext(basename)[0].lower()
        cands = [c for c in icons if c[1].lower() in (full, stem)]
        cands.sort(key=lambda c: c[1].lower() != full)
        if len(cands) <= 1:
            return cands[0] if cands else None
        for c in cands:
            if before.get(c[1].lower()) != (c[2], c[3]):
                return c
        return None

    def fixup(self, basenames, before, timeout=3.0):
        """释放的图标出现后统一摆位：新图标挪到桌面末尾行，被挤的原有图标按
        快照摆回。basenames = 释放文件的文件名列表，before = 释放前快照。"""
        if not self.ok or not before:
            return
        # SHCNF_FLUSH 只是把通知投进 explorer 的队列，图标真正加进 ListView 有
        # 延迟（实测 0~0.6s+），轮询等到全部出现；超时按已出现的修
        t0 = time.time()
        found = {}
        while time.time() - t0 < timeout:
            icons = self.enum_icons()
            found = {}
            for b in basenames:
                m = self._match(icons, before, b)
                if m:
                    found[b] = m
            if len(found) >= len(basenames):
                break
            time.sleep(0.1)
        if not found:
            return
        # 末尾行 = 快照里最后一行之下另起一行（必是空行，SET 不挤人）；屏幕下沿
        # 放不下就塞到最后一行最右图标之后（同样是空位）
        xs = [x for x, _ in before.values()]
        ys = [y for _, y in before.values()]
        bx, by = min(xs), min(ys)
        k_last = max(int(round((y - by) / float(self.cy))) for y in ys)
        y0 = by + self.cy * (k_last + 1)
        x0 = bx
        if y0 + self.cy > self.rc.bottom:
            y0 = by + self.cy * k_last
            x0 = max(x for x, y in before.values()
                     if int(round((y - by) / float(self.cy))) == k_last) + self.cx
        released = set()
        x, y = x0, y0
        for b in basenames:
            m = found.get(b)
            if not m:
                continue
            if x + self.cx > self.rc.right:
                x, y = x0, y + self.cy
            if y + self.cy > self.rc.bottom:
                continue   # 屏幕摆满：这个留在 Explorer 给的位置
            self._set_pos(m[0], x, y)
            released.add(m[0])
            x += self.cx
        # 原有图标按快照摆回：被挤的连锁两轮内收敛（每摆正一个就腾出一个空位）
        for _ in range(2):
            moved = []
            for i, n, ix, iy in self.enum_icons():
                if i in released:
                    continue
                pos = before.get(n.lower())
                if pos and pos != (ix, iy):
                    moved.append((i, pos))
            if not moved:
                break
            for i, (px, py) in moved:
                self._set_pos(i, px, py)


_LVM_HITTEST = 0x1012

def _desktop_icon_at(lv, pt):
    """SysListView32 上 pt（屏幕坐标）是否命中图标：跨进程 LVM_HITTEST
    （结构体必须开在 explorer 的地址空间里，SendMessage 才读得到）。
    命中返回 True；任何一步失败按未命中处理——宁可当空白处。"""
    class _LVHITTESTINFO(ctypes.Structure):
        _fields_ = [('pt', wintypes.POINT), ('flags', wintypes.UINT),
                    ('iItem', ctypes.c_int)]
    cpt = wintypes.POINT(pt.x, pt.y)
    _h32.ScreenToClient(lv, ctypes.byref(cpt))
    pid = wintypes.DWORD()
    ui._u32.GetWindowThreadProcessId(lv, ctypes.byref(pid))
    # PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ
    hp = _k32.OpenProcess(0x0008 | 0x0020 | 0x0010, False, pid.value)
    if not hp:
        return False
    try:
        buf = _k32.VirtualAllocEx(hp, None, ctypes.sizeof(_LVHITTESTINFO),
                                  0x1000, 0x04)   # MEM_COMMIT | PAGE_READWRITE
        if not buf:
            return False
        try:
            info = _LVHITTESTINFO(cpt, 0, -1)
            nw = ctypes.c_size_t()
            if not _k32.WriteProcessMemory(hp, buf, ctypes.byref(info),
                                           ctypes.sizeof(info), ctypes.byref(nw)):
                return False
            return _h32.SendMessageW(lv, _LVM_HITTEST, 0, buf) != -1
        finally:
            _k32.VirtualFreeEx(hp, buf, 0, 0x8000)   # MEM_RELEASE
    finally:
        _k32.CloseHandle(hp)


class _GUID(ctypes.Structure):
    _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD),
                ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]


def _guid(text):
    """'{000214E4-0000-0000-C000-000000000046}' → GUID 结构体。"""
    h = text.strip('{}').split('-')
    return _GUID(int(h[0], 16), int(h[1], 16), int(h[2], 16),
                 (ctypes.c_ubyte * 8)(*bytes.fromhex(h[3] + h[4])))


_IID_IShellFolder = _guid('{000214E6-0000-0000-C000-000000000046}')
_IID_IContextMenu = _guid('{000214E4-0000-0000-C000-000000000046}')


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG),
                ('hwnd', wintypes.HWND), ('lpVerb', wintypes.LPCWSTR),
                ('lpFile', wintypes.LPCWSTR),
                ('lpParameters', wintypes.LPCWSTR), ('lpDirectory', wintypes.LPCWSTR),
                ('nShow', ctypes.c_int), ('hInstApp', ctypes.c_void_p),
                ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR),
                ('hkeyClass', ctypes.c_void_p), ('dwHotKey', wintypes.DWORD),
                ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]


def _com_fn(obj, idx, restype, *argtypes):
    """取 COM 对象的第 idx 个虚函数（vtable 头三格固定是 IUnknown），包成可调用对象。"""
    vtbl = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p)).contents.value,
                       ctypes.POINTER(ctypes.c_void_p))
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[idx])


def _progid_verbs(path):
    """读文件 progid 的 shell 动词（HKCR 合并视图，含 command 子键才算有效），
    返回 [(verb 名, 显示名, 命令行)]，open 排最前。显示名取动词键默认值（如 '打开(&O)'），
    没有则按常见名映射。壳默认菜单不含用户范围注册的 progid 动词（实测），
    由调用方补进菜单顶部。"""
    import winreg
    verbs = []
    if os.path.isdir(path):
        return verbs
    ext = os.path.splitext(path)[1]
    if not ext:
        return verbs
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ext) as k:
            progid = winreg.QueryValue(k, None)
        if not progid:
            return verbs
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + r'\shell') as sh:
            i = 0
            while True:
                try:
                    v = winreg.EnumKey(sh, i)
                except OSError:
                    break
                i += 1
                cmd = None
                try:
                    with winreg.OpenKey(sh, v + r'\command') as ck:
                        cmd = winreg.QueryValue(ck, None)
                except OSError:
                    continue
                try:
                    label = winreg.QueryValue(sh, v)   # 默认值可能是空串（只给了 command）
                except OSError:
                    label = None
                if not label:
                    label = {'open': '打开(&O)', 'edit': '编辑(&E)',
                             'print': '打印(&P)'}.get(v, v)
                verbs.append((v, label, cmd))
    except OSError:
        pass
    verbs.sort(key=lambda t: 0 if t[0] == 'open' else 1)
    return verbs


def _star_shell_verbs():
    """HKCR\\*\\shell 下的静态动词（如「使用 ToDesk 快传文件」）：壳默认菜单不合并
    *\\shell（实测），手工补。只收带 command 子键的纯命令动词；IExplorerCommand 型
    （如 Notepad++ 的 ANotepad++64，宿主接口在非 Explorer 环境加载不了）跳过。
    返回 [(显示名, 图标路径或 None, exe, 参数模板)]。"""
    import winreg
    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'*\shell') as sh:
            i = 0
            while True:
                try:
                    v = winreg.EnumKey(sh, i)
                except OSError:
                    break
                i += 1
                base = r'*\shell\%s' % v
                try:
                    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, base + r'\command') as ck:
                        cmd = winreg.QueryValue(ck, None)
                except OSError:
                    continue
                try:
                    label = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, base)
                except OSError:
                    label = v
                icon = None
                try:
                    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, base) as bk:
                        try:
                            icon = winreg.QueryValueEx(bk, 'Icon')[0]
                        except OSError:
                            icon = None
                except OSError:
                    pass
                exe, params = _split_command(cmd)
                if exe:
                    out.append((label, icon, exe, params))
    except OSError:
        pass
    return out


def _split_command(line):
    """拆命令行模板：带引号的 exe 路径 + 参数模板。空模板返回 (None, '')。"""
    line = (line or '').strip()
    if not line:
        return None, ''
    if line.startswith('"'):
        end = line.find('"', 1)
        if end > 0:
            return line[1:end], line[end + 1:].strip()
    parts = line.split(None, 1)
    return parts[0], (parts[1] if len(parts) > 1 else '')


def _verb_hicon(icon_val, exe):
    """动词图标：优先注册表 Icon 值（'path[,idx]'），否则 exe 的 0 号图标。返回 HICON 或 None。"""
    path, idx = None, 0
    if icon_val:
        parts = icon_val.rsplit(',', 1)
        path = parts[0].strip('"')
        if len(parts) > 1:
            try:
                idx = int(parts[1])
            except ValueError:
                idx = 0
    else:
        path = exe
    if not path or not os.path.isfile(path):
        return None
    h = ctypes.c_void_p()
    _s32.ExtractIconExW.restype = wintypes.UINT
    _s32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                    ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    if _s32.ExtractIconExW(path, idx, None, ctypes.byref(h), 1) > 0 and h:
        return h.value
    return None


class _ICONINFO(ctypes.Structure):
    _fields_ = [('fIcon', wintypes.BOOL), ('xHotspot', wintypes.DWORD),
                ('yHotspot', wintypes.DWORD), ('hbmMask', ctypes.c_void_p),
                ('hbmColor', ctypes.c_void_p)]


class _MENUITEMINFOW(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('fMask', wintypes.UINT), ('fType', wintypes.UINT),
                ('fState', wintypes.UINT), ('wID', wintypes.UINT), ('hSubMenu', ctypes.c_void_p),
                ('hbmpChecked', ctypes.c_void_p), ('hbmpUnchecked', ctypes.c_void_p),
                ('dwItemData', ctypes.c_void_p), ('dwTypeData', wintypes.LPWSTR),
                ('cch', wintypes.UINT), ('hbmpItem', ctypes.c_void_p)]


def _set_item_icon(hmenu, pos, hicon):
    """给菜单项挂图标：MIIM_BITMAP 要 HBITMAP，借 GetIconInfo 从 HICON 取 hbmColor。"""
    if not hicon:
        return
    info = _ICONINFO()
    _h32.GetIconInfo.restype = wintypes.BOOL
    _h32.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    if not _h32.GetIconInfo(hicon, ctypes.byref(info)) or not info.hbmColor:
        return
    mii = _MENUITEMINFOW()
    mii.cbSize = ctypes.sizeof(mii)
    mii.fMask = 0x00000080   # MIIM_BITMAP（0x20 是 MIIM_DATA，写错掩码图标静默不生效）
    mii.hbmpItem = info.hbmColor
    _h32.SetMenuItemInfoW(hmenu, pos, 1, ctypes.byref(mii))


def _ux_dark_menu():
    """壳菜单跟随系统明暗：uxtheme 135 号序数 SetPreferredAppMode（0=默认 1=允许暗色
    2=强制暗色 3=强制亮色）。不设的话 TrackPopupMenu 在深色系统上也是浅色菜单。"""
    try:
        fn = ctypes.windll.uxtheme[135]
        fn.restype = ctypes.c_int
        fn.argtypes = [ctypes.c_int]
        fn(3 if sysutil.system_uses_light_theme() else 2)
    except Exception:
        pass


def _menu_labels(hmenu):
    """菜单里已有的显示名集合（去掉 (&X) 助记符），用于补动词时去重。"""
    out = set()
    n = _h32.GetMenuItemCount(hmenu)
    for i in range(n):
        buf = ctypes.create_unicode_buffer(128)
        _h32.GetMenuStringW(hmenu, i, buf, 128, 0x00000400)   # MF_BYPOSITION
        if buf.value:
            out.add(buf.value.split('(')[0])
    return out


def _zshell_host():
    """定位 zshell_host.exe（原生外壳菜单宿主，与资源管理器逐项一致）：
    frozen 时在 exe 同目录，源码运行时在 native\\ 下。缺失返回 None。
    必须独立进程：Defender 扫描（EPP 扩展）在真正的 python.exe 进程里拒绝加项
    （逆向结论见 AGENTS.md），只有原生宿主进程能拿到完整菜单。"""
    if getattr(sys, 'frozen', False):
        cand = os.path.join(os.path.dirname(sys.executable), 'zshell_host.exe')
    else:
        cand = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'native', 'zshell_host.exe')
    return cand if os.path.isfile(cand) else None


class _HostDaemon(QObject):
    """常驻 zshell_host.exe 服务模式（--serve）：进程常驻 + 启动时预热壳扩展 DLL，
    每次右键只写一行管道请求，省掉每次新建进程 + 重载全部壳扩展的 ~500ms。
    请求/响应按 FIFO 配对：结果回调队列与请求一一对应。"""

    result = pyqtSignal(int)

    def __init__(self):
        super(_HostDaemon, self).__init__()
        self.proc = None
        self.callbacks = []          # 每次请求对应的 on_rename（FIFO）
        self.result.connect(self._on_result)
        self._req_key = None         # 在途请求的 (hwnd, paths)——重复请求去重
        self._req_ts = 0.0           # 在途请求发出时间（卡死看门狗用）
        self.closed_at = 0.0         # 最近一次菜单关闭的时刻（格子双击守卫用，见 BoxList）

    def ensure(self):
        if self.proc is not None and self.proc.poll() is None:
            return True
        self.callbacks = []          # 旧宿主已死，待配对回调全部作废（GUI 线程清理）
        host = _zshell_host()
        if not host:
            return False
        try:
            self.proc = subprocess.Popen(
                [host, '--serve'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=0x08000000)   # CREATE_NO_WINDOW
        except OSError:
            self.proc = None
            return False
        # 记一笔「这次用的是哪个宿主」：排查时最常见的坑就是面板没重启、还在跑旧宿主
        #（run.cmd 对已在运行的面板只切显隐，不会重启！），加上 exe 的 mtime 一眼可辨。
        try:
            mt = time.strftime('%m-%d %H:%M:%S',
                               time.localtime(os.path.getmtime(host)))
            ui._dbg('host 启动 pid=%s exe_mtime=%s path=%s'
                    % (self.proc.pid, mt, host))
        except OSError:
            pass
        threading.Thread(target=self._read_loop, daemon=True).start()
        return True

    def _read_loop(self):
        # 独立线程只读管道发信号，绝不碰 Qt 对象（同 DesktopClickHook 的铁律）
        for raw in self.proc.stdout:
            line = raw.decode('utf-8', 'replace').strip()
            if line.startswith('R '):
                try:
                    self.result.emit(int(line[2:]))
                except ValueError:
                    pass
        # 进程死了：不在此清 callbacks——读线程与 GUI 线程共享该列表无锁，
        # 重启后新请求的回调可能被旧读线程误清；改由 ensure() 在重启前清理。

    def request(self, hwnd, paths, on_rename):
        key = (int(hwnd), tuple(paths))
        if self.callbacks:
            if time.time() - self._req_ts > 15:
                # 看门狗：上一请求 15s 无响应且又来了新请求 = 宿主卡死
                # （菜单开着时用户再点右键会先经 TPM_RECURSE 取消旧菜单，
                # R 必然已回，所以在途 15s+ 还有新请求不可能是正常弹窗）。
                # 杀掉重启自愈——宿主与它弹的菜单一起消失，前台与输入随即释放。
                ui._dbg('ctxmenu: 宿主 15s 无响应，杀掉重启')
                try:
                    self.proc.kill()
                except (OSError, AttributeError):
                    pass
                self.proc = None
                self.callbacks = []
            elif self._req_key == key:
                # 在途去重：同一次物理右键可能经两条路径各触发一次请求
                # （TPM_RECURSE 按下时转发 + 抬起时 DefWindowProc 再发
                # WM_CONTEXTMENU）。只对【在途】请求去重——上一菜单已关闭后
                # 的同项右键是合法的重定向连击，绝不能吞（旧版 1.5s 时间窗
                # 会把它吃掉，表现为「首次右键不弹，第二次才行」）。
                return True
        if not self.ensure():
            return False
        # 把「置前台」权限【只】授给宿主自己的 pid：宿主弹菜单前要 SetForegroundWindow
        # 它的隐藏属主窗——这是必须的（菜单要靠前台线程的鼠标捕获才能被「点别处」关掉，
        # 实测不抢前台时点菜单外关不掉菜单）。用 ASFW_ANY 则等于把权限敞开给桌面上任意
        # 进程、关掉系统防抢前台的那道锁，**绝不能用**。键盘误执行菜单项的问题由宿主侧
        # 线程级 WH_GETMESSAGE 钩子解决（见 AGENTS.md ⑨-b），不靠这里的授权。
        try:
            _h32.AllowSetForegroundWindow(self.proc.pid)
        except OSError:
            pass
        try:
            head = 'M %d %d\n' % (int(hwnd), len(paths))
            body = ''.join(p + '\n' for p in paths).encode('utf-8')
            self.proc.stdin.write(head.encode('ascii') + body)
            self.proc.stdin.flush()
        except (OSError, ValueError):
            self.proc = None
            return False
        self.callbacks.append((on_rename, time.time()))   # 每个请求各带自己的发出时刻
        self._req_key = key
        self._req_ts = time.time()
        return True

    def _on_result(self, rc):
        self.closed_at = time.time()
        # 记「宿主回了什么、这一次花了多久」：出事复盘时若只有发出去的请求、没有
        # 回来的应答，就无从判断宿主当时是否还健康（2026-10 冻结事故就吃了这个亏）。
        # 时间必须按【每个请求自己】的发出时刻算——连点时会有多个请求在途，拿最新的
        # 时间戳算会把先回的那条算成很短（真踩过：7 连点的日志因此对不上号）。
        item = self.callbacks.pop(0) if self.callbacks else None
        cb, sent_at = item if item else (None, 0.0)
        if sent_at:
            ui._dbg('ctxmenu: R=%d 用时=%.2fs 在途=%d'
                    % (rc, time.time() - sent_at, len(self.callbacks)))
        if rc == 2 and cb:
            cb()

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.stdin.close()   # 宿主 stdin 关闭即退出
            except OSError:
                pass
        self.proc = None


_daemon = None


def _get_daemon():
    global _daemon
    if _daemon is None:
        _daemon = _HostDaemon()
        QApplication.instance().aboutToQuit.connect(_daemon.stop)
    return _daemon


def _menu_open_or_just_closed(grace=0.25):
    """外壳菜单正开着，或刚刚（grace 秒内）被点关掉。

    菜单是宿主进程弹的，**点它会穿透到下面的格子窗口上**（实测：菜单弹在第一行、左键点
    没被菜单盖住的另一行，格子列表照样收到一次完整的 press/release/itemClicked）。所以
    「菜单刚关掉」这个窗口里落在格子列表上的左键，其实就是「点掉那个菜单」的那一下。
    callbacks 非空 = 请求在途 = 菜单还开着（应答回来才算关）；刚关掉的一瞬按下也可能
    先于应答信号到达，所以再留一个 grace 窗口。"""
    d = _daemon
    if d is None:
        return False
    return bool(d.callbacks) or (time.time() - d.closed_at) < grace


def shell_context_menu(hwnd, paths, x, y, on_rename=None):
    """在 (x, y) 弹出 paths 的系统外壳右键菜单（资源管理器同款）。
    优先常驻宿主 zshell_host.exe --serve（SHCreateDefaultContextMenu + SetSite，
    含 Defender 扫描 / IExplorerCommand 项 / 全量图标，菜单随系统明暗；
    x/y 仅回退路径用——宿主自己取 GetCursorPos，避免 Qt 逻辑像素在 DPI 缩放下偏移）。
    宿主缺失回退 ctypes 实现（CDefFolderMenu_Create2，少几个需要宿主环境的扩展项）。
    on_rename：宿主路径下用户选「重命名」时回调（异步，菜单关闭后触发）。
    返回 True=已接管；'rename'=ctypes 路径选了重命名；False=回退内置菜单。"""
    if not paths:
        return False
    ui._dbg('ctxmenu: %d 项, 首个=%s' % (len(paths), os.path.basename(paths[0])))
    # 置前台权限在 _HostDaemon.request 里授（只给宿主自己的 pid）：不授权的话，
    # 焦点刚变过（Win+D 回桌面 / 切过别的程序）的首次右键，宿主 SetForegroundWindow
    # 失败，菜单弹出即被取消——表现为首次右键无效。
    if _get_daemon().request(hwnd, paths, on_rename):
        return True
    # GUI 线程现在已是 STA（main.pyw 入口初始化），这里只是确认；S_OK 才是我们初始化的，
    # 退出才配对释放（别写成 0——那是 COINIT_MULTITHREADED）。
    own_com = (_o32.CoInitializeEx(None, 0x2) == 0)
    pidls = []      # 待 ILFree 的绝对 PIDL
    objs = []       # 待 Release 的接口指针
    hmenu = None
    try:
        # 每个文件：SHParseDisplayName 拿绝对 PIDL，SHBindToParent 拆父文件夹 + 子 PIDL
        # （子 PIDL 指向绝对 PIDL 内部，生命周期跟它走）。格子列表必然同目录，
        # 父文件夹只留第一份，重复的当场 Release。
        psf_dir, kids = None, []
        for p in paths:
            fp = ctypes.c_void_p()
            if _s32.SHParseDisplayName(p, None, ctypes.byref(fp), 0, None) != 0 or not fp:
                continue
            pidls.append(fp.value)
            psf, kid = ctypes.c_void_p(), ctypes.c_void_p()
            if _s32.SHBindToParent(fp.value, ctypes.byref(_IID_IShellFolder),
                                   ctypes.byref(psf), ctypes.byref(kid)) != 0 or not psf:
                continue
            if psf_dir is None:
                psf_dir = psf.value
                objs.append(psf_dir)
            else:
                _com_fn(psf.value, 2, wintypes.UINT)(psf.value)   # 重复父目录：Release
            if kid:
                kids.append(kid.value)
        if psf_dir is None or not kids:
            return False
        arr = (ctypes.c_void_p * len(kids))(*kids)
        # CDefFolderMenu_Create2 直接造 IContextMenu（GetUIObjectOf 在某些系统组件
        # 上的 vtable 布局实测不可依赖，这个导出函数是壳菜单的标准做法）。
        pcm = ctypes.c_void_p()
        if _s32.CDefFolderMenu_Create2(None, hwnd, len(kids), arr, psf_dir,
                                       None, 0, None, ctypes.byref(pcm)) != 0 or not pcm:
            return False
        objs.append(pcm.value)
        hmenu = _h32.CreatePopupMenu()
        if not hmenu:
            return False
        qcm = _com_fn(pcm.value, 3, ctypes.c_long,   # IContextMenu::QueryContextMenu
                      ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                      ctypes.c_uint, ctypes.c_uint)
        # CMF_EXPLORE|CMF_CANRENAME：对齐资源管理器（不带 CANRENAME 菜单里没有「重命名」；
        # 扩展动词仍按壳规则按住 Shift 才出）。注意别传 ahKeys——传了会整个替换掉
        # 壳默认的动词/扩展合并，菜单反而只剩壳内置项（实测）。
        if qcm(pcm.value, hmenu, 0, 1, 0x7FFF, 0x14) < 0:
            return False
        _ux_dark_menu()
        # 顶部补动词：① progid 动词（打开 / 编辑，壳默认菜单不合并用户范围注册的 progid）；
        # ② *\shell 静态动词（如「使用 ToDesk 快传文件」，壳默认菜单不合并 *\shell）。
        # 已存在的不重复补；第 0 项加粗对齐资源管理器。
        inserted = {}
        seen = _menu_labels(hmenu)
        pos = 0
        for verb, label, cmd in _progid_verbs(paths[0]):
            if label.split('(')[0] in seen:
                continue
            _h32.InsertMenuW(hmenu, pos, 0x00000400, 0x7F00 + pos, label)
            inserted[0x7F00 + pos] = ('verb', verb)
            _set_item_icon(hmenu, pos, _verb_hicon(None, _split_command(cmd)[0]))
            pos += 1
        for label, icon, exe, params in _star_shell_verbs():
            if label.split('(')[0] in seen:
                continue
            _h32.InsertMenuW(hmenu, pos, 0x00000400, 0x7F00 + pos, label)
            inserted[0x7F00 + pos] = ('cmd', (exe, params))
            _set_item_icon(hmenu, pos, _verb_hicon(icon, exe))
            pos += 1
        if pos:
            _h32.SetMenuDefaultItem(hmenu, 0, 1)
        cmd = _h32.TrackPopupMenu(hmenu, 0x0100, x, y, 0, hwnd, None)   # TPM_RETURNCMD
        if cmd in inserted:
            kind, payload = inserted[cmd]
            if kind == 'verb':
                _shell_invoke_async(payload, paths)
            else:
                exe, params = payload
                for f in paths:
                    _shell_exec_async(exe, params.replace('%1', '"%s"' % f))
            return True
        if cmd:
            # 动词字符串 → ShellExecuteEx 执行。不直接用 IContextMenu::InvokeCommand：
            # CDefFolderMenu_Create2 的对象在无站点（SetSite）环境下对动词一律 E_FAIL（实测）。
            gcs = _com_fn(pcm.value, 5, ctypes.c_long,   # IContextMenu::GetCommandString
                          ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_uint)
            buf = ctypes.create_unicode_buffer(64)
            verb = None
            if gcs(pcm.value, cmd - 1, 4, None, buf, 64) == 0 and buf.value:   # GCS_VERBW
                verb = buf.value
            _shell_invoke_async(verb, paths)
        return True
    except Exception:
        return False
    finally:
        if hmenu:
            _h32.DestroyMenu(hmenu)
        for o in objs:
            _com_fn(o, 2, wintypes.UINT)(o)   # IUnknown::Release
        for p in pidls:
            _s32.ILFree(p)
        if own_com:
            _o32.CoUninitialize()


def _shell_exec_async(exe, params):
    """独立 STA 线程 ShellExecuteEx 直接执行命令行（坑同 _shell_invoke_async）。"""
    def work():
        _o32.CoInitializeEx(None, 0x2)   # COINIT_APARTMENTTHREADED（0 是 MTA，别写错）
        try:
            sei = _SHELLEXECUTEINFOW()
            sei.cbSize = ctypes.sizeof(sei)
            sei.fMask = 0x00100000   # SEE_MASK_ASYNCOK
            sei.lpFile = exe
            sei.lpParameters = params
            sei.nShow = 1
            _s32.ShellExecuteExW(ctypes.byref(sei))
        except Exception:
            pass
        finally:
            _o32.CoUninitialize()
    threading.Thread(target=work, daemon=True).start()


def _shell_invoke_async(verb, paths):
    """独立 STA 线程里用 ShellExecuteEx 执行外壳动词（删除/属性/打开方式等自带确认与对话框）。
    两个实测坑：① Qt 把 GUI 线程初始化成 MTA，壳动词在 MTA 下静默 E_FAIL
    （ShellExecuteEx 返回成功但什么都没发生），必须换 STA 线程；
    ② 不带 SEE_MASK_ASYNCOK 的同步调用会吊死调用线程（壳内部要等本线程泵消息）。"""
    def work():
        _o32.CoInitializeEx(None, 0x2)   # COINIT_APARTMENTTHREADED（0 是 MTA，别写错）
        try:
            for p in paths:
                sei = _SHELLEXECUTEINFOW()
                sei.cbSize = ctypes.sizeof(sei)
                sei.fMask = 0x00100000   # SEE_MASK_ASYNCOK
                sei.lpVerb = verb
                sei.lpFile = p
                sei.nShow = 1            # SW_NORMAL
                _s32.ShellExecuteExW(ctypes.byref(sei))
        except Exception:
            pass
        finally:
            _o32.CoUninitialize()
    threading.Thread(target=work, daemon=True).start()


def _log_hook_error():
    """WH_MOUSE_LL 回调异常落盘。ctypes 回调里的异常不走 sys.excepthook，
    被 ctypes 吞掉打印到 stderr（pythonw 下不可见），还会向系统返回垃圾值。"""
    try:
        import traceback
        p = os.path.join(sysutil.appdata_dir(), 'debug_due.log')
        with open(p, 'a', encoding='utf-8') as f:
            f.write('--- DesktopClickHook ---\n')
            f.write(traceback.format_exc())
    except Exception:
        pass


class DesktopClickHook(QThread):
    """双击桌面空白处 → 显隐全部格子。
    WH_MOUSE_LL 看不到 WM_LBUTTONDBLCLK（它是投递时才合成的），
    所以自己按 GetDoubleClickTime + SM_C?DOUBLECLK 判定双击。
    命中窗口沿父链走：先碰到我们自己的窗口（格子/面板）则忽略；
    碰到桌面家族（Progman/SHELLDLL_DefView/WorkerW/SysListView32）才算桌面。"""

    double_clicked = pyqtSignal()

    def __init__(self, own_hwnds, parent=None):
        super(DesktopClickHook, self).__init__(parent)
        self.own_hwnds = own_hwnds   # callable -> set(int)
        self._stop = False

    def run(self):
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        state = {'t': 0.0, 'x': -9999, 'y': -9999}
        dbl_t = u32.GetDoubleClickTime() / 1000.0
        dbl_x = u32.GetSystemMetrics(36)   # SM_CXDOUBLECLK
        dbl_y = u32.GetSystemMetrics(37)   # SM_CYDOUBLECLK

        sw = u32.GetSystemMetrics(0)
        sh = u32.GetSystemMetrics(1)

        my_pid = k32.GetCurrentProcessId()

        def _is_desktop(pt):
            h = ui._u32.WindowFromPoint(pt)
            pid = wintypes.DWORD()
            ui._u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == my_pid:
                # 本进程窗口一律不算桌面：文件夹选择框等系统对话框跑在本进程里，
                # 内嵌 SysListView32，不挡会在框里双击空白时误判成双击桌面
                return False
            own = self.own_hwnds()
            while h:
                if h in own:
                    return False
                cls = ui._class_name(h)
                if cls == 'SysListView32' or cls == 'SHELLDLL_DefView':
                    # 资源管理器窗口（CabinetWClass）里也有这两个壳视图：
                    # 只有根窗口是 Progman/WorkerW 的才是桌面，否则一律不算
                    if ui._class_name(ui._u32.GetAncestor(h, ui._GA_ROOT)) not in ('Progman', 'WorkerW'):
                        return False
                    # 点在图标/文件夹上不算空白：双击文件夹不能触发显隐
                    return cls == 'SHELLDLL_DefView' or not _desktop_icon_at(h, pt)
                if cls in ui._PROG_FAMILY:
                    return True
                # 桌面整理软件的全屏覆盖层：与 app.probe_desktop 同一判定
                if ui._is_desktop_surface(h, sw, sh):
                    return True
                h = ui._u32.GetParent(h)
            return False

        # 轮询左键沿代替 LL 钩子：只在本线程内做事，_is_desktop 的跨进程命中测试
        # 最坏多占几毫秒，也绝不影响系统鼠标管道。
        prev_down = False
        while not self._stop:
            down = bool(u32.GetAsyncKeyState(0x01) & 0x8000)   # VK_LBUTTON 当前按下
            if down and not prev_down:
                pt = wintypes.POINT()
                u32.GetCursorPos(ctypes.byref(pt))
                # 命中判定要兜异常：落盘 + 本轮放弃，不能拖垮轮询线程
                try:
                    on_desktop = _is_desktop(pt)
                    now = time.time()
                    if (on_desktop and state['t'] and now - state['t'] <= dbl_t
                            and abs(pt.x - state['x']) <= dbl_x
                            and abs(pt.y - state['y']) <= dbl_y):
                        state['t'] = 0.0
                        self.double_clicked.emit()
                    elif on_desktop:
                        state['t'], state['x'], state['y'] = now, pt.x, pt.y
                    else:
                        # 第一击也必须落在桌面上：点在格子/窗口上要把双击序列清零，
                        # 否则「拖开格子 → 快速点它腾出来的空位」会被误判成双击桌面，
                        # 全部格子被隐藏——用户眼里就是拖完格子消失了
                        state['t'] = 0.0
                except Exception:
                    _log_hook_error()
            prev_down = down
            time.sleep(0.02)

    def stop(self):
        self._stop = True
        self.wait(2000)


class BoxManager(object):
    """格子总管：恢复/新建/解散/显隐，维护双击桌面钩子。"""

    def __init__(self, data_dir, panel):
        self.store = BoxStore(os.path.join(data_dir, 'boxes.json'))
        self.box_root = os.path.join(data_dir, 'Boxes')
        self.panel = panel
        self.windows = []
        self._own_hwnd_cache = frozenset()
        self.hook = DesktopClickHook(self.own_hwnds)
        self.hook.double_clicked.connect(self.toggle_all)
        if panel.cfg.data.get('box_dblclick', True):
            self.hook.start()
        self.restore()
        self._refresh_own_hwnds()
        _get_daemon().ensure()   # 面板启动就拉起菜单宿主并预热壳扩展，首个右键不等

    def _refresh_own_hwnds(self):
        """重建本进程窗口句柄快照。只能在 GUI 线程调：winId() 可能现场创建原生窗口，
        钩子线程里调会 QWaitCondition 等主线程刷窗口事件，而主线程绘制又在等 GIL
        （钩子线程持有），直接死锁——必须在这里（GUI 线程）提前算好。"""
        s = set()
        for w in [self.panel, getattr(self.panel, 'titlebar', None)] + self.windows:
            if w is not None:
                try:
                    s.add(int(w.winId()))
                except Exception:
                    pass
        self._own_hwnd_cache = frozenset(s)   # 整体换引用，钩子线程读到的总是完整快照

    def own_hwnds(self):
        """钩子线程专用：只读主线程预建的快照，绝不碰 Qt 对象（见 _refresh_own_hwnds）。"""
        return self._own_hwnd_cache

    def restore(self):
        self._upgrade_blank_boxes()
        ag = QApplication.primaryScreen().virtualGeometry()
        show = self.store.data.get('visible', True)
        for rec in self.store.data['boxes']:
            win = BoxWindow(self, rec)
            x = min(max(rec.get('x', ag.left() + 60), ag.left()), ag.right() - 80)
            y = min(max(rec.get('y', ag.top() + 60), ag.top()), ag.bottom() - 60)
            win.move(x, y)
            self.windows.append(win)
            if show:
                win.show()
                # 收进格子 = 桌面图标藏起来（关程序时已还原，这里重新收起）
                if rec['kind'] == 'blank':
                    win.hide_icons()
        self._refresh_own_hwnds()

    def _upgrade_blank_boxes(self):
        """启动时把空白格子的文件弄回桌面，两种情况：

        ① 旧版把文件真搬进了 %APPDATA%\\zviber\\Boxes\\<id>\\（用户实测关程序后这些
           文件「被吞在里面」）—— 搬回桌面并转成 items，rec['path'] 随之作废；
        ② 新版那些目录只当「拖出暂存」用（见 `BoxWindow.stage_for_drag`），另一种暂存是
           桌面下的隐藏夹 `.zviber`：拖拽途中进程被强杀会留下残留 —— 一并搬回桌面并补进
           记账，否则文件就留在隐藏夹里看不见了。"""
        desk = os.path.normpath(desktop_dir())
        stage = os.path.join(desk, _STAGE_NAME)
        for rec in self.store.data['boxes']:
            if rec.get('kind') != 'blank':
                continue
            items = [p for p in (rec.get('items') or []) if os.path.exists(p)]
            legacy = rec.get('path') or ''
            dirs = [os.path.join(self.box_root, rec['id']), stage]
            if os.path.isdir(legacy) and legacy not in dirs:
                dirs.append(legacy)
            for d in dirs:
                items = _recover_files(d, desk, items)
            rec.pop('path', None)
            rec['items'] = items
        for d in (stage, self.box_root):   # 空目录收掉（新版不再用它们常驻）
            try:
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
            except OSError:
                pass
        self.store.save()

    def _new_rec(self, kind, name, path):
        rec = {'id': 'b%d' % int(time.time() * 1000), 'kind': kind, 'name': name,
               'x': None, 'y': None, 'w': 0, 'h': 0,
               'collapsed': False, 'locked': False, 'sort': 'name'}
        if path:
            rec['path'] = path
        n = len(self.windows)
        rec['x'] = 60 + (n % 5) * 40
        rec['y'] = 60 + (n % 5) * 40
        self.store.data['boxes'].append(rec)
        self.store.save()
        return rec

    def new_blank(self):
        """新建空白格子：只是桌面文件的收纳视图（items 记账 + 隐藏桌面图标）。"""
        n = len([r for r in self.store.data['boxes'] if r['kind'] == 'blank'])
        name = '新建格子' if n == 0 else '新建格子 %d' % (n + 1)
        rec = self._new_rec('blank', name, None)
        rec['items'] = []
        rec['attrs'] = {}
        self.store.save()
        self._spawn(rec)

    def ungroup_paths(self, paths, except_win):
        """把 paths 从别的空白格子里摘掉（一个文件只属于一个格子）。"""
        if not paths:
            return
        for w in self.windows:
            if w is except_win or w.rec.get('kind') != 'blank':
                continue
            items = w.rec.get('items') or []
            rest = [p for p in items if p not in paths]
            if rest != items:
                w.rec['items'] = rest
                w.refresh()
        self.store.save()

    def new_folder(self, path=None):
        """新建文件夹映射格子；path 为空时弹目录选择框（原生资源管理器样式）。
        同一路径已有格子时不新建：显示出来并闪烁提示（文件夹右键「添加到zviber桌面格子」
        与「新建文件夹格子」对话框都走这里）。"""
        if not path:
            # 静态方法原生框：模态只锁属主窗口，设置窗等其它顶层窗口照常可用。
            # 两个坑：① 必须用静态方法——QFileDialog 实例 + exec_() 在这套环境会开出
            # 隐形对话框；② GUI 线程必须是 STA（main() 入口已初始化），否则原生壳对话框
            # 在 Qt 默认的 MTA 下抛 RPC_E_WRONG_THREAD（0x8001010e）致命错误
            path = QFileDialog.getExistingDirectory(self.panel, '选择要映射的文件夹')
        if not path:
            return
        path = os.path.normpath(path)
        key = os.path.normcase(path)
        for w in self.windows:
            if w.rec.get('kind') == 'folder' and os.path.normcase(w.rec.get('path') or '') == key:
                if not w.isVisible():
                    if any(x.isVisible() for x in self.windows):
                        w.show()                # 过渡态个别补显示，不动全局可见标志
                    else:
                        # 全隐藏态整批放出。不能调 toggle_all()：面板可见而格子全藏
                        # （restore 按 visible=False 启动）时它会把面板也藏起来
                        self.set_boxes_visible(True)
                w.refresh()   # 路径曾被删又重建时自愈「解散格子」失效页
                w.flash()
                return
        rec = self._new_rec('folder', os.path.basename(path) or path, path)
        self._spawn(rec)

    def _spawn(self, rec):
        win = BoxWindow(self, rec)
        win.move(rec['x'], rec['y'])
        self.windows.append(win)
        # 半透明窗口 show 的首帧会先合成一帧白屏（paint 还没跑）：先隐身，
        # 等首绘与挂带（SetParent 触发隐藏-重现）都落定后再现身
        win.setWindowOpacity(0.0)
        win.show()
        QTimer.singleShot(120, lambda w=win: w.setWindowOpacity(1.0))
        if not self.store.data.get('visible', True):
            win.hide()
        self._refresh_own_hwnds()

    def save_rec(self, _win):
        self.store.save()

    def remove(self, win):
        if win in self.windows:
            self.windows.remove(win)
            self._refresh_own_hwnds()
        self.store.data['boxes'] = [r for r in self.store.data['boxes'] if r is not win.rec]
        self.store.save()
        win.setParent(None)
        win.deleteLater()

    def set_dblclick_enabled(self, on):
        """设置窗开关：启停「双击桌面显隐格子」的低级鼠标钩子。
        QThread 停止后可再次 start；stop() 会等线程退出，重启是安全的。"""
        if on and not self.hook.isRunning():
            self.hook.start()
        elif not on and self.hook.isRunning():
            self.hook.stop()

    def set_boxes_visible(self, show):
        """只显隐格子（不动面板与桌面图标层）。空白格子的文件图标同步收放：
        格子藏着时文件回桌面（show_icons），亮出时重新收进格子（hide_icons）——
        否则文件既不在格子里也不在桌面上（AGENTS.md 记过的用户痛点）。
        _hide_icon 对已隐藏的文件直接早退不重记属性，重复调用安全。"""
        self.store.data['visible'] = show
        self.store.save()
        for w in self.windows:
            w.setVisible(show)
            if w.rec['kind'] == 'blank':
                (w.hide_icons if show else w.show_icons)()

    def toggle_all(self):
        """双击桌面空白处：桌面图标 + 全部格子 + 面板一起显隐。
        任一还可见就算「显示中」，全部收起来；全收了再一起放出来。
        图标显隐 = ShowWindow 桌面 SysListView32（与右键菜单的勾选状态无关）。"""
        lv = find_desktop_listview()
        showing = (self.panel.isVisible()
                   or any(w.isVisible() for w in self.windows)
                   or bool(lv and ui._u32.IsWindowVisible(lv)))
        show = not showing
        self.set_boxes_visible(show)
        if show:   # 与 panel.toggle_visible 的显示分支一致
            self.panel.show()
            self.panel.raise_()
            self.panel.activateWindow()
        else:
            self.panel.close_panel()   # 顶部栏是独立小窗，必须跟着收
        if lv:
            ui._u32.ShowWindow(lv, 5 if show else 0)   # SW_SHOW / SW_HIDE

    def shutdown(self):
        self.hook.stop()
        # 关程序：空白格子里的文件全部「还原」到桌面（文件本来就在桌面，只是被隐藏了
        # 图标）——不还原的话用户关掉程序后桌面上找不到它们。分组记录留着，下次启动
        # 再收进格子（用户实测：关程序后文件被吞在 AppData 里，就是这个没做）。
        for w in self.windows:
            if w.rec.get('kind') == 'blank':
                w.show_icons()
        self.store.save()
