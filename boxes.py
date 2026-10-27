# -*- coding: utf-8 -*-
"""桌面格子：桌面文件归类格子功能。

- 空白格子：**只是桌面文件的收纳视图，不搬动文件**（2026-10 改；旧版是把文件真搬进
  %APPDATA%\\zbox\\Boxes\\<id>\\，用户实测「属性里路径变成 AppData」「关程序后
  文件被吞掉」，故改成现在这样）。收进格子的文件留在桌面原路径（右键属性的位置就是桌面），
  只是给文件加「隐藏」属性把桌面图标藏起来；关程序/解散格子/隐藏格子时把属性还原，
  文件随即回到桌面。分组记录（rec['items'] + 隐藏属性账本 rec['attrs']）存在 boxes.json，
  下次启动自动收进格子。不在桌面的文件拖进来会先搬到桌面——「格子里的文件都在桌面」是
  这套模型的前提。拖出落回桌面由 _DesktopDropOverlay 接住内部处理（划账 + 放出图标，
  文件不挪窝，被占用也能拖出），不经 Explorer——文件本来就在桌面上，让 Explorer 执行
  落放＝移动到它自己所在的目录，会弹「源文件名和目标文件名相同」。落到资源管理器窗口/
  其他应用才交文件 URL 给对方真实移动。格子、桌面之间的拖拽默认「移动」，按住 Ctrl
  落放 = 复制（徽标变加号）；落放效果只在真会搬走时才敢报「移动」
  （报 Move 而文件没走，资源管理器会把源文件删掉）。
- 文件夹映射格子：实时映射任意磁盘文件夹，QFileSystemWatcher 监听内容变化自动刷新；
  路径失效时切失效页（缺省图 + 「刷新」重测按钮 + 提示文案 + 「解散格子」）；文件夹被整个
  删掉时 watcher 静默失效收不到事件，双击打开文件由 open_path 补一道存在性检测兜底。
- 窗口：无边框 Tool 窗，半透明磨砂；挂桌面带免疫 Win+D（面板同款 pin_to_desktop）。
  与面板的差异：永不主动沉底（格子沉到应用窗口之下 = 用户眼里的「消失」）；
  只在被桌面整理软件表层压住时由 WinEvent 钩子/看门狗抬回表层之上。
- 双击桌面空白处显隐「桌面图标 + 全部格子 + 面板」：独立线程轮询左键自判双击
  （不用 WH_MOUSE_LL 全局钩子——每个系统鼠标事件都要等 Python 回调拿 GIL，拖拽时全系统
  鼠标卡顿，ctypes 回调里的崩溃还会直接闪退进程）；命中判定与旧钩子版一致。
- 全隐藏态的桌面右键拦截（DesktopRightClickHook）：短命 WH_MOUSE_LL 吞掉桌面右键的系统
  菜单、弹自己的单项菜单「显示桌面图标」。与上面「不用常驻 LL 钩子」不冲突——只在全隐藏
  期间安装、恢复即卸载，回调只处理右键。阻塞式 GetMessage 泵是硬要求（见类 docstring）。
- 视觉固定深色磨砂：格子贴在壁纸上，跟随面板明暗主题都不合适，故不挂主题系统。
  注意 WA_TranslucentBackground 会禁用 ClearType（app.py 面板因此不用它），
  格子文字少且参考软件本身就是半透明的，这里接受这个取舍。
"""
import ctypes
import collections
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import (Qt, QObject, QTimer, QThread, QUrl, QPoint, QRect, QSize, QEventLoop,
                          QFileSystemWatcher, Signal, QEvent, QVariantAnimation, QEasingCurve,
                          QByteArray)
from PySide6.QtGui import (QIcon, QCursor, QPainter, QColor, QPen, QFont, QImage, QPixmap, QDrag,
                          QActionGroup, QPalette)   # QActionGroup Qt6 起从 QtWidgets 挪到 QtGui
from PySide6.QtWidgets import (QWidget, QDialog, QListWidget, QListWidgetItem, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QLabel, QToolButton,
                             QPushButton, QStackedLayout, QMenu,
                             QFileDialog, QLineEdit,
                             QAbstractItemView, QApplication, QStyle,
                             QGraphicsOpacityEffect, QSizePolicy)

import app as ui   # sc / _PROG_FAMILY / _class_name / _is_desktop_surface
from snapping import (SNAP_ENGAGE, SNAP_RELEASE, SnapGuideOverlay,
                      guide_segments, snap_move, snap_resize)
import sysutil
from i18n import t

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

def _hicon_to_image(hicon, size):
    """HICON → QImage（Qt6 移除了 QtWinExtras.fromHICON 的替代）：DrawIconEx 画进
    清零的 32bpp 顶向下 DIB section，直接读回像素内存。GDI 对 32bpp 图标会写 alpha；
    老式 mask 图标 alpha 全 0 时按「RGB 非黑即不透明」兜底（纯黑像素会变透明，可接受）。"""
    g32, u32 = ctypes.windll.gdi32, ctypes.windll.user32
    w = h = size

    class _BIH(ctypes.Structure):   # BITMAPINFOHEADER，负高 = 顶向下
        _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG),
                    ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                    ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                    ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                    ('biClrImportant', wintypes.DWORD)]

    bih = _BIH()
    bih.biSize = ctypes.sizeof(_BIH)
    bih.biWidth, bih.biHeight, bih.biPlanes, bih.biBitCount = w, -h, 1, 32
    # GDI 句柄是 64 位指针：不声明 c_void_p 原型，默认 int32 转换会 OverflowError
    g32.CreateCompatibleDC.restype = ctypes.c_void_p
    g32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    g32.SelectObject.restype = ctypes.c_void_p
    g32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    g32.DeleteObject.argtypes = [ctypes.c_void_p]
    g32.DeleteDC.argtypes = [ctypes.c_void_p]
    hdc = g32.CreateCompatibleDC(None)
    bits = ctypes.c_void_p()
    g32.CreateDIBSection.restype = ctypes.c_void_p
    g32.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                     wintypes.UINT, ctypes.c_void_p,
                                     wintypes.HANDLE, wintypes.DWORD]
    hbm = g32.CreateDIBSection(hdc, ctypes.byref(bih), 0, ctypes.byref(bits), None, 0)
    if not hbm:
        g32.DeleteDC(hdc)
        return None
    old_bm = g32.SelectObject(hdc, hbm)
    ctypes.memset(bits.value, 0, w * h * 4)
    u32.DrawIconEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                               wintypes.HANDLE, ctypes.c_int, ctypes.c_int,
                               wintypes.UINT, wintypes.HANDLE, wintypes.UINT]
    u32.DrawIconEx(hdc, 0, 0, hicon, w, h, 0, None, 3)   # DI_NORMAL
    data = bytearray(ctypes.string_at(bits.value, w * h * 4))
    g32.SelectObject(hdc, old_bm)
    g32.DeleteObject(hbm)
    g32.DeleteDC(hdc)
    if not any(data[3::4]):   # alpha 全 0：老式 mask 图标兜底
        for i in range(0, len(data), 4):
            data[i + 3] = 255 if (data[i] or data[i + 1] or data[i + 2]) else 0
    img = QImage(bytes(data), w, h, w * 4, QImage.Format_ARGB32)
    return img.copy()   # 脱离本地 buffer 生命周期


# ---------------------------------------------------------------- 壳图标：后台取 + 进程内缓存
# 2026-10 性能审计：QFileIconProvider 取图标要经壳解析目标（.lnk 要打开目标才能拿到
# 目标程序的图标；.exe 要从 PE 资源提取），实测单条可达 5 秒（快捷键检测.exe 5006ms、
# 暴雪战网.lnk 1534ms），而普通文件只要 0.006ms。启动时逐条目同步取 = 48 次共 4.0 秒
# （占启动 65%）；且每次 refresh（文件监听事件）都要重付一遍。
# 改法：① 慢的那步（provider.icon()）整个挪到后台线程；
#        ② QIcon 回主线程后再烘焙（QPixmap 只能在 GUI 线程建），渲染路径与原先一致、
#        像素不变；③ 未缓存的先给零成本的占位图标，真实图标取到后替换；
#        ④ 进程内缓存 (path, is_dir, size, dpr) → QIcon，同一文件不再重复问壳。
_icon_cache = {}           # (path, is_dir, size, dpr) -> QIcon（只在 GUI 线程读写）
_ICON_CACHE_MAX = 1024
_icon_pending = set()      # 已提交后台、尚未回填的 key（只在 GUI 线程读写）
_placeholder_cache = {}    # (is_dir, size) -> QIcon 占位图标（零 shell 调用）


def _icon_cache_put(key, icon):
    """进程内图标缓存；超上限整体清空（图标不贵，重取只是几十毫秒）。"""
    if len(_icon_cache) >= _ICON_CACHE_MAX:
        _icon_cache.clear()
    _icon_cache[key] = icon


def _placeholder_icon(is_dir, size):
    """零 shell 调用的通用占位图标（系统内置样式图标），真实图标取到后替换。"""
    key = (is_dir, size)
    ico = _placeholder_cache.get(key)
    if ico is None:
        sp = QStyle.StandardPixmap.SP_DirIcon if is_dir else QStyle.StandardPixmap.SP_FileIcon
        ico = QApplication.style().standardIcon(sp)
        _placeholder_cache[key] = ico
    return ico


# 这些类型的图标取起来慢（.lnk 要经壳解析目标；exe/dll 要从 PE 资源提取，
# 实测 11.8MB 的 exe 提取一次要 3 秒），必须放后台线程。
_ASYNC_ICON_EXT = ('.lnk', '.exe', '.dll', '.com', '.scr', '.msi', '.bat',
                    '.cmd', '.jar', '.appref-ms')


def _needs_async_icon(path, is_dir):
    """该条目的图标要不要放后台线程取。"""
    if is_dir:
        return False
    return path.lower().endswith(_ASYNC_ICON_EXT)


_icon_tls = threading.local()


def _shell_icon_image(path, is_dir, px):
    """纯 ctypes 取壳图标 → QImage（工作线程安全，**不碰 Qt 的全局图标缓存**）。

    为什么不用 QFileIconProvider 放到后台：它的图标引擎挂在 **全局 QPixmapCache**
    （带 mutex）上——实测后台线程取图标时，主线程的 resize/paint 也要用同一把锁，
    会被堵住 3.4 秒（启动从 2.0s 劣化到 5.4s）。纯 ctypes 路线完全不碰 Qt 缓存。

    .lnk 要先解析目标：SHGetFileInfoW / ExtractIconExW 对 .lnk 返回的是
    「快捷方式」默认图标（不解析目标），而资源管理器显示的是目标程序的图标。
    故这里用 IShellLinkW 解析出目标路径，再对目标取图标。

    ⚠️ 慢的那步是真的慢：从 PE 资源提取图标要扫完整个 exe（实测 11.8MB 的 exe
    提取一次 3.0 秒）——正因如此才必须放在后台线程。
    """
    target = path
    if path.lower().endswith('.lnk'):
        t = _lnk_target_path(path)
        if t:
            target = t
    h_big, h_small = ctypes.c_void_p(), ctypes.c_void_p()
    _s32.ExtractIconExW.restype = wintypes.UINT
    _s32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                    ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    if _s32.ExtractIconExW(target, 0, ctypes.byref(h_big), ctypes.byref(h_small), 1) <= 0:
        return None
    u32 = ctypes.windll.user32
    try:
        h = int(h_big.value) if h_big.value else int(h_small.value)
        if not h:
            return None
        # DrawIconEx 直接画成目标像素尺寸（shell 自己做缩放，质量比事后拉伸好）
        return _hicon_to_image(h, px)
    finally:
        if h_big.value:
            u32.DestroyIcon(int(h_big.value))
        if h_small.value:
            u32.DestroyIcon(int(h_small.value))


class _IconThread(QObject):
    """后台取壳图标：一个实例服务所有格子（不每格一线程）。

    队列取任务 → 工作线程提取 → QImage 经信号回主线程。
    ⚠️ sig_ready 从工作线程 emit，接收者必须是在**主线程**的 QObject，
    AutoConnection 才会判成 QueuedConnection（否则直接在发射线程跑 UI 代码）。
    故本类自己接一手（_deliver 是本 QObject 的方法 → 排队回主线程），
    再由主线程回调转交给格子。
    """

    sig_ready = Signal(str, bool, int, float, object)   # path, is_dir, size, dpr, QImage

    def __init__(self, parent=None):
        super(_IconThread, self).__init__(parent)
        self._q = collections.deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._cb = None
        self.sig_ready.connect(self._deliver)
        self._th = threading.Thread(target=self._loop, name='zbox-icon')
        self._th.daemon = True
        self._th.start()

    def set_callback(self, cb):
        self._cb = cb

    def submit(self, path, is_dir, size, px, dpr):
        with self._lock:
            self._q.append((path, is_dir, size, px, dpr))
        self._wake.set()

    def _deliver(self, path, is_dir, size, dpr, img):
        """已回到主线程：转交给订阅者。"""
        cb = self._cb
        if cb is not None:
            try:
                cb(path, is_dir, size, dpr, img)
            except Exception:
                pass

    def _loop(self):
        while True:
            self._wake.wait(0.2)
            self._wake.clear()
            while True:
                with self._lock:
                    if not self._q:
                        break
                    path, is_dir, size, px, dpr = self._q.popleft()
                try:
                    img = _shell_icon_image(path, is_dir, px)
                    self.sig_ready.emit(path, is_dir, size, dpr, img)
                except Exception:
                    self.sig_ready.emit(path, is_dir, size, dpr, None)


_icon_thread = None


def _icon_worker():
    """进程内单例的后台图标线程。"""
    global _icon_thread
    if _icon_thread is None:
        _icon_thread = _IconThread()
    return _icon_thread

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

# 旧版拖出空白格子用的暂存目录名（桌面下的隐藏夹；现已被 _DesktopDropOverlay 取代，
# 只留名字给 _upgrade_blank_boxes 扫回旧残留）
_STAGE_NAME = '.zbox'

# 格子拖出时挂在 QMimeData 上的来源标记（值为格子 rec id）：落回桌面由
# _DesktopDropOverlay 接住内部处理时凭它找到源格子；外部应用不认识它，无影响
_BOX_DRAG_MIME = 'application/x-zbox-box-drag'


def _drop_text(e, name):
    """拖拽落点文案：默认移动，按住 Ctrl 复制；文案在运行时按当前语言取。"""
    key = 'boxes.drop.copy' if e.modifiers() & Qt.ControlModifier else 'boxes.drop.move'
    return t(key, name=name)

SORT_CHOICES = [('name', 'boxes.sort.name'), ('type', 'boxes.sort.type'),
                ('mtime', 'boxes.sort.mtime')]
VIEW_CHOICES = [('list', 'boxes.view.list'), ('icon', 'boxes.view.icon')]

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
QListWidget::item { border-radius: 4px; }
QListWidget[view="list"]::item { height: @IH@px; padding-left: 4px; }
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
QMenu { background: #26282f; color: #e8e6e1; border: 1px solid rgba(255,255,255,30);
        padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 4px; }
QMenu::item:selected { background: rgba(255,255,255,25); }
QMenu::separator { height: 1px; background: rgba(255,255,255,20); margin: 4px 8px; }
QPushButton { background: rgba(255,255,255,30); color: #fff; border: none;
              border-radius: 4px; padding: 5px 18px; font-size: @HFS@px; }
QPushButton:hover { background: rgba(255,255,255,55); }
QPushButton#boxRefresh { padding: 3px 12px; }
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


def _recover_files(path, desk, items, keep=()):
    """把 path 里的文件搬回桌面（去重后补进 items），搬空则删掉目录。
    用于启动恢复：旧版存储目录与拖拽暂存夹的残留都走这里。
    keep 里的路径是空白格子正在托管的文件（rec['moved']），不是残留，不动。"""
    if not path or not os.path.isdir(path):
        return items
    try:
        for name in os.listdir(path):
            if os.path.join(path, name) in keep:
                continue
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


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [('hwnd', ctypes.c_void_p), ('wFunc', ctypes.c_uint),
                ('pFrom', ctypes.c_wchar_p), ('pTo', ctypes.c_wchar_p),
                ('fFlags', ctypes.c_ushort), ('fAnyOperationsAborted', wintypes.BOOL),
                ('hNameMappings', ctypes.c_void_p), ('lpszProgressTitle', ctypes.c_wchar_p)]


def _shell_op(func, paths, dest=None, hwnd=None):
    """SHFileOperation 搬移/复制/删除（func = FO_MOVE 1 / FO_COPY 2 / FO_DELETE 3）。
    确认弹窗、进度条、撞名处理全走外壳原生（不带 FOF_NOCONFIRMATION，与资源管理器一致）；
    返回是否实际执行了（用户在外壳弹窗里取消 = False）。"""
    if not paths:
        return False
    op = _SHFILEOPSTRUCTW()
    op.hwnd = hwnd
    op.wFunc = func
    op.pFrom = '\0'.join(paths) + '\0\0'
    op.fFlags = 0x40   # FOF_ALLOWUNDO：删除进回收站、搬移/复制可撤销
    if dest:
        op.pTo = dest + '\0\0'
        op.fFlags |= 0x200   # FOF_NOCONFIRM_MKDIR：目标子目录直接建，别弹窗打断
    r = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return r == 0 and not op.fAnyOperationsAborted


def _strip_hidden(path):
    """摘掉文件的隐藏属性。空白格子复制/搬出产生的文件不能带隐藏位（否则落点看不见）。"""
    try:
        a = _k32.GetFileAttributesW(path)
        if a != _INVALID_ATTRS and a & ATTR_HIDDEN:
            _k32.SetFileAttributesW(path, a & ~ATTR_HIDDEN)
    except Exception:
        pass


def _recycle(paths, hwnd=None):
    """删除到回收站：确认弹窗由外壳自己弹（资源管理器里按 Del 同款）。"""
    _shell_op(0x3, paths, hwnd=hwnd)


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
    """格子文件列表：拖入归类、拖出回桌面/别处、双击打开、右键菜单、Delete 删除。
    格子内拖放（外部拖入同规则）：落点三态——条目间缝显白色引导线、松手插入该位并
    切自定义排序（sort='custom'，菜单三项勾勾全灭）；落文件夹条目上 = 移进去；
    落可执行文件/快捷方式上 = 用它打开被拖文件（资源管理器同款，普通文件无此语义）。"""

    def __init__(self, box):
        super(BoxList, self).__init__()
        self.box = box
        self.setProperty('view', 'list')   # QSS 行高选择器用；set_view 里切换并重刷样式
        self.setViewMode(QListWidget.ListMode)
        self.setIconSize(QSize(ui.sc(16), ui.sc(16)))
        self.setResizeMode(QListWidget.Adjust)
        # Qt6 起 QSS 的 background: transparent 不再传导到滚动区视口（视口 palette 是不透明黑，
        # 格子内容区整块黑底）——手动把视口置透明
        vp = self.viewport()
        vp.setAutoFillBackground(False)
        pal = vp.palette()
        pal.setColor(QPalette.Base, QColor(0, 0, 0, 0))
        vp.setPalette(pal)
        self.setUniformItemSizes(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.itemDoubleClicked.connect(lambda it: self.box.open_path(it.data(Qt.UserRole)))
        self._menu_press_ts = 0.0   # 最近一次「点掉外壳菜单」的那按下（见 mouseDoubleClickEvent）
        self._guide = None   # 拖拽落点反馈：('line'/'folder'/'open', 行号)，paintEvent 画引导线/高亮
        self._lnk_dir_cache = {}   # .lnk → 目标目录解析缓存（拖拽悬停每帧都问；refresh 清空）
        self._icon_items = {}      # path → (item, 图标尺寸)：后台图标取回后回填到对应行
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 滚轮平滑滚动（对齐资源管理器手感，见 wheelEvent）：动画驱动滚动条
        self._wheel_target = 0
        self._wheel_anim = QVariantAnimation(self)
        self._wheel_anim.setDuration(200)
        self._wheel_anim.setEasingCurve(QEasingCurve.OutCubic)
        sb = self.verticalScrollBar()
        self._wheel_sb = sb
        self._wheel_anim.valueChanged.connect(self._set_wheel_value)
        sb.sliderPressed.connect(self._wheel_anim.stop)   # 拖滚动条时动画让位，别抢
        self.horizontalScrollBar().sliderPressed.connect(self._wheel_anim.stop)

    def set_view(self, key):
        """按列表 / 按图标查看。图标视图 = 32px 图标 + 固定网格 + 名称两行折行；
        QSS 的固定行高只对 list 生效（view 属性选择器），切完必须 unpolish/polish。"""
        if key == 'icon':
            self.setViewMode(QListWidget.IconMode)
            self.setIconSize(QSize(ui.sc(32), ui.sc(32)))
            self.setGridSize(QSize(ui.sc(84), ui.sc(72)))
            self.setWordWrap(True)
            # 按像素滚动：IconMode 下默认 ScrollPerItem 的步进极小，滚轮滚很久才动一点
            self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            self.verticalScrollBar().setSingleStep(ui.sc(24))   # 一 notch(3 行) ≈ 一格高
        else:
            self.setViewMode(QListWidget.ListMode)
            self.setIconSize(QSize(ui.sc(16), ui.sc(16)))
            self.setGridSize(QSize())   # 无效 QSize = 恢复自动
            self.setWordWrap(False)
            # 两种视图都按像素滚动：滚轮平滑动画（wheelEvent）与触摸板跟手都按像素驱动
            self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        # Qt 坑（6.8 实测）：QListView.setViewMode 会按 movement 顺手调
        # setDragEnabled/setAcceptDrops——ListMode 的 movement 是 Static → 两个都被关掉
        # （图标视图切回列表后，拖出退化成橡皮筋框选、拖入也不收）。每次切完重新打开。
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setProperty('view', key)
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        # 图标尺寸随视图变，按新尺寸重烘 pixmap（壳图标 paint 期现取是滚动卡顿根因，
        # 见 BoxWindow._baked_icon）
        sz = self.iconSize()
        szw = sz.width() if hasattr(sz, 'width') else int(sz)
        for i in range(self.count()):
            it = self.item(i)
            p = it.data(Qt.UserRole)
            if p:
                self._icon_items[p] = (it, szw)
                it.setIcon(self.box._baked_icon(p, os.path.isdir(p), sz))

    def apply_icon(self, path, icon, size):
        """后台取回的图标回填到对应行（期间切了视图、尺寸变了就跳过，等重取）。"""
        rec = self._icon_items.get(path)
        if rec is not None and rec[1] == size:
            rec[0].setIcon(icon)

    def set_scrollbars_visible(self, visible):
        policy = Qt.ScrollBarAsNeeded if visible else Qt.ScrollBarAlwaysOff
        self.setHorizontalScrollBarPolicy(policy)
        self.setVerticalScrollBarPolicy(policy)

    def _set_wheel_value(self, value):
        self._wheel_sb.setValue(value)

    def wheelEvent(self, e):
        """滚轮平滑滚动（对齐资源管理器手感）：Qt 默认每 notch 瞬跳 3 行，视觉上
        一卡一卡；改成 200ms 缓出动画驱动滚动条。触摸板（pixelDelta）直接跟手不走动画。
        Shift + 滚轮在横向可滚时横滚，否则保持纵向滚动。"""
        horizontal = (bool(e.modifiers() & Qt.ShiftModifier)
                      and self.horizontalScrollBar().maximum() > 0)
        sb = self.horizontalScrollBar() if horizontal else self.verticalScrollBar()
        if sb is not self._wheel_sb:
            self._wheel_anim.stop()
            self._wheel_sb = sb
        pd = e.pixelDelta()
        if not pd.isNull():
            self._wheel_anim.stop()
            sb.setValue(sb.value() - pd.y())
            e.accept()
            return
        dy = e.angleDelta().y()
        if not dy:
            super(BoxList, self).wheelEvent(e)   # 原生横向滚动等交给默认实现
            return
        lines = QApplication.styleHints().wheelScrollLines() or 3
        if horizontal:
            px = ((self.gridSize().width() or ui.sc(84))
                  if self.viewMode() == QListWidget.IconMode else ui.sc(24) * lines)
        elif self.viewMode() == QListWidget.IconMode:
            px = self.gridSize().height() or ui.sc(72)   # 一 notch ≈ 一格高
        else:
            row = self.sizeHintForRow(0) if self.count() else ui.sc(28)
            px = row * lines   # 一 notch = 系统滚动行数 × 行高
        start = sb.value()
        if self._wheel_anim.state() == QVariantAnimation.Running:
            start_target = self._wheel_target   # 连滚：从在途动画的目标值继续叠加
        else:
            start_target = start
        target = max(sb.minimum(), min(sb.maximum(), int(round(start_target - px * dy / 120.0))))
        if target == start:
            e.accept()
            return
        self._wheel_target = target
        self._wheel_anim.stop()
        self._wheel_anim.setStartValue(start)
        self._wheel_anim.setEndValue(target)
        self._wheel_anim.start()
        e.accept()

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
            ui._dbg('★ double-click %.2fs after menu close ignored'
                    % (time.time() - self._menu_press_ts))
            e.accept()
            return
        super(BoxList, self).mouseDoubleClickEvent(e)

    def dragEnterEvent(self, e):
        paths = self._drag_paths(e)
        if paths:
            e.setDropAction(self.box.drag_effect(e))   # 徽标：默认移动，Ctrl 复制
            e.accept()
            self.box.mgr._note_drag_enter_own()
        else:
            super(BoxList, self).dragEnterEvent(e)

    # 拖拽落点三态：('line', N) 第 N 行前的白色引导线 / ('folder', N) 落进文件夹 /
    # ('open', N) 用该文件打开被拖文件。行高中部 50% 算「落在条目上」，上/下各 25%
    # 算条目间的缝（图标视图改看左/右 25%）。
    _OPEN_EXTS = ('.exe', '.bat', '.cmd', '.com', '.lnk')

    def _lnk_dir(self, path):
        """.lnk 指向现存目录 → 返回目录路径（带缓存，refresh 重建列表时清空）。"""
        cache = self._lnk_dir_cache
        if path not in cache:
            cache[path] = _lnk_target_dir(path)
        return cache[path]

    def _content_right(self, it):
        """条目内容的右边界 = 行左缘 + QSS 左内边距 4px + 图标 + 图文间距 ~4px + 文件名宽。
        行尾超出这条线的空白区不是有效落点（见 _drop_loc）。"""
        rect = self.visualItemRect(it)
        text_w = self.fontMetrics().horizontalAdvance(it.text())
        return min(rect.left() + ui.sc(4) + self.iconSize().width() + ui.sc(4) + text_w,
                   rect.right())

    def _drop_loc(self, pos, paths):
        """落点判定（格子内拖动与外部拖入共用同一套）。落在文件夹条目中部 = 移进它；
        落在可执行文件/快捷方式中部 = 用它打开被拖文件（资源管理器同款：普通文件没有
        落放语义，退化为就近引导线）；落在条目间的缝 = 白色引导线，松手按这个位置
        插入并切成自定义排序。列表视图下光标超出条目内容宽度（行尾空白区）不做
        落点判定：一律视为移动/复制到格子根。"""
        it = self.itemAt(pos)
        if it is None:
            if self.count():
                last = self.visualItemRect(self.item(self.count() - 1))
                if pos.y() > last.bottom():
                    return ('line', self.count())
            return None
        if self.viewMode() == QListWidget.ListMode and pos.x() > self._content_right(it):
            # 行尾空白区：不落文件夹、不显引导线。外部拖入走 None 分支照常收进格子根；
            # 内部拖动的文件本来就在格子里，拒收 = 原地不动
            return None
        p = it.data(Qt.UserRole)
        row = self.row(it)
        rect = self.visualItemRect(it)
        if self.viewMode() == QListWidget.ListMode:
            rel = (pos.y() - rect.top()) / max(1, rect.height())
        else:
            rel = (pos.x() - rect.left()) / max(1, rect.width())
        if rel < 0.25:
            return ('line', row)
        if rel > 0.75:
            return ('line', row + 1)
        if p in paths:
            return None   # 拖到被拖条目自己身上：没有语义
        if it.data(Qt.UserRole + 1):
            return ('folder', row)
        if p.lower().endswith('.lnk') and self._lnk_dir(p):
            return ('folder', row)   # 文件夹快捷方式：与文件夹同语义（移进目标目录）
        if os.path.splitext(p)[1].lower() in self._OPEN_EXTS:
            return ('open', row)
        return ('line', row) if rel < 0.5 else ('line', row + 1)

    def _set_guide(self, loc):
        if loc != self._guide:
            self._guide = loc
            self.viewport().update()

    def paintEvent(self, e):
        """落点反馈：引导线 = 一条 2px 白色横线（图标视图为竖线）；
        落在条目上（文件夹/可执行文件）= 整行高亮框。"""
        super(BoxList, self).paintEvent(e)
        if not self._guide:
            return
        kind, row = self._guide
        vp = self.viewport()
        pt = QPainter(vp)
        pt.setRenderHint(QPainter.Antialiasing)
        if kind == 'line':
            if row < self.count():
                it = self.item(row)
                r = self.visualItemRect(it)
                before = True
            else:
                it = self.item(self.count() - 1)
                r = self.visualItemRect(it)
                before = False
            pen = QPen(QColor(255, 255, 255, 230), max(2, ui.sc(2)))
            pen.setCapStyle(Qt.RoundCap)
            pt.setPen(pen)
            if self.viewMode() == QListWidget.ListMode:
                y = r.top() if before else r.bottom() + 1
                # 线长跟着内容走：行尾空白区不是有效落点（见 _drop_loc）
                pt.drawLine(ui.sc(2), y, self._content_right(it), y)
            else:
                x = r.left() if before else r.right() + 1
                pt.drawLine(x, r.top(), x, r.bottom())
        else:
            it = self.item(row)
            r = self.visualItemRect(it)
            if self.viewMode() == QListWidget.ListMode:
                r.setRight(self._content_right(it))   # 高亮框同样只圈内容区
            pt.setPen(QPen(QColor(255, 255, 255, 160), 1))
            pt.setBrush(QColor(255, 255, 255, 26))
            pt.drawRoundedRect(r.adjusted(1, 1, -1, -1), ui.sc(4), ui.sc(4))
        pt.end()

    def dragMoveEvent(self, e):
        internal = e.source() is self
        paths = ([it.data(Qt.UserRole) for it in self.selectedItems()] if internal
                 else self._drag_paths(e))
        if not paths:
            self._set_guide(None)
            super(BoxList, self).dragMoveEvent(e)
            return
        loc = self._drop_loc(e.position().toPoint(), paths)
        if loc is None:
            self._set_guide(None)
            self.box.mgr.badge.done()
            if internal:
                e.ignore()   # 内部拖动落在无语义区（被拖条目自己身上）：拒收
            else:
                # 外部拖入落在无语义区：保持旧行为，照常收进格子根
                e.setDropAction(self.box.drag_effect(e))
                e.accept()
                self.box.mgr.badge.show_text(_drop_text(e, self.box.rec['name']))
            return
        self._set_guide(loc)
        e.setDropAction(self.box.drag_effect(e))
        e.accept()
        kind, row = loc
        if kind == 'folder':
            text = _drop_text(e, os.path.basename(self.item(row).data(Qt.UserRole)))
        elif kind == 'open':
            text = t('boxes.drop.open_with', name=self.item(row).text())
        elif internal:
            text = t('boxes.drop.reorder')
        else:
            # 外部拖到引导线：白线本身就是落点反馈，系统气泡（Explorer 画的「→ 移动」）
            # 已说明移动语义，不再叠一行「移动到 格子名」徽标
            self.box.mgr.badge.done()
            return
        self.box.mgr.badge.show_text(text)

    def dragLeaveEvent(self, e):
        self._set_guide(None)
        self.box.mgr.badge.done()
        self.box.mgr._note_drag_leave_own()
        super(BoxList, self).dragLeaveEvent(e)

    def _drag_from_blank(self, e):
        """这次拖拽是从我们的空白格子拖出来的（文件被我们藏着）→ 落进真实目录要摘隐藏位。"""
        md = e.mimeData()
        if md.hasFormat(_BOX_DRAG_MIME):
            sb = self.box.mgr.box_by_id(bytes(md.data(_BOX_DRAG_MIME).data()).decode('utf-8'))
            return sb is not None and sb.rec['kind'] == 'blank'
        return False

    def dropEvent(self, e):
        self.box.mgr.badge.done()
        self.box.mgr._note_drag_enter_own()
        loc = self._guide
        self._set_guide(None)
        internal = e.source() is self
        paths = ([it.data(Qt.UserRole) for it in self.selectedItems()] if internal
                 else self._drag_paths(e))
        if not paths:
            e.ignore()
            return
        kind, row = loc if loc else (None, -1)
        copy = bool(e.modifiers() & Qt.ControlModifier)   # 按住 Ctrl = 复制
        # 源是空白格子（文件被我们藏着）：落进真实目录要摘隐藏位
        unhide = (self.box.rec['kind'] == 'blank') if internal else self._drag_from_blank(e)
        if kind == 'folder':
            dest = self.item(row).data(Qt.UserRole)
            if dest.lower().endswith('.lnk'):
                dest = self._lnk_dir(dest) or dest   # 文件夹快捷方式：落进目标目录
            self.box.import_paths(paths, copy=copy, dest=dest, unhide=unhide)
        elif kind == 'open':
            _shell_exec_async(self.item(row).data(Qt.UserRole),
                              ' '.join('"%s"' % p for p in paths))
        elif kind == 'line':
            if internal:
                self._reorder(row, paths)
            else:
                # 外部拖到引导线：先照常收进格子，再按落点位置切成自定义排序
                pre = [self.item(i).data(Qt.UserRole) for i in range(self.count())]
                dsts = self.box.import_paths(paths, copy=copy, unhide=unhide)
                if dsts:
                    idx = max(0, min(row, len(pre)))
                    self.box.apply_custom_order(pre[:idx] + dsts + pre[idx:])
        elif internal:
            e.ignore()   # 落在无语义区（自己身上）：不动
            return
        else:
            self.box.import_paths(paths, copy=copy, unhide=unhide)
        e.setDropAction(self.box.drop_effect(paths))   # 按实际搬没搬走回报
        e.accept()

    def _reorder(self, insert_row, paths):
        """格子内拖放落到引导线：把被拖条目按当前可见顺序插到 insert_row 之前，
        并切成自定义排序（菜单三项勾勾全消，见 apply_custom_order）。"""
        rows = [self.item(i).data(Qt.UserRole) for i in range(self.count())]
        moving = set(paths)
        picked = [p for p in rows if p in moving]
        rest = [p for p in rows if p not in moving]
        idx = sum(1 for i, p in enumerate(rows) if i < insert_row and p not in moving)
        self.box.apply_custom_order(rest[:idx] + picked + rest[idx:])

    def _drag_paths(self, e):
        """外部拖进来的本地文件路径（source 是自己的列表 = 格子内部拖拽，不算）。"""
        if e.source() is self:
            return []
        return [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]

    def mimeData(self, items):
        """拖出时附带文件 URL（落到资源管理器窗口/其他应用 = 对方执行真实移动）
        + 来源格子标记（落回桌面由 _DesktopDropOverlay 内部处理，凭它找到源格子）。"""
        md = super(BoxList, self).mimeData(items)
        md.setUrls([QUrl.fromLocalFile(it.data(Qt.UserRole)) for it in items])
        md.setData(_BOX_DRAG_MIME, QByteArray(self.box.rec['id'].encode('utf-8')))
        return md

    def _drag_pixmap(self, items):
        """拖拽跟随图像：选中行的视口截图（太宽压到 320，拿不到就让 Qt 用默认光标）。"""
        rect = QRect()
        for it in items[:6]:
            rect = rect.united(self.visualItemRect(it))
        if rect.isValid():
            pm = self.viewport().grab(rect)
            if pm.width() > ui.sc(320):
                pm = pm.scaledToWidth(ui.sc(320), Qt.SmoothTransformation)
            return pm
        return QPixmap()

    def startDrag(self, actions):
        """格子拖出：默认动作报「移动」（exec 第二参数 = CFSTR_PREFERREDDROPEFFECT，
        跨盘落到资源管理器默认也是移动，Ctrl 落放 = 复制）。落到桌面由 overlay 接住
        内部处理（见 _DesktopDropOverlay），不经 Explorer——空白格子的文件本来就在
        桌面，落回桌面 = 划账 + 放图标，文件不挪窝，被占用也能拖出（DeskGo 同款）。
        空白格子拖出前先把隐藏图标放出来：落到资源管理器窗口是对方真实移动，
        隐藏属性不能跟过去；拖完没搬走的（取消/复制）重新藏。"""
        self._wheel_anim.stop()   # 拖拽自动滚动与滚轮动画不叠加
        items = self.selectedItems()
        paths = [it.data(Qt.UserRole) for it in items]
        box = self.box
        blank = box.rec['kind'] == 'blank'
        if blank:
            for p in paths:
                box._dragging[p] = p   # 拖拽期间别让桌面 watcher 把放出来的图标当场收回
            # 拖出时**不**先放图标：旧版拖出即放，Explorer 立刻把图标摆到第一列空位
            # （桌面满了还挤开别人不弹回）——用户实测「没松手图标就出现在别处」。
            # 落到桌面由落放层在落点处放出并摆位（overlay_drop）；只有拖到外部窗口
            # （Explorer 文件夹等）才需要提前摘隐藏属性——由 mgr._note_drag_leave_own
            # 的延迟定时器判定「离开了我们所有窗口」才放
            box.mgr._drag_src = box
            box.mgr._drag_paths = paths
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items))
        pm = self._drag_pixmap(items)
        if not pm.isNull():
            drag.setPixmap(pm)
            drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
        # 徽标让位用：跟随图高度（热点在图中心）。系统气泡位置够不着（Qt 自绘拖拽光标，
        # 不走 IDragSourceHelper2，DropDescription 写了也不渲染——实测），徽标只能自绘让开
        box.mgr.badge.drag_pm_h = pm.height() if not pm.isNull() else 0
        ov = getattr(box.mgr, 'overlay', None)
        use_ov = ov is not None and ov.pin_ok
        if use_ov:
            ov.begin()
        try:
            drag.exec(Qt.MoveAction | Qt.CopyAction, Qt.MoveAction)
        finally:
            if use_ov:
                ov.end()
            box.mgr.badge.done()
            box.mgr.badge.drag_pm_h = 0
            box.mgr._cancel_unhide()   # 先取消延迟放图标定时器，再按结果重新藏
            box.mgr._drag_src = None
            box.mgr._drag_paths = []
            if blank:
                for p in paths:
                    box._dragging.pop(p, None)
                for p in paths:
                    if p in (box.rec.get('items') or []) and os.path.exists(p):
                        box._hide_icon(p)   # 没搬走（取消/复制）：重新藏
                _shell_refresh(desktop_dir())
                box.refresh()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete:
            self.box.delete_items(self.selectedItems())
        elif e.key() == Qt.Key_F2:
            # 与资源管理器一致：F2 重命名焦点项（条目平时不可编辑，默认触发器够不着）
            it = self.currentItem()
            if it is not None:
                self._rename_item(it)
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

            # 弹菜单的落点在【右键事件进来这一刻】钉死：GetCursorPos 取物理像素
            # （QCursor.pos() 是 Qt 逻辑像素，125% DPI 下传给宿主会偏移）；
            # 不能等弹窗时再取——宿主建菜单要几十~几百 ms，光标一挪菜单就跟着跑了。
            _pt = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(_pt))
            r = shell_context_menu(int(self.winId()), paths,
                                   _pt.x, _pt.y,
                                   on_rename=_do_rename)
            ui._dbg('ctxmenu: takeover result r=%r' % (r,))
            if r == 'rename':
                self._rename_item(it)
                return
            if r:
                return
            # ★ Qt 兜底菜单：**只有宿主与 ctypes 两条路都没接管才会走到这**。它弹在
            # 光标处、第一项是「打开」，而右键之后按键可能还按着——松开就会被当成选中它。
            ui._dbg('★ using Qt fallback menu (host/ctypes did not take over) it=%s' % it.text())
        menu = QMenu(self)
        if it:
            path = it.data(Qt.UserRole)
            menu.addAction(t('boxes.menu.open'), lambda: self.box.open_path(path))
            menu.addAction(t('boxes.menu.reveal'), lambda: self.box.reveal_path(path))
            menu.addSeparator()
            menu.addAction(t('common.delete'), lambda: self.box.delete_items(self.selectedItems()))
        else:
            menu.addAction(t('common.refresh'), self.box.refresh)
            menu.addAction(t('boxes.menu.open_folder'),
                           lambda: self.box.open_path(self.box.display_dir()))
        if menu.actions():
            act = menu.exec(QCursor.pos())
            ui._dbg('★ Qt fallback menu choice: %s' % (act.text() if act else None))


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
        title_lbl = QLabel(title)
        title_lbl.setObjectName('boxName')
        tb.addWidget(title_lbl)
        tb.addStretch(1)
        close = QToolButton()
        close.setText('✕')
        close.setFixedSize(ui.sc(22), ui.sc(20))
        close.setToolTip(t('common.close'))
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
        cancel = QPushButton(t('common.cancel'))
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


class _BoxTitle(QLabel):
    """格子标题标签：按可用宽度尾部省略。英文默认名 / 长名称比中文宽，
    最小宽度下会被右侧操作按钮挤压，普通 QLabel 不参与布局收缩、只会被裁掉。"""

    def __init__(self, text=''):
        super(_BoxTitle, self).__init__()
        self._full = text or ''
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._relide()

    def setText(self, text):
        self._full = text or ''
        self._relide()

    def resizeEvent(self, e):
        super(_BoxTitle, self).resizeEvent(e)
        self._relide()

    def _relide(self):
        text = self.fontMetrics().elidedText(self._full, Qt.ElideRight,
                                             max(self.width(), 0))
        super(_BoxTitle, self).setText(text)
        self.setToolTip(self._full if text != self._full else '')


class BoxWindow(QWidget):
    """单个桌面格子窗口。"""

    def __init__(self, mgr, rec):
        super(BoxWindow, self).__init__(None, Qt.FramelessWindowHint | Qt.Tool)
        self.mgr = mgr
        self.rec = rec
        self._desk_pinned = False
        self._dragging = {}         # 拖出期间记账 {路径: 路径}：防桌面 watcher 把放出来的图标当场收回
        self._op = None          # ('move', 起点全局坐标, 起始几何) 或 ('resize', 边缘掩码, ...)
        self._press_pos = None   # 拖拽起点（全局坐标），用于区分点击与拖动
        self._last_drag_ts = 0.0   # 最近一次发生位移的拖拽结束时间（抑制拖拽连带的双击收起）
        self._snap_sticky = (None, None)  # 当前拖拽在横/纵轴已吸附的位置
        self._snap_guide = None   # 当前拖拽的跨卡片辅助线覆盖层
        self._hover_peek = False   # 收起态悬停预览中（临时展开，不改 rec、不落盘）
        self._peek_timer = QTimer(self)   # 移开后延迟收回：菜单/拖拽进行中由 _peek_tick 推迟
        self._peek_timer.setInterval(120)
        self._peek_timer.timeout.connect(self._peek_tick)
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
            self.icon.setToolTip(t('boxes.tooltip.open_folder'))
        else:
            # 空白格子不显示图标——它背后没有对应的文件夹，图标只是个无意义的点缀，
            # 隐藏后布局不占位（QHBoxLayout 跳过隐藏控件），标题栏只留名称
            self.icon.hide()
        tb.addWidget(self.icon)
        self.name = _BoxTitle(rec['name'])
        self.name.setObjectName('boxName')
        tb.addWidget(self.name, 1)
        # 双击名称后原地替换成的重命名输入框
        self.edit = QLineEdit(rec['name'])
        self.edit.setObjectName('boxNameEdit')
        self.edit.hide()
        self.edit.editingFinished.connect(self._finish_rename)
        tb.addWidget(self.edit, 1)
        self._edit_cancel = False
        self.title_actions = QWidget()
        ta = QHBoxLayout(self.title_actions)
        ta.setContentsMargins(0, 0, 0, 0)
        ta.setSpacing(ui.sc(4))
        self.btn_collapse = QToolButton()
        self.btn_collapse.setFixedSize(ui.sc(22), ui.sc(20))
        self.btn_collapse.clicked.connect(lambda: self.set_collapsed(not self.rec['collapsed']))
        ta.addWidget(self.btn_collapse)
        self.btn_lock = QToolButton()
        self.btn_lock.setFixedSize(ui.sc(22), ui.sc(20))
        self.btn_lock.clicked.connect(lambda: self.set_locked(not self.rec['locked']))
        ta.addWidget(self.btn_lock)
        self.btn_menu = QToolButton()
        self.btn_menu.setText('≡')
        self.btn_menu.setFixedSize(ui.sc(22), ui.sc(20))
        self.btn_menu.clicked.connect(self._show_menu)
        ta.addWidget(self.btn_menu)
        tb.addWidget(self.title_actions)
        self._title_actions_effect = QGraphicsOpacityEffect(self.title_actions)
        self._title_actions_effect.setOpacity(0.0)
        self.title_actions.setGraphicsEffect(self._title_actions_effect)
        self.title_actions.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._title_actions_target = 0.0
        self._title_actions_hold = False
        self._title_actions_timer = QTimer(self)
        self._title_actions_timer.setSingleShot(True)
        self._title_actions_timer.setInterval(30)
        self._title_actions_timer.timeout.connect(self._title_actions_tick)
        self._title_actions_anim = QVariantAnimation(self)
        self._title_actions_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._title_actions_anim.valueChanged.connect(self._set_title_actions_opacity)
        self._title_actions_anim.finished.connect(self._finish_title_actions_fade)
        self._title_hover_widgets = (
            self.title, self.title_actions, self.btn_collapse,
            self.btn_lock, self.btn_menu)
        root.addWidget(self.title)

        # 内容：文件列表页 / 路径失效页
        self.pages = QStackedLayout()
        root.addLayout(self.pages, 1)  # 先装进父控件再加页面：否则第一页成为当前页，
        page_list = QWidget()          # 会被 QStackedLayout 立刻 show()，无父状态下闪出白框
        gl = QGridLayout(page_list)
        gl.setContentsMargins(ui.sc(4), 0, ui.sc(4), ui.sc(4))
        self.list = BoxList(self)
        gl.addWidget(self.list, 0, 0)
        self.hint = QLabel(t('boxes.empty_hint'))
        self.hint.setObjectName('boxHint')
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        gl.addWidget(self.hint, 0, 0, Qt.AlignCenter)
        self.pages.addWidget(page_list)

        page_invalid = QWidget()
        il = QVBoxLayout(page_invalid)
        il.addStretch(1)
        pix = QLabel()
        pix.setAlignment(Qt.AlignCenter)
        pix.setPixmap(self._invalid_pm())
        t1 = QLabel(t('boxes.invalid.title'))
        t1.setObjectName('boxInvalid1')
        t1.setAlignment(Qt.AlignCenter)
        t2 = QLabel(t('boxes.invalid.detail'))
        t2.setObjectName('boxInvalid2')
        t2.setAlignment(Qt.AlignCenter)
        btn_refresh = QPushButton(t('common.refresh'))
        btn_refresh.setObjectName('boxRefresh')
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setToolTip(t('boxes.invalid.retry'))
        # 文件夹回来了 refresh 自己会扫目录切回列表页，没回来就停在失效页
        btn_refresh.clicked.connect(self.refresh)
        btn = QPushButton(t('boxes.dissolve'))
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.dissolve)
        il.addWidget(pix)
        il.addSpacing(ui.sc(6))
        il.addWidget(t1)
        il.addWidget(t2)
        il.addSpacing(ui.sc(10))
        row = QHBoxLayout()          # 刷新在左、解散在右，整体居中
        row.setSpacing(ui.sc(8))
        row.addStretch(1)
        row.addWidget(btn_refresh)
        row.addWidget(btn)
        row.addStretch(1)
        il.addLayout(row)
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

        # 桌面层级：归属桌面带（免疫 Win+D，面板同款 pin_to_desktop）+ 500ms 补挂看门狗。
        # 与面板的关键差异：永不主动沉底——格子被压到应用窗口之下
        # 就是用户眼里的「消失」。
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
        self.list.set_view(self.rec.get('view', 'list'))

    def _icon_for(self, path, is_dir):
        """QFileIconProvider 需要 QFileInfo；文件夹图标直接取 style 的标准图标更稳。
        .url 走 _url_icon：QFileIconProvider 不读文件里的 IconFile 指令，只给空白页图标。"""
        if not is_dir and path.lower().endswith('.url'):
            icon = self._url_icon(path)
            if icon is not None:
                return icon
        from PySide6.QtCore import QFileInfo
        from PySide6.QtWidgets import QFileIconProvider
        if not hasattr(self, '_icon_provider'):
            self._icon_provider = QFileIconProvider()
        return self._icon_provider.icon(QFileInfo(path))

    def _baked_icon(self, path, is_dir, size):
        """取壳图标后烘成纯位图 QIcon。QFileIconProvider 返回的 QIcon 不在内存缓存
        pixmap，每次 paint 都重新经壳生成——实测滚动一帧 20+ 行、每行 ~1.3ms，
        整帧 30ms 级掉帧（2026-10 滚动卡顿根因）；烘焙后 paint 只读内存位图
        （p50 30ms → 1.2ms）。DPR 按窗口取，高分屏不糊。

        2026-10 性能改造（启动瓶颈 #1）：按类型分流，不再一律在 GUI 线程同步问壳。
        - 缓存命中（同路径同尺寸问过壳）直接返回；
        - **快捷方式 / 可执行文件**（.lnk/.exe/…）：取图标要经壳解析 .lnk 目标，
          或从 PE 资源提取（实测 11.8MB 的 exe 要 3 秒）→ 放后台线程，主线程先给
          占位图标，真实图标取到后回填替换；
        - **普通文件 / 目录 / .url**：取图标很快（实测 0.006ms），同步取，
          渲染路径与原先完全一致（像素不变）。
        """
        dpr = self.devicePixelRatioF()
        if hasattr(size, 'width'):     # 调用方传的是 QSize（list.iconSize()）
            size = size.width()
        key = (path, is_dir, size, dpr)
        icon = _icon_cache.get(key)
        if icon is not None:
            return icon
        if _needs_async_icon(path, is_dir):
            self._request_icon(path, is_dir, size, dpr)
            return _placeholder_icon(is_dir, size)
        icon = self._icon_for(path, is_dir)
        pm = icon.pixmap(QSize(size, size), dpr)
        out = QIcon(pm) if not pm.isNull() else icon
        _icon_cache_put(key, out)
        return out

    def _request_icon(self, path, is_dir, size, dpr):
        """把图标提取排给后台线程（同一 key 只排一次，避免重复问壳）。"""
        key = (path, is_dir, size, dpr)
        if key in _icon_pending:
            return
        _icon_pending.add(key)
        px = max(1, int(round(size * dpr)))
        _icon_worker().submit(path, is_dir, size, px, dpr)

    def _url_icon(self, path):
        """解析 .url 里的 IconFile/IconIndex，ExtractIconExW 取图标（同资源管理器）；没有就返回 None。"""
        icon_file, idx = '', 0
        try:
            with open(path, encoding='utf-8', errors='ignore') as f:
                for raw in f:
                    line = raw.strip()
                    low = line.lower()
                    if low.startswith('iconfile='):
                        icon_file = os.path.expandvars(line[9:].strip())
                    elif low.startswith('iconindex='):
                        try:
                            idx = int(line[10:].strip())
                        except ValueError:
                            pass
        except OSError:
            return None
        if not icon_file or not os.path.isfile(icon_file):
            return None
        if icon_file.lower().endswith('.ico'):
            icon = QIcon(icon_file)   # Qt 原生读 ico（全尺寸一档收齐）
            return icon if not icon.isNull() else None
        h_big, h_small = ctypes.c_void_p(), ctypes.c_void_p()
        _s32.ExtractIconExW.restype = wintypes.UINT
        _s32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        if _s32.ExtractIconExW(icon_file, idx, ctypes.byref(h_big), ctypes.byref(h_small), 1) <= 0:
            return None
        u32 = ctypes.windll.user32
        u32.DestroyIcon.argtypes = [wintypes.HANDLE]
        icon = QIcon()
        # 列表视图用 16px、图标视图用 32px，两档都收；尺寸随系统图标档（DPI 会放大）
        for h, metric in ((h_small, 49), (h_big, 11)):   # SM_CXSMICON / SM_CXICON
            if h:
                img = _hicon_to_image(int(h.value), u32.GetSystemMetrics(metric))
                u32.DestroyIcon(int(h.value))
                if img is not None and not img.isNull():
                    icon.addPixmap(QPixmap.fromImage(img))
        return icon if not icon.isNull() else None

    def display_dir(self):
        """格子内容所在目录：映射格子是映射的目录，空白格子是桌面（文件都在桌面上）。"""
        return self.rec['path'] if self.rec['kind'] == 'folder' else desktop_dir()

    def _invalid_pm(self):
        """失效页缺省图：半透明灰圆角方块 + 文件夹剪影 + 问号（映射路径失效的占位提示）。"""
        s = ui.sc(64)
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 16))
        p.drawRoundedRect(QRect(0, 0, s, s), ui.sc(12), ui.sc(12))
        p.setBrush(QColor(255, 255, 255, 120))
        p.drawRoundedRect(QRect(ui.sc(15), ui.sc(18), ui.sc(14), ui.sc(7)),
                          ui.sc(2), ui.sc(2))                       # 文件夹 tab
        body = QRect(ui.sc(13), ui.sc(25), ui.sc(38), ui.sc(23))
        p.drawRoundedRect(body, ui.sc(3), ui.sc(3))
        p.setPen(QColor(38, 40, 47))
        f = QFont(ui.pick_fonts()[0])
        f.setPixelSize(ui.sc(16))
        f.setBold(True)
        p.setFont(f)
        p.drawText(body, Qt.AlignCenter, '?')
        p.end()
        return pm

    def refresh(self):
        """重新扫描填充列表；映射文件夹失效时切到失效页。
        空白格子按 rec['items'] 记账列文件（文件在桌面上），不再扫目录。"""
        if self._dragging:
            # 拖出期间不重建列表：文件此刻在暂存夹里（桌面目录变化会触发 watcher 刷新），
            # 这时候 clear() 会把拖拽源那一行清掉。拖完 startDrag 收尾会刷新。
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
        if sort == 'custom':
            # 自定义排序（拖放到白色引导线后）：空白格子按 items 记账顺序填充、不用排；
            # 映射格子按 rec['order'] 名字表排，表外新文件排最后
            key = None
            if self.rec['kind'] == 'folder':
                pos = {n: i for i, n in enumerate(self.rec.get('order') or [])}
                total = len(pos)
                key = lambda e: (pos.get(e[0], total), e[0].lower())
        elif sort == 'mtime':
            key = lambda e: (not e[2], -e[3].st_mtime, e[0].lower())
        elif sort == 'type':
            key = lambda e: (not e[2], os.path.splitext(e[0])[1].lower(), e[0].lower())
        else:
            key = lambda e: (not e[2], e[0].lower())
        if key is not None:
            entries.sort(key=key)

        self.list._lnk_dir_cache.clear()
        self.list.clear()
        self.list._icon_items.clear()
        size = self.list.iconSize()
        szw = size.width() if hasattr(size, 'width') else int(size)
        for name, p, is_dir, st in entries:
            disp = name[:-4] if name.lower().endswith(('.lnk', '.url')) else name   # 快捷方式不显示 .lnk/.url 后缀
            item = QListWidgetItem(self._baked_icon(p, is_dir, size), disp)
            item.setData(Qt.UserRole, p)
            item.setData(Qt.UserRole + 1, is_dir)   # 拖拽落点判定用：是否文件夹
            item.setToolTip(p)
            self.list.addItem(item)
            self.list._icon_items[p] = (item, szw)
        self.hint.setVisible(not entries and self.rec['kind'] == 'blank')
        # 标题图标只有映射格子有（空白格子隐藏了图标，只显示名称，见 __init__）
        if self.rec['kind'] == 'folder':
            self._apply_title_icon()

    def _apply_title_icon(self):
        """标题栏的小文件夹图标：同样「缓存优先 + 后台取」，不在 GUI 线程等壳。"""
        path = self.rec['path']
        size = ui.sc(16)
        dpr = self.devicePixelRatioF()
        key = (path, True, size, dpr)
        icon = _icon_cache.get(key)
        if icon is not None:
            self.icon.setPixmap(icon.pixmap(QSize(size, size), dpr))
            return
        self._request_icon(path, True, size, dpr)
        ph = _placeholder_icon(True, size).pixmap(QSize(size, size), dpr)
        if not ph.isNull():
            self.icon.setPixmap(ph)

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
        """空白格子的条目：只认记账过的路径，已消失的顺手从 items 和账本里剔除。
        拖出期间文件在暂存夹里，按暂存路径确认它还在（列表不能中途少一行）；
        托管文件（moved）按存放路径确认。条目路径用实际路径（图标/打开/拖出都按它），
        显示名仍用桌面身份的名字。"""
        attrs = self.rec.setdefault('attrs', {})
        moved = self.rec.setdefault('moved', {})
        items, entries, dirty = [], [], False
        for p in self.rec.get('items') or []:
            actual = self._dragging.get(p, moved.get(p, p))
            try:
                st = os.stat(actual)
            except OSError:
                if p in self._dragging:
                    continue     # 拖拽中的条目 stat 失败：等拖完收尾，先别动
                attrs.pop(p, None)   # 文件不在了（被删/被搬走）：账本一起划掉
                moved.pop(p, None)
                dirty = True
                continue
            if p not in moved and p not in self._dragging and self.isVisible() and \
                    not getattr(st, 'st_file_attributes', 0) & ATTR_HIDDEN:
                # 账在、图标还露着（拖拽中断等事故）：当场收回——先划掉旧账以实况
                # 重记，免得 _hide_icon 早退。实在收不起（藏不了也搬不动）才移出格子。
                attrs.pop(p, None)
                dirty = True
                if not self._collect(p):
                    ui._dbg('box: cannot hide %s; removed from box' % os.path.basename(p))
                    continue
                actual = moved.get(p, p)
                if actual != p:
                    try:
                        st = os.stat(actual)
                    except OSError:
                        moved.pop(p, None)
                        continue
            items.append(p)
            entries.append((os.path.basename(p), actual, os.path.isdir(actual), st))
        if dirty:
            self.rec['items'] = items
            self.mgr.save_rec(self)
        return entries

    def _rewatch(self):
        """重建目录监听。

        2026-10 性能/正确性改造：原先每次 refresh() 都 removePaths + addPath 重建一遍
        ——① 白费一次句柄重建；② **remove 与 add 之间的窗口里到达的变更被永久丢弃**
        （Windows 的 ReadDirectoryChangesW 缓冲区随 remove 一起丢弃），快速连续复制
        时列表会少文件。故只在被监听的路径真的变了时才重建。
        """
        # 空白格子看桌面：收进格子的文件在桌面被删/改名/剪切走都要跟着刷新
        watch = self.display_dir()
        want = watch if os.path.isdir(watch) else ''
        old = self.watcher.directories()
        if old and (not want or old == [want]):
            return          # 已经监听对了（或目标已不存在），不动
        if old:
            self.watcher.removePaths(old)
        if want:
            self.watcher.addPath(want)

    # ---------- 空白格子：桌面图标隐藏账本 ----------
    def _hide_icon(self, path):
        """把桌面图标藏起来 = 给文件加「隐藏」属性（资源管理器唯一支持的单项隐藏方式），
        原属性记进 rec['attrs'] 以便还原。本来就隐藏的（图标本来就不显示）不动、不记账。
        返回桌面是否真的看不见它了：SetFileAttributesW 可能被拒（实测：管理员 ACL 下发的
        企业图标只给普通用户读权限）——藏不掉的文件，调用方必须自己兜住。"""
        attrs = self.rec.setdefault('attrs', {})
        if path in attrs:
            return True
        old = _k32.GetFileAttributesW(path)
        if old == _INVALID_ATTRS:
            return False
        if old & ATTR_HIDDEN:
            return True
        if _k32.SetFileAttributesW(path, old | ATTR_HIDDEN):
            attrs[path] = old
            return True
        return False

    def _show_icon(self, path):
        """把桌面图标放出来：还原隐藏前的属性。"""
        old = self.rec.setdefault('attrs', {}).pop(path, None)
        if old is not None and os.path.exists(path):
            _k32.SetFileAttributesW(path, old)

    def _store_dir(self):
        """藏不掉的文件真搬进这里（%APPDATA%\\zbox\\Boxes\\<格子id>）；
        show_icons 时按 rec['moved'] 搬回桌面。"""
        d = os.path.join(self.mgr.box_root, self.rec['id'])
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            return None
        return d

    def _collect(self, p):
        """收进空白格子：优先只摘桌面图标（加隐藏属性，文件不动）；藏不掉
        （管理员 ACL 的文件，普通用户没有写属性权限）就退而真搬进格子存储目录，
        rec['moved'] 记「桌面路径 → 存放路径」，放回时按它搬回。
        两条路都走不通才返回 False（调用方拒收/移出格子）。"""
        moved = self.rec.setdefault('moved', {})
        if p in moved or self._hide_icon(p):
            return True
        d = self._store_dir()
        if not d:
            return False
        try:
            dst = os.path.join(d, _unique_name(d, os.path.basename(p)))
            shutil.move(p, dst)
        except OSError:
            return False
        moved[p] = dst
        return True

    def hide_icons(self):
        """收进格子：隐藏 items 的桌面图标；藏不掉的由 _collect 真搬进存储目录。"""
        for p in self.rec.get('items') or []:
            self._collect(p)
        _shell_refresh(desktop_dir())
        self.mgr.save_rec(self)

    def show_icons(self):
        """放回桌面：还原我们隐藏过的图标（关程序 / 解散格子 / 隐藏格子时调）。
        重新出现的图标由 Explorer 自行摆位——落在第一列从上往下第一个空位
        （用户眼里就是「跑到屏幕最左上角」，桌面满员时还会把原有图标挤下去且
        不回弹）——所以释放前后各做一次快照/修正：新图标挪到桌面图标末尾行，
        被挤的原有图标按快照摆回（_DesktopIconLayout，实测依据见其 docstring）。"""
        paths = list(self.rec.get('attrs') or {})
        moved = self.rec.get('moved') or {}
        lay = _DesktopIconLayout() if (paths or moved) else None
        before = lay.snapshot() if lay else None
        for p in paths:
            self._show_icon(p)
        # 托管文件搬回桌面（落点被占了就用重命名落点，账本身份跟着改）
        items = self.rec.get('items') or []
        back = []
        for p, stored in list(moved.items()):
            if not os.path.exists(stored):
                moved.pop(p, None)   # 存放文件已没：账划掉，items 由下次刷新一起划
                continue
            try:
                dst = os.path.join(os.path.dirname(p),
                                   _unique_name(os.path.dirname(p), os.path.basename(p)))
                shutil.move(stored, dst)
            except OSError:
                continue   # 搬不回去就保持托管，下次再放
            moved.pop(p, None)
            if p in items and dst != p:
                items[items.index(p)] = dst
            back.append(dst)
        _shell_refresh(desktop_dir())
        if lay:
            if before:
                lay.fixup([os.path.basename(p) for p in paths + back], before)
            lay.close()
        self.mgr.save_rec(self)

    def drag_effect(self, e=None):
        """拖拽悬停期间回报的落放效果——**只决定鼠标旁那个徽标显示什么**：默认报「移动」，
        按住 Ctrl 报「复制」（徽标变加号，落放时真复制，见 import_paths）。

        徽标是资源管理器按我们从 DragOver 报回的效果画的；而「源方会不会删文件」是另一件事：
        源方只在 Drop 那一步按我们报的效果决定要不要清理源文件（报 Move 而文件仍在原处 →
        它会把文件删掉；报 Copy → 什么都不做）。两件事解耦，实测（悬停报 Move + 落放报 Copy）：
        徽标显示「移动」，源文件安然无恙。真正搬没搬走由 drop_effect() 按实际结果回报。"""
        if e is not None and e.modifiers() & Qt.ControlModifier:
            return Qt.CopyAction
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


    # ---------- 文件操作 ----------
    def import_paths(self, paths, copy=False, dest=None, unhide=False):
        """拖入文件。dest = 落点命中的格子内文件夹（落到文件夹条目上 = 落进它，两类格子
        同此、纯物理搬/复制、不涉及账本）；否则落进格子根：文件夹格子真实移动到映射目录
        （copy=True 则复制、源保留——按住 Ctrl 的落放；跨格子拖动同此；跳过已在目录内/
        父目录拖进自己）；空白格子走 _group_paths 只收进账本、把桌面图标藏起来
        （藏不掉的由 _collect 真搬进存储目录）。unhide = 拖自空白格子（文件被我们藏着）：
        落进真实目录时摘掉隐藏位，否则落点看不见文件。空白格子目标不摘（收着就行）。
        返回实际收进来的落点路径列表（空白格子是桌面身份路径），供引导线落点
        插序用（见 BoxList.dropEvent）。"""
        if dest is not None:
            dest = os.path.normpath(dest)
            done = []
            for p in paths:
                p = os.path.normpath(p)
                if os.path.normcase(os.path.dirname(p)) == os.path.normcase(dest):
                    continue
                if os.path.isdir(p) and (dest == p or dest.startswith(p + os.sep)):
                    continue
                try:
                    d = os.path.join(dest, _unique_name(dest, os.path.basename(p)))
                    if copy:
                        if os.path.isdir(p):
                            shutil.copytree(p, d)
                        else:
                            shutil.copy2(p, d)
                    else:
                        shutil.move(p, d)
                    if unhide:
                        _strip_hidden(d)
                    done.append(d)
                except OSError:
                    pass
            self.refresh()
            return done
        if self.rec['kind'] == 'blank':
            added = self._group_paths(paths, copy=copy)
            self.refresh()
            return added
        dest = os.path.normpath(self.rec['path'])
        done = []
        for p in paths:
            p = os.path.normpath(p)
            if os.path.dirname(p) == dest:
                continue
            if os.path.isdir(p) and (dest == p or dest.startswith(p + os.sep)):
                continue
            try:
                dst = os.path.join(dest, _unique_name(dest, os.path.basename(p)))
                if copy:
                    if os.path.isdir(p):
                        shutil.copytree(p, dst)
                    else:
                        shutil.copy2(p, dst)
                else:
                    shutil.move(p, dst)
                if unhide:
                    _strip_hidden(dst)
                done.append(dst)
            except OSError:
                pass
        self.refresh()
        return done

    def apply_custom_order(self, ordered_paths):
        """切成自定义排序并记下这次的可见顺序（拖放落到白色引导线时调用）——
        排序菜单「按名称/按类型/按修改时间」三项勾勾因此全灭（sort='custom'，
        谁也不等于）。ordered_paths = 落放后期望的完整可见顺序（条目实际路径）。
        空白格子的账本身份是桌面路径，先把托管存放路径换回桌面身份再重排 items；
        映射格子只记文件名表 rec['order']，之后目录里多出来的新文件由 refresh
        排到表外末尾。"""
        self.rec['sort'] = 'custom'
        if self.rec['kind'] == 'blank':
            inv = {v: k for k, v in (self.rec.get('moved') or {}).items()}
            old = self.rec.get('items') or []
            old_set = set(old)
            items, seen = [], set()
            for a in ordered_paths:
                p = inv.get(a, a)
                if p in old_set and p not in seen:
                    items.append(p)
                    seen.add(p)
            items.extend(p for p in old if p not in seen)
            self.rec['items'] = items
        else:
            self.rec['order'] = [os.path.basename(p) for p in ordered_paths]
        self.mgr.save_rec(self)
        self.refresh()

    def _group_paths(self, paths, copy=False):
        """收进空白格子：不在桌面的先搬到桌面（「格子里的文件都在桌面」是这套模型的前提），
        再记账 + 收起桌面图标（_collect：只隐藏；藏不掉的真搬进存储目录）；
        同一文件（移动时）从别的空白格子里移出。copy=True = 复制收编（按住 Ctrl 的落放）：
        不论源在哪都复制一份到桌面、收副本，源文件原样保留。"""
        desk = os.path.normpath(desktop_dir())
        items = self.rec.setdefault('items', [])
        moved = self.rec.setdefault('moved', {})
        added = []
        refused = False
        for p in paths:
            p = os.path.normpath(p)
            if p in items or p in moved.values():
                continue   # 已是本格子的文件（含托管存放路径）：拖回来 = 原地不动
            if copy or os.path.normcase(os.path.dirname(p)) != os.path.normcase(desk):
                dst = os.path.join(desk, _unique_name(desk, os.path.basename(p)))
                try:
                    if copy:
                        if os.path.isdir(p):
                            shutil.copytree(p, dst)
                        else:
                            shutil.copy2(p, dst)
                    else:
                        shutil.move(p, dst)
                except OSError:
                    continue
                p = dst
            if self._collect(p):
                items.append(p)
                added.append(p)
            else:
                # 藏不了也搬不动（占用/权限）：不收，免得同一图标桌面格子里各一份
                ui._dbg('box: cannot hide %s; not added to box' % os.path.basename(p))
                refused = True
        if refused:
            self.flash()
        if not copy:
            self.mgr.ungroup_paths(added, self)   # 移动语义：同一文件从别的空白格子移出
        _shell_refresh(desk)
        self.mgr.save_rec(self)
        return added

    # ---------- 拖入（整窗，不只列表视口） ----------
    def dragEnterEvent(self, e):
        """只有文件列表视口注册了拖放目标，拖到标题栏/空白提示区/边缘时 Qt 找不到
        接受拖放的控件就整个忽略这次拖拽（鼠标变红色禁止图标，怎么都放不进去）。
        窗口自己接一份，收起状态（整格只剩标题栏）也就能收文件了。"""
        paths = self._drag_paths(e)
        if paths:
            e.setDropAction(self.drag_effect(e))
            e.accept()
            self.mgr._note_drag_enter_own()
        else:
            super(BoxWindow, self).dragEnterEvent(e)

    def dragMoveEvent(self, e):
        paths = self._drag_paths(e)
        if paths:
            e.setDropAction(self.drag_effect(e))
            e.accept()
            self.mgr.badge.show_text(_drop_text(e, self.rec['name']))
        else:
            super(BoxWindow, self).dragMoveEvent(e)

    def dragLeaveEvent(self, e):
        self.mgr.badge.done()
        self.mgr._note_drag_leave_own()
        super(BoxWindow, self).dragLeaveEvent(e)

    def dropEvent(self, e):
        self.mgr.badge.done()
        self.mgr._note_drag_enter_own()
        paths = self._drag_paths(e)
        if not paths:
            super(BoxWindow, self).dropEvent(e)
            return
        copy = bool(e.modifiers() & Qt.ControlModifier)   # 按住 Ctrl = 复制
        self.import_paths(paths, copy=copy, unhide=self._drop_from_blank(e))
        e.setDropAction(self.drop_effect(paths))   # 按实际搬没搬走回报
        e.accept()

    def _drag_paths(self, e):
        """外部拖进来的本地文件路径；格子内部拖拽（source 是自己的列表）不接。"""
        if e.source() is self.list:
            return []
        return [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]

    def _drop_from_blank(self, e):
        """这次拖拽是从我们的空白格子拖出来的（文件被我们藏着）→ 落进真实目录要摘隐藏位。"""
        md = e.mimeData()
        if md.hasFormat(_BOX_DRAG_MIME):
            sb = self.mgr.box_by_id(bytes(md.data(_BOX_DRAG_MIME).data()).decode('utf-8'))
            return sb is not None and sb.rec['kind'] == 'blank'
        return False

    def rename_item(self, old, new):
        """格子里改名（外壳菜单的「重命名」）：空白格子要跟着改记账——文件在桌面，
        路径变了；隐藏属性跟着文件走，账本的键也得跟着改，否则这个文件就成了
        「藏着但不在任何格子里」。托管文件的身份是桌面路径，同样跟着新文件名走。"""
        moved = self.rec.get('moved') or {}
        for desk_p, stored in list(moved.items()):
            if stored == old:
                moved.pop(desk_p)
                desk_new = os.path.join(os.path.dirname(desk_p), os.path.basename(new))
                moved[desk_new] = new
                items = self.rec.get('items') or []
                if desk_p in items:
                    items[items.index(desk_p)] = desk_new
                    self.rec['items'] = items
                self.mgr.save_rec(self)
                return
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
        if self.rec['kind'] == 'folder' and not os.path.isdir(self.rec['path'] or ''):
            # 映射文件夹被整个删掉时 watcher 静默失效、列表还停在旧内容：双击打开才发现
            # 路径没了。refresh 会切到失效页（缺省图 + 「刷新」重测），别白开不存在的路径。
            self.refresh()
            return
        try:
            os.startfile(path)
        except OSError:
            pass

    def reveal_path(self, path):
        subprocess.Popen(['explorer.exe', '/select,%s' % path])

    def delete_items(self, items):
        """Delete/右键删除：确认弹窗由外壳弹（资源管理器 Del 同款，含回收站设置）。"""
        if not items:
            return
        paths = [it.data(Qt.UserRole) for it in items]
        _recycle(paths, hwnd=int(self.winId()))
        self.refresh()

    # ---------- 格子操作 ----------
    def set_collapsed(self, on, save=True):
        self._hover_peek = False   # 真正展开/收起都结束预览态（预览期点 ▼ 展开后移开不再收回）
        self.rec['collapsed'] = on
        self.pages.currentWidget().setVisible(not on)
        self.btn_collapse.setText('▼' if on else '▲')
        self.btn_collapse.setToolTip(t('boxes.expand') if on else t('boxes.collapse'))
        if on:
            self.setFixedHeight(ui.sc(TITLE_H))
        else:
            self.setMinimumHeight(ui.sc(TITLE_H) + ui.sc(60))
            self.setMaximumHeight(16777215)
            self.resize(self.width(), self.rec.get('h') or ui.sc(DEF_H))
        if save:
            self.mgr.save_rec(self)

    # ---------- 收起态悬停预览 ----------
    def _peek_expand(self):
        """收起态悬停预览：临时展开内容页——不改 rec['collapsed']、不落盘，
        光标移开由 _peek_tick 收回。预览期点 ▼/双击标题走 set_collapsed 真正展开，
        之后移开不再收回。"""
        self._hover_peek = True
        self.pages.currentWidget().setVisible(True)
        self.setMinimumHeight(ui.sc(TITLE_H) + ui.sc(60))
        self.setMaximumHeight(16777215)
        self.resize(self.width(), self.rec.get('h') or ui.sc(DEF_H))

    def _peek_tick(self):
        """预览收回判定（leaveEvent 后每拍一问）：菜单/模态弹窗/文件拖出/窗口拖动
        进行中推迟；光标回窗内（enterEvent 有漏发场景，坐标说了算）停表。"""
        if not self._hover_peek:
            self._peek_timer.stop()
            return
        if QApplication.activePopupWidget() is not None or \
                QApplication.activeModalWidget() is not None or \
                self._dragging or self._op is not None:
            return   # 进行中，下一拍再看
        if self.geometry().contains(QCursor.pos()):
            self._peek_timer.stop()
            return
        self._peek_collapse()

    def _peek_collapse(self):
        """收回悬停预览（未在预览 = 空操作；期间被真正展开则不收）。"""
        self._peek_timer.stop()
        if not self._hover_peek:
            return
        self._hover_peek = False
        if not self.rec.get('collapsed'):
            return
        self.pages.currentWidget().setVisible(False)
        self.setFixedHeight(ui.sc(TITLE_H))

    def set_locked(self, on, save=True):
        self.rec['locked'] = on
        self.btn_lock.setText('🔒' if on else '🔓')
        self.btn_lock.setToolTip(t('boxes.unlock') if on else t('boxes.lock'))
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

    def _dissolve_confirm_dialog(self):
        """构造解散确认弹窗（截图自检也走这里，保证弹的就是真实弹窗）。"""
        if self.rec['kind'] == 'blank':
            detail = t('boxes.dissolve.blank_detail')
        else:
            detail = t('boxes.dissolve.folder_detail')
        return BoxConfirmDialog(self, t('boxes.dissolve'),
                                t('boxes.dissolve.confirm', name=self.rec['name'], detail=detail),
                                t('boxes.dissolve.ok'))

    def _confirm_dissolve(self):
        """解散二次确认：空白格子提示文件会回到桌面，映射格子提示不影响原文件夹。"""
        return self._dissolve_confirm_dialog().exec() == QDialog.Accepted

    def dissolve(self):
        """解散格子：空白格子把桌面图标放出来（文件本来就在桌面，不搬动文件）；
        映射格子只是移除格子。"""
        if not self._confirm_dissolve():
            return
        if self.rec['kind'] == 'blank':
            self.show_icons()
        self.mgr.remove(self)

    def _build_menu(self):
        """构造 ≡ 菜单（截图自检也走这里，保证弹的就是真实菜单）。"""
        menu = QMenu(self)
        grp = QActionGroup(menu)
        for key, label in VIEW_CHOICES:
            act = menu.addAction(t(label))
            act.setCheckable(True)
            act.setChecked(self.rec.get('view', 'list') == key)
            grp.addAction(act)
            act.triggered.connect(lambda _c=False, k=key: self._set_view(k))
        menu.addSeparator()
        grp = QActionGroup(menu)
        for key, label in SORT_CHOICES:
            act = menu.addAction(t(label))
            act.setCheckable(True)
            act.setChecked(self.rec.get('sort', 'name') == key)
            grp.addAction(act)
            act.triggered.connect(lambda _c=False, k=key: self._set_sort(k))
        menu.addSeparator()
        menu.addAction(t('boxes.rename'), self._start_rename)
        if self.rec['kind'] == 'folder':
            menu.addAction(t('boxes.tooltip.open_folder'),
                           lambda: self.open_path(self.rec['path']))
        menu.addAction(t('boxes.dissolve'), self.dissolve)
        return menu

    def _show_menu(self):
        self._title_actions_hold = True
        try:
            self._build_menu().exec(QCursor.pos())
        finally:
            self._title_actions_hold = False
            self._schedule_title_actions_hide()

    def _set_title_actions_opacity(self, value):
        self._title_actions_effect.setOpacity(max(0.0, min(1.0, float(value))))

    def _finish_title_actions_fade(self):
        value = 0.0 if self._title_actions_target <= 0 else 1.0
        self._set_title_actions_opacity(value)
        self.title_actions.setAttribute(Qt.WA_TransparentForMouseEvents, value <= 0)

    def _show_title_actions(self):
        self._title_actions_timer.stop()
        if self._title_actions_target == 1.0 and \
                (self._title_actions_anim.state() == QVariantAnimation.Running
                 or self._title_actions_effect.opacity() >= 1.0):
            return
        self._fade_title_actions(1.0)

    def _hide_title_actions(self, immediate=False):
        if self._title_actions_hold and not immediate:
            return
        self._title_actions_timer.stop()
        if immediate:
            self._title_actions_anim.stop()
            self._title_actions_target = 0.0
            self._finish_title_actions_fade()
            return
        if self._title_actions_target == 0.0 and \
                (self._title_actions_anim.state() == QVariantAnimation.Running
                 or self._title_actions_effect.opacity() <= 0.0):
            return
        self._fade_title_actions(0.0)

    def _fade_title_actions(self, target):
        self._title_actions_anim.stop()
        self._title_actions_target = target
        self.title_actions.setAttribute(Qt.WA_TransparentForMouseEvents, target <= 0)
        self._title_actions_anim.setDuration(140 if target > 0 else 180)
        self._title_actions_anim.setStartValue(self._title_actions_effect.opacity())
        self._title_actions_anim.setEndValue(target)
        self._title_actions_anim.start()

    def _schedule_title_actions_hide(self):
        if not self._title_actions_hold and \
                self._title_actions_effect.opacity() > 0.0:
            self._title_actions_timer.start()

    def _title_actions_tick(self):
        if self._title_actions_hold or \
                QApplication.activePopupWidget() is not None or \
                QApplication.activeModalWidget() is not None:
            return
        if self.title.rect().contains(self.title.mapFromGlobal(QCursor.pos())):
            return
        self._hide_title_actions()

    def _set_view(self, key):
        self.rec['view'] = key
        self.mgr.save_rec(self)
        self.list.set_view(key)

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
        dv = ui.find_desktop_defview()
        if dv and ui._u32.GetAncestor(hwnd, ui._GA_PARENT) != dv:
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
        """看门狗只做两件极廉的事：自身存活检查 + 桌面带补挂。
        不做跨进程命中探测——WindowFromPoint 会向命中窗口同步发 WM_NCHITTEST，
        对方线程不消息循环就把 UI 线程整段卡死（2026-10 实测多次秒级冻结，
        探测随桌面整理软件兼容层整体移除；装了桌面整理软件时格子可能被
        它的覆盖层压住，属已知取舍）。"""
        hwnd = int(self.winId())
        if not ui._u32.IsWindow(hwnd):
            self._sink_timer.stop()
            return
        self._ensure_band()

    # ---------- 绘制 ----------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 圆角裁切区（alpha=0）在分层窗口里是点击穿透的——右下角缩放命中带大半落在
        # 裁切区里，点上去事件全漏给桌面（「连拖几次失效」根因之一）。先整窗铺一层
        # alpha=1 的不可见填充：视觉不变，命中恢复。
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setBrush(QColor(25, 28, 34, 140))
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
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
        if obj in self._title_hover_widgets:
            if e.type() == QEvent.Enter:
                self._show_title_actions()
            elif e.type() == QEvent.Leave:
                self._schedule_title_actions_hide()
        # 映射格子的文件夹图标：左键按下打开所在文件夹。
        # 三类鼠标事件都吃掉——按下不放给父窗口（否则进拖动）、双击不收起、
        # 双击的第二次松开也不再开一次
        if obj is self.icon and self.rec['kind'] == 'folder':
            if e.type() == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
                self.open_path(self.rec['path'])
                return True
            if e.type() in (QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
                return True
        # 名称标签双击 → 内联重命名；吃掉事件，不再传给父窗口触发收起
        if obj is self.name and e.type() == QEvent.MouseButtonDblClick:
            self._start_rename()
            return True
        # 输入框里 Esc 取消：失焦会触发 editingFinished，借 _edit_cancel 跳过提交
        if obj is self.edit and e.type() == QEvent.KeyPress and e.key() == Qt.Key_Escape:
            self._edit_cancel = True
            self.edit.clearFocus()
            return True
        # 列表视口会吃掉左键按下（选中项），父窗口收不到——底部边缘和两个下角的
        # 缩放从这里起；起缩放后移动/松开同样发给视口，直接在过滤器里驱动到底。
        if obj is self.list.viewport():
            if e.type() == QEvent.MouseButtonPress and e.button() == Qt.LeftButton \
                    and not self.rec.get('locked') and not self.rec.get('collapsed'):
                edges = self._hit_edges(obj.mapTo(self, e.pos()))
                if edges:
                    self._op = ('resize', edges, e.globalPos(), self.geometry())
                    self._press_pos = e.globalPos()
                    self._snap_sticky = (None, None)
                    if self._snap_guide is not None:
                        self._snap_guide.hide()
                    return True
            if self._op and self._op[0] == 'resize':
                if e.type() == QEvent.MouseMove:
                    self._apply_resize(e.globalPos())
                    return True
                if e.type() == QEvent.MouseButtonRelease:
                    self._finish_op(e.globalPos())
                    return True
        # 子控件上的 MouseMove 转成窗口坐标同步光标（子控件不设光标，跟随窗口）
        if e.type() == QEvent.MouseMove and not self._op:
            self._sync_cursor(obj.mapTo(self, e.pos()))
        return super(BoxWindow, self).eventFilter(obj, e)

    def enterEvent(self, e):
        self.list.set_scrollbars_visible(True)
        self.unsetCursor()   # 从窗外划入时复位，不残留上次的缩放箭头
        self._peek_timer.stop()
        if self.rec.get('collapsed') and not self._hover_peek:
            self._peek_expand()   # 收起态悬停标题栏 = 临时展开预览，移开收回
        super(BoxWindow, self).enterEvent(e)

    def leaveEvent(self, e):
        self.list.set_scrollbars_visible(False)
        self.unsetCursor()
        if self._hover_peek:
            self._peek_timer.start()   # 延迟一拍判定：瞬移出窗/弹菜单的误收由 _peek_tick 挡
        super(BoxWindow, self).leaveEvent(e)

    def hideEvent(self, e):
        # 双击桌面全隐藏等整体隐藏路径：预览态直接收回，恢复显示时保持收起形态
        self._peek_collapse()
        self._hide_title_actions(immediate=True)
        if self._snap_guide is not None:
            self._snap_guide.hide()
        super(BoxWindow, self).hideEvent(e)

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
            self._snap_sticky = (None, None)
            if self._snap_guide is not None:
                self._snap_guide.hide()

    def mouseMoveEvent(self, e):
        if not self._op:
            self._sync_cursor(e.pos())
            super(BoxWindow, self).mouseMoveEvent(e)
            return
        kind, edges, start_pos, start_geo = self._op
        if kind == 'move':
            proposed = QRect(start_geo)
            proposed.moveTopLeft(start_geo.topLeft() + (e.globalPos() - start_pos))
            targets = self.mgr.snap_card_rects(exclude=self)
            snapped, self._snap_sticky = snap_move(
                proposed, targets, engage=ui.sc(SNAP_ENGAGE),
                release=ui.sc(SNAP_RELEASE), sticky=self._snap_sticky)
            self.move(snapped.topLeft())
            self._update_snap_guide(snapped, targets, self._snap_sticky)
            self.activateWindow()
        else:
            self._apply_resize(e.globalPos())

    def _update_snap_guide(self, source, targets, matches):
        segments = guide_segments(source, targets, matches, cap=ui.sc(8))
        if segments:
            if self._snap_guide is None:
                self._snap_guide = SnapGuideOverlay(
                    self, scale=ui.ui_scale())
            self._snap_guide.show_segments(segments)
        elif self._snap_guide is not None:
            self._snap_guide.hide()

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
            targets = self.mgr.snap_card_rects(exclude=self)
            snapped, self._snap_sticky = snap_resize(
                r, edges, targets, engage=ui.sc(SNAP_ENGAGE),
                release=ui.sc(SNAP_RELEASE), sticky=self._snap_sticky)
            if snapped.width() >= self.minimumWidth() and \
                    snapped.height() >= self.minimumHeight():
                self.setGeometry(snapped)
                self._update_snap_guide(snapped, targets, self._snap_sticky)
            else:
                self._snap_sticky = (None, None)
                self.setGeometry(r)
                self._update_snap_guide(r, targets, self._snap_sticky)
        else:
            self._snap_sticky = (None, None)
            if self._snap_guide is not None:
                self._snap_guide.hide()

    def mouseReleaseEvent(self, e):
        if self._op:
            self._finish_op(e.globalPos())
        super(BoxWindow, self).mouseReleaseEvent(e)

    def _finish_op(self, global_pos):
        """拖动/缩放收尾（mouseReleaseEvent 与视口事件过滤器共用）。"""
        self._op = None
        self._snap_sticky = (None, None)
        if self._snap_guide is not None:
            self._snap_guide.hide()
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
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        ag = screen.availableGeometry()
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
        # 2026-10 性能审计 P1-7：原轮询用 time.sleep(0.1) —— **GUI 线程整个睡
        # 住**，最坏 3 秒界面无响应。改用 processEvents 推进（且排除用户输入
        # 事件，避免重入到用户的点击里），并把间隔改成指数退避，减少跨进程枚举次数。
        t0 = time.time()
        found = {}
        delay = 0.05
        while time.time() - t0 < timeout:
            icons = self.enum_icons()
            found = {}
            for b in basenames:
                m = self._match(icons, before, b)
                if m:
                    found[b] = m
            if len(found) >= len(basenames):
                break
            # 让界面保持响应（绘制/定时器照常跑），但不处理用户输入（防重入）
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
            time.sleep(delay)
            delay = min(delay * 1.6, 0.25)
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

    def restore_positions(self, saved):
        """启动恢复：把桌面图标摆回记住的位置（saved = {小写显示名: [x, y]}）。
        按显示名匹配，位置不同才 SET；快照里没有的新图标不动，
        快照里有但桌面已没有（删掉 / 收进格子）的跳过。自动排列桌面 ok=False 早退。"""
        if not self.ok or not saved:
            return
        for i, n, x, y in self.enum_icons():
            pos = saved.get(n.lower())
            if pos and (x, y) != (pos[0], pos[1]):
                self._set_pos(i, pos[0], pos[1])


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


_CLSID_SHELL_LINK = _guid('{00021401-0000-0000-C000-000000000046}')
_IID_IShellLinkW = _guid('{000214F9-0000-0000-C000-000000000046}')
_IID_IPersistFile = _guid('{0000010B-0000-0000-C000-000000000046}')


def _lnk_target_path(path):
    """解析 .lnk 快捷方式的目标路径（不限于目录）；失败返回 None。

    与 _lnk_target_dir 同源的 COM 代码，但取任意目标路径 —— 图标提取要用：
    资源管理器显示快捷方式时显示的是**目标程序的图标**，而 SHGetFileInfoW /
    ExtractIconExW 对 .lnk 只给「快捷方式」默认图标。
    ⚠️ IShellLinkW 是 STA 类：在 MTA 线程创建会由 COM 安排到某个 STA 承载
    （本进程 GUI 线程是 STA —— 见 main.pyw 的 CoInitializeEx(0x2)）。
    这段只在**后台线程**调用，不能挪到 GUI 线程热路径上。
    """
    hr_init = _o32.CoInitializeEx(None, 0x2)   # COINIT_APARTMENTTHREADED
    own_com = hr_init in (0, 1)   # S_OK / S_FALSE
    psl = ctypes.c_void_p()
    hr = _o32.CoCreateInstance(ctypes.byref(_CLSID_SHELL_LINK), None, 1,
                               ctypes.byref(_IID_IShellLinkW), ctypes.byref(psl))
    if hr or not psl.value:
        if own_com:
            _o32.CoUninitialize()
        return None
    ppf = ctypes.c_void_p()
    try:
        _com_fn(psl, 0, ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p)(
            psl, ctypes.byref(_IID_IPersistFile), ctypes.byref(ppf))
        if not ppf.value:
            return None
        _com_fn(ppf, 5, ctypes.HRESULT,
                wintypes.LPCWSTR, wintypes.DWORD)(ppf, path, 0)
        buf = ctypes.create_unicode_buffer(1024)
        _com_fn(psl, 3, ctypes.HRESULT,
                wintypes.LPWSTR, ctypes.c_int,
                ctypes.c_void_p, wintypes.DWORD)(psl, buf, 1024, None, 0)
        return buf.value or None
    except OSError:
        return None
    finally:
        if ppf.value:
            _com_fn(ppf, 2, wintypes.UINT)(ppf)
        _com_fn(psl, 2, wintypes.UINT)(psl)
        if own_com:
            _o32.CoUninitialize()


def _lnk_target_dir(path):
    """解析 .lnk 快捷方式的目标：目标是现存目录 → 返回其路径，否则 None。
    文件夹快捷方式的拖放语义与文件夹一致（落上去 = 移进目标目录，资源管理器同款）。
    IShellLinkW 线程模型是 Apartment，从 Qt 初始化的 MTA 线程创建会被 COM 编组到
    宿主 STA 同步执行——阻塞往返，不需要本线程泵消息。"""
    # COM 公寓自初始化：应用里 Qt 已把 GUI 线程初始化成 MTA（返回 S_FALSE/RPC_E_CHANGED_MODE，
    # 都无妨）；没初始化过的线程（离屏测试等）也能用。S_OK/S_FALSE 才配对 CoUninitialize
    hr_init = _o32.CoInitializeEx(None, 0x2)   # COINIT_APARTMENTTHREADED
    own_com = hr_init in (0, 1)   # S_OK / S_FALSE
    psl = ctypes.c_void_p()
    hr = _o32.CoCreateInstance(ctypes.byref(_CLSID_SHELL_LINK), None, 1,   # CLSCTX_INPROC_SERVER
                               ctypes.byref(_IID_IShellLinkW), ctypes.byref(psl))
    if hr or not psl.value:
        if own_com:
            _o32.CoUninitialize()
        return None
    ppf = ctypes.c_void_p()
    # ctypes 对 HRESULT 返回值会自动把失败码抛成 OSError，失败语义统一走 except
    try:
        _com_fn(psl, 0, ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p)(
            psl, ctypes.byref(_IID_IPersistFile), ctypes.byref(ppf))   # QueryInterface
        if not ppf.value:
            return None
        _com_fn(ppf, 5, ctypes.HRESULT,
                wintypes.LPCWSTR, wintypes.DWORD)(ppf, path, 0)   # IPersistFile::Load(STGM_READ)
        buf = ctypes.create_unicode_buffer(1024)
        _com_fn(psl, 3, ctypes.HRESULT,
                wintypes.LPWSTR, ctypes.c_int,
                ctypes.c_void_p, wintypes.DWORD)(psl, buf, 1024, None, 0)   # IShellLinkW::GetPath
        if not buf.value:
            return None
        return buf.value if os.path.isdir(buf.value) else None
    except OSError:
        return None
    finally:
        if ppf.value:
            _com_fn(ppf, 2, wintypes.UINT)(ppf)   # Release
        _com_fn(psl, 2, wintypes.UINT)(psl)
        if own_com:
            _o32.CoUninitialize()


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
                    label = {'open': t('boxes.verb.open'), 'edit': t('boxes.verb.edit'),
                             'print': t('boxes.verb.print')}.get(v, v)
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

    result = Signal(int)

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
            ui._dbg('host started pid=%s exe_mtime=%s path=%s'
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

    def request(self, hwnd, paths, x, y, on_rename):
        key = (int(hwnd), tuple(paths))
        if self.callbacks:
            if time.time() - self._req_ts > 15:
                # 看门狗：上一请求 15s 无响应且又来了新请求 = 宿主卡死
                # （菜单开着时用户再点右键会先经 TPM_RECURSE 取消旧菜单，
                # R 必然已回，所以在途 15s+ 还有新请求不可能是正常弹窗）。
                # 杀掉重启自愈——宿主与它弹的菜单一起消失，前台与输入随即释放。
                ui._dbg('ctxmenu: host unresponsive for 15s; killing and restarting')
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
            head = 'M %d %d %d %d\n' % (int(hwnd), len(paths), int(x), int(y))
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
            ui._dbg('ctxmenu: R=%d elapsed=%.2fs in-flight=%d'
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
    含 Defender 扫描 / IExplorerCommand 项 / 全量图标，菜单随系统明暗）。
    x/y 是右键按下那一刻的物理屏幕坐标：经管道到宿主再建壳菜单要几十~几百毫秒，
    弹窗时再取光标会跟着鼠标跑，所以坐标由调用方钉死随请求发过去。
    宿主缺失回退 ctypes 实现（CDefFolderMenu_Create2，少几个需要宿主环境的扩展项）。
    on_rename：宿主路径下用户选「重命名」时回调（异步，菜单关闭后触发）。
    返回 True=已接管；'rename'=ctypes 路径选了重命名；False=回退内置菜单。"""
    if not paths:
        return False
    ui._dbg('ctxmenu: %d item(s), first=%s' % (len(paths), os.path.basename(paths[0])))
    # 置前台权限在 _HostDaemon.request 里授（只给宿主自己的 pid）：不授权的话，
    # 焦点刚变过（Win+D 回桌面 / 切过别的程序）的首次右键，宿主 SetForegroundWindow
    # 失败，菜单弹出即被取消——表现为首次右键无效。
    if _get_daemon().request(hwnd, paths, x, y, on_rename):
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


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('pt', wintypes.POINT), ('mouseData', wintypes.DWORD),
                ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.c_size_t)]   # ULONG_PTR


_LOWLEVELPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                   ctypes.c_size_t, ctypes.c_size_t)


def _hit_desktop(pt, own, my_pid, sw, sh, blank_only):
    """桌面命中测试（DesktopClickHook 双击判定与 DesktopRightClickHook 右键拦截共用）。
    命中窗口沿父链走：先碰到我们自己的窗口（own）则忽略；SysListView32/SHELLDLL_DefView
    只有根窗口是 Progman/WorkerW 才是桌面（资源管理器窗口里也有这两个壳视图）；
    桌面整理软件的全屏覆盖层也算（全屏工具窗判定见 app._is_desktop_surface）。
    blank_only=True 时点中图标/文件夹不算空白（双击文件夹不能触发显隐）；右键拦截不需要区分。"""
    h = ui._u32.WindowFromPoint(pt)
    pid = wintypes.DWORD()
    ui._u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if pid.value == my_pid:
        # 本进程窗口一律不算桌面：文件夹选择框等系统对话框跑在本进程里，
        # 内嵌 SysListView32，不挡会在框里双击空白时误判成双击桌面
        return False
    while h:
        if h in own:
            return False
        cls = ui._class_name(h)
        if cls == 'SysListView32' or cls == 'SHELLDLL_DefView':
            if ui._class_name(ui._u32.GetAncestor(h, ui._GA_ROOT)) not in ('Progman', 'WorkerW'):
                return False
            if not blank_only:
                return True
            # 点在图标/文件夹上不算空白：双击文件夹不能触发显隐
            return cls == 'SHELLDLL_DefView' or not _desktop_icon_at(h, pt)
        if cls in ui._PROG_FAMILY:
            return True
        # 桌面整理软件的全屏覆盖层也算桌面
        if ui._is_desktop_surface(h, sw, sh):
            return True
        h = ui._u32.GetParent(h)
    return False


class DesktopClickHook(QThread):
    """双击桌面空白处 → 显隐全部格子。
    WH_MOUSE_LL 看不到 WM_LBUTTONDBLCLK（它是投递时才合成的），
    所以自己按 GetDoubleClickTime + SM_C?DOUBLECLK 判定双击。
    命中窗口沿父链走：先碰到我们自己的窗口（格子/面板）则忽略；
    碰到桌面家族（Progman/SHELLDLL_DefView/WorkerW/SysListView32）才算桌面。
    单击桌面空白另外发 single_clicked：清掉所有格子的文件选中——格子是桌面带
    Tool 窗，点桌面不会让它自己失焦，选中高亮会一直挂着。"""

    double_clicked = Signal()
    single_clicked = Signal()

    def __init__(self, own_hwnds, parent=None):
        super(DesktopClickHook, self).__init__(parent)
        self.own_hwnds = own_hwnds   # callable -> set(int)
        self._stop = False

    def run(self):
        # _stop 必须在 run() 开头清掉：stop() 置位后再次 start() 会重进 run()，
        # 不清的话 while 条件立刻为假、线程秒退——设置里把开关关掉再打开，
        # 双击功能就永久失效（2026-10 用户实测，docstring 却写着「重启是安全的」）。
        self._stop = False
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
            return _hit_desktop(pt, self.own_hwnds(), my_pid, sw, sh, blank_only=True)

        # 轮询左键代替 LL 钩子：只在本线程内做事，_is_desktop 的跨进程命中测试
        # 最坏多占几毫秒，也绝不影响系统鼠标管道。
        # 一次「按下」两条路都认——低位记账（0x0001 = 距上次调用以来按下过）或高位沿
        # （0x8000 当前态由松到按）：只看高位沿的话，触摸板轻点/快速点击的按下-松开可
        # 整个落在两次轮询之间被漏掉，双击丢一击 → 「双击显隐有时不灵」（2026-10 用户
        # 实测）；只看低位又不行——低位会被**别的进程**调 GetAsyncKeyState 抢先读走
        # （MSDN 注明，实测注入点击时低位置位也不稳定），所以高位沿留着兜底。
        prev_down = False
        while not self._stop:
            v = u32.GetAsyncKeyState(0x01)   # VK_LBUTTON
            down = bool(v & 0x8000)
            if (v & 0x0001) or (down and not prev_down):
                pt = wintypes.POINT()
                u32.GetCursorPos(ctypes.byref(pt))
                # 命中判定要兜异常：落盘 + 本轮放弃，不能拖垮轮询线程
                try:
                    on_desktop = _is_desktop(pt)
                    now = time.time()
                    if on_desktop:
                        self.single_clicked.emit()
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
            time.sleep(0.01)

    def stop(self):
        self._stop = True
        self.wait(2000)


class DesktopRightClickHook(QThread):
    """全隐藏态专用：WH_MOUSE_LL 吞掉落在桌面上的右键（Explorer 收不到，系统菜单不弹），
    再发信号让 GUI 线程弹自己的单项菜单「显示桌面图标」。只在全隐藏期间安装钩子、
    恢复显示立即卸载——平时对系统鼠标零开销。
    与文件头「不用 WH_MOUSE_LL」的教训不冲突：那里反对的是常驻全量钩子（每个鼠标
    事件都等 Python 回调拿 GIL）；这里钩子短命、回调只做一次 wParam 比较就放行，
    只有右键按下才做命中测试。两个硬约束：
    - WH_MOUSE_LL 回调靠安装线程的消息泵派发，且事件要等钩子链返回才投递给目标
      窗口，所以 run() 必须用阻塞式 GetMessage 泵——轮询泵会给全系统鼠标事件加延迟；
    - ctypes 回调里的异常不走 sys.excepthook、还会向系统返回垃圾值，必须就地兜住落盘。"""

    right_clicked = Signal()
    # 菜单开着时点了菜单以外：True = 桌面右键（关掉并在新位置重弹），False = 只关掉
    outside_clicked = Signal(bool)

    def __init__(self, own_hwnds, parent=None):
        super(DesktopRightClickHook, self).__init__(parent)
        self.own_hwnds = own_hwnds   # callable -> set(int)
        self.menu_open = False   # GUI 线程写：单项菜单开着时，钩子接管菜单以外的点击
        self._stop = False
        self._tid = None

    def start(self):
        # _stop 由 start() 清而不是 run() 清：run() 清会丢掉「stop 抢在 run 进泵前」的
        # 竞态（run 把自己刚被置位的 _stop 又抹掉，泵就永远退不出）
        self._stop = False
        super(DesktopRightClickHook, self).start()

    def run(self):
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        # windll 默认按 32 位 int 截断参数/返回值，64 位下句柄与指针必须先声明原型
        u32.SetWindowsHookExW.restype = ctypes.c_void_p
        u32.SetWindowsHookExW.argtypes = [ctypes.c_int, _LOWLEVELPROC,
                                          ctypes.c_void_p, wintypes.DWORD]
        u32.CallNextHookEx.restype = ctypes.c_ssize_t
        u32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                       ctypes.c_size_t, ctypes.c_size_t]
        u32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        u32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                           ctypes.c_size_t, ctypes.c_size_t]
        self._tid = k32.GetCurrentThreadId()
        if self._stop:   # stop() 抢在进泵前到了（_tid 未设，WM_QUIT 发不出）：别装钩子直接退
            self._tid = None
            return
        my_pid = k32.GetCurrentProcessId()
        sw = u32.GetSystemMetrics(0)
        sh = u32.GetSystemMetrics(1)
        sw_l = [False]   # 左/右键按下被吞时，对应松开/双击也要吞，
        sw_r = [False]   # 否则桌面收到一个没有按下的 BUTTONUP

        def proc(nCode, wParam, lParam):
            try:
                if nCode == 0:   # HC_ACTION；nCode < 0 时 lParam 无效，必须直接放行
                    if wParam in (0x0201, 0x0204):   # WM_LBUTTONDOWN / WM_RBUTTONDOWN
                        right = wParam == 0x0204
                        ms = ctypes.cast(lParam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                        h = ui._u32.WindowFromPoint(ms.pt)
                        pid = wintypes.DWORD()
                        ui._u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                        if pid.value == my_pid:
                            pass   # 自己进程的窗口（含弹出的菜单）：Qt 自己处理，点菜单项才点得上
                        elif self.menu_open:
                            # 菜单开着时点外面（Qt 的弹窗抓取抓不住桌面点击——SetCapture
                            # 只在抓取时有按键按住才管别的线程窗口，菜单是从队列信号弹出的，
                            # 所以「点外面关闭」只能由钩子代劳）：
                            # 左键/点别的应用 = 发信号关掉；桌面右键 = 发信号关掉并在新位置重弹
                            on_desktop = _hit_desktop(ms.pt, self.own_hwnds(), my_pid, sw, sh,
                                                      blank_only=False)
                            self.outside_clicked.emit(bool(right and on_desktop))
                            if on_desktop:
                                (sw_r if right else sw_l)[0] = True
                                return 1   # 桌面上的点击吞掉：系统菜单不弹、框选不发生
                            # 点在别的应用窗口：放行让窗口正常激活，菜单由信号关掉
                        elif right and _hit_desktop(ms.pt, self.own_hwnds(), my_pid, sw, sh,
                                                    blank_only=False):
                            sw_r[0] = True
                            self.right_clicked.emit()   # 队列到 GUI 线程弹菜单
                            return 1   # 吞掉：Explorer 收不到这次点击，系统菜单不弹
                    elif wParam == 0x0202 and sw_l[0]:   # WM_LBUTTONUP
                        sw_l[0] = False
                        return 1
                    elif wParam == 0x0203 and sw_l[0]:   # WM_LBUTTONDBLCLK
                        return 1
                    elif wParam == 0x0205 and sw_r[0]:   # WM_RBUTTONUP
                        sw_r[0] = False
                        return 1
                    elif wParam == 0x0206 and sw_r[0]:   # WM_RBUTTONDBLCLK
                        return 1
            except Exception:
                _log_hook_error()
            return u32.CallNextHookEx(None, nCode, wParam, lParam)

        cb = _LOWLEVELPROC(proc)   # 必须留住引用：回调被 GC 后系统再来消息 = 进程崩
        hook = u32.SetWindowsHookExW(14, cb, None, 0)   # WH_MOUSE_LL
        if not hook:
            return   # 装不上就降级：桌面右键只剩注册表那枚单项菜单（系统菜单照常弹）
        msg = wintypes.MSG()
        while not self._stop:
            r = u32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r <= 0:   # 0 = WM_QUIT（stop() 投递），-1 = 错误
                break
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))
        u32.UnhookWindowsHookEx(hook)
        self._tid = None

    def stop(self):
        self._stop = True
        tid = self._tid
        if tid and self.isRunning():
            # 唤醒阻塞在 GetMessage 的泵让它看到 _stop。
            # 时序安全：run() 先设 _tid 再进泵——tid 读到了就一定能唤醒；
            # tid 还没设说明 run() 未进泵，_stop 置位会让它装完钩子前直接退。
            ctypes.windll.user32.PostThreadMessageW(tid, 0x0012, 0, 0)   # WM_QUIT
        self.wait(2000)


class _DragBadge(QLabel):
    """格子拖拽的落点提示徽标：跟随光标的「移动到 XX / 复制到 XX」浮签。
    **2026-10 起整体停用**（show_text 直接隐藏，见那里）：系统气泡已说明移动/复制，
    落点另有白色引导线/整行高亮框反馈，不再叠第二行文字。
    系统拖拽气泡（白色浮窗）的文字改不了：Qt 自绘拖拽光标、不走 IDragSourceHelper2，
    DropDescription 写了也不渲染；外来拖拽的气泡归 Explorer 的 DoDragDrop 画，改文字要
    对 OLE 数据对象 SetData，Qt 不暴露这个指针（均实测）。所以自绘并让位：
    外来拖拽时系统气泡占光标下方一段，徽标再往下让；进程内拖拽让到跟随图之下
    （drag_pm_h 由 startDrag 记）。鼠标穿透（WA_TransparentForMouseEvents →
    WS_EX_TRANSPARENT，OLE 命中测试跳过它，绝不挡落放），置顶跟随光标。
    显示驱动全在落点侧：格子/落放层的 dragMove 里按落点更新文字，dragLeave/drop/
    拖拽结束收起。"""

    def __init__(self):
        super(_DragBadge, self).__init__(None, Qt.FramelessWindowHint | Qt.Tool
                                         | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet('QLabel { background: rgba(30, 32, 38, 235); color: #f2f2f2;'
                           ' border-radius: %dpx; padding: %dpx %dpx; font-size: %dpx; }'
                           % (ui.sc(6), ui.sc(4), ui.sc(10), ui.sc(12)))
        self.drag_pm_h = 0   # 进程内拖拽的跟随图高度（startDrag 记，拖完清零）

    def show_text(self, text):
        """徽标整体停用（2026-10 用户要求，所有场景）：系统气泡（Explorer 画的
        「→ 移动/复制」）已说明动作，落点另有引导线/高亮框，不再叠第二行文字。
        调用点与让位记账（drag_pm_h）全部保留，想恢复把 self.hide() 换成原实现。"""
        self.hide()

    def done(self):
        self.hide()


class _DesktopDropOverlay(QWidget):
    """格子拖出期间的桌面落放层：全屏透明窗，挂桌面带、压在桌面图标之上/格子与面板之下，
    接住落到桌面的拖放并内部处理（mgr.overlay_drop），不走 Explorer——
    空白格子的文件本来就在桌面，落回桌面 = 划账 + 图标放出来，文件不挪窝，
    被占用（别的进程 cwd/句柄在里头）也拖得动（DeskGo 同款）；映射格子文件由
    _shell_op 搬进/复制进目标，进度与撞名都是外壳原生弹窗。默认「移动」，Ctrl = 复制。

    平时隐藏，只在格子 startDrag 期间 show，所以不影响桌面自身的拖放与点击；
    落到资源管理器窗口/其他应用时它们压在落放层之上，照常由对方接。
    已知取舍：桌面上的文件夹快捷方式不解析目标，落到它上面按落桌面根处理。
    挂带失败（pin_ok=False）就永不显示，落桌面退回 Explorer 处理（空白格子文件
    在桌面原路径，会弹「源文件名和目标文件名相同」——罕见兜底，记 _dbg）。
    坑：分层窗口全透明像素命中穿透，paintEvent 必须画 alpha=1 的底（见该函数）。"""

    def __init__(self, mgr):
        super(_DesktopDropOverlay, self).__init__(None, Qt.FramelessWindowHint | Qt.Tool)
        self.mgr = mgr
        self.setAttribute(Qt.WA_TranslucentBackground)   # 视觉全透明（无文字，ClearType 不适用）
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.winId()   # 强制建原生句柄再挂带
        self.pin_ok = ui.pin_to_desktop(self)
        if not self.pin_ok:
            ui._dbg('box: failed to pin drop overlay; desktop drops fall back to Explorer')

    def begin(self):
        """拖出开始时显示。每次重摆几何（桌面图标区大小），并把格子/面板抬回自己之上
        ——带内兄弟序谁后动谁在上，面板沉底守卫等会改序，显示时统一抬一次。
        顺带快照桌面图标的落点区域（命中判定与徽标文案用，见 _folder_zone）。"""
        lv = find_desktop_listview()
        if lv:
            rc = wintypes.RECT()
            ui._u32.GetWindowRect(lv, ctypes.byref(rc))
            self.setGeometry(rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)
        self._icon_zones = []
        self._snapshot_icon_zones()
        self.show()
        above = [self.mgr.panel, getattr(self.mgr.panel, 'titlebar', None)] + self.mgr.windows
        for w in above:
            if w is None:
                continue
            try:
                ui._u32.SetWindowPos(int(w.winId()), ui._HWND_TOP, 0, 0, 0, 0, ui._SWP_Z_ONLY)
            except Exception:
                pass

    def end(self):
        self._icon_zones = []
        self.hide()

    def _snapshot_icon_zones(self):
        """[(屏幕矩形, 文件夹路径或 None, 显示名)]：桌面图标落点区域快照。
        命中文件夹图标 = 落进它（overlay_drop 的目标）；命中文件图标/空白 = 桌面根。"""
        lay = _DesktopIconLayout()
        if not lay.ok:
            return
        try:
            desk = os.path.normpath(desktop_dir())
            # 2026-10 性能审计 P2-14：原先在**每个图标的循环里**调 os.listdir(desk)
            # —— 系统开「隐藏扩展名」时显示名缺后缀，必然找不到 → 每个图标都触发
            # 一次全量 listdir：O(图标数 × 桌面文件数) 的磁盘风暴（200 图标就是
            # 4 万次 exists + 200 次 listdir），拖拽起始直接卡住。改成先扫一次
            # 建「主名 → 全名」映射。
            stem_map = {}
            try:
                for f in os.listdir(desk):
                    stem_map.setdefault(os.path.splitext(f)[0], f)
            except OSError:
                pass
            for _i, name, x, y in lay.enum_icons():
                pt = wintypes.POINT(x, y)
                ui._u32.ClientToScreen(lay.lv, ctypes.byref(pt))
                p = os.path.join(desk, name)
                if not os.path.exists(p):   # 系统「隐藏扩展名」时显示名缺扩展名
                    full = stem_map.get(name)
                    if full:
                        p = os.path.join(desk, full)
                self._icon_zones.append((QRect(pt.x, pt.y, lay.cx, lay.cy),
                                         p if os.path.isdir(p) else None, name))
        finally:
            lay.close()

    def _folder_zone(self, gpos):
        """落点命中的桌面图标是文件夹 → 返回它的路径；否则 None（落桌面根）。"""
        for rect, p, _name in self._icon_zones:
            if p and rect.contains(gpos):
                return p
        return None

    def paintEvent(self, e):
        # Win8+ 分层窗口按 alpha 做命中测试：全透明像素是「穿透」的——什么都不画的话
        # WindowFromPoint 会直接落到下面的桌面 ListView，落放永远到不了这里（实测）。
        # 画一层 alpha=1（视觉不可见）让整面都能接住拖拽。
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))

    @staticmethod
    def _action(e):
        return Qt.CopyAction if e.modifiers() & Qt.ControlModifier else Qt.MoveAction

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(_BOX_DRAG_MIME):
            e.setDropAction(self._action(e))
            e.accept()
            self.mgr._note_drag_enter_own()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        self.dragEnterEvent(e)   # 悬停与进入同一套判定
        if e.mimeData().hasFormat(_BOX_DRAG_MIME):
            folder = self._folder_zone(self.mapToGlobal(e.position().toPoint()))
            name = os.path.basename(folder) if folder else t('boxes.desktop')
            self.mgr.badge.show_text(_drop_text(e, name))

    def dragLeaveEvent(self, e):
        self.mgr.badge.done()
        self.mgr._note_drag_leave_own()
        super(_DesktopDropOverlay, self).dragLeaveEvent(e)

    def dropEvent(self, e):
        md = e.mimeData()
        if not md.hasFormat(_BOX_DRAG_MIME):
            e.ignore()
            return
        box = self.mgr.box_by_id(bytes(md.data(_BOX_DRAG_MIME).data()).decode('utf-8'))
        paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        if box is None or not paths:
            e.ignore()
            return
        self.mgr._note_drag_enter_own()
        act = self._action(e)
        gpos = self.mapToGlobal(e.position().toPoint())
        self.mgr.overlay_drop(box, paths, act == Qt.CopyAction, gpos,
                              self._folder_zone(gpos))
        e.setDropAction(act)
        e.accept()
        self.mgr.badge.done()


class BoxManager(object):
    """格子总管：恢复/新建/解散/显隐，维护双击桌面钩子。"""

    def __init__(self, data_dir, panel):
        self.store = BoxStore(os.path.join(data_dir, 'boxes.json'))
        self.box_root = os.path.join(data_dir, 'Boxes')
        self.panel = panel
        self.windows = []
        self.menu_icon = None   # 右键菜单图标路径，main.pyw 注入（frozen 用 exe 自带图标，不用传）
        self._own_hwnd_cache = frozenset()
        self.hook = DesktopClickHook(self.own_hwnds)
        self.hook.double_clicked.connect(self.toggle_all)
        self.hook.single_clicked.connect(self._clear_selections)
        self.rhook = DesktopRightClickHook(self.own_hwnds)
        self.rhook.right_clicked.connect(self._popup_show_icons_menu)
        self.rhook.outside_clicked.connect(self._menu_outside_clicked)
        self._menu = None          # 全隐藏态弹出的单项菜单（开着时非 None）
        self._reopen_menu = False  # 桌面右键换位置：关掉当前菜单后在光标处重弹
        # 桌面落放层：先于格子挂带，落在桌面带最底层（格子/面板在它之上，见类 docstring）
        self.overlay = _DesktopDropOverlay(self)
        self.badge = _DragBadge()   # 拖拽落点提示徽标（跟随光标，见类 docstring）
        self._drag_src = None       # 进程内拖拽的源格子（仅空白格子；延迟放图标用）
        self._drag_paths = []       # 拖拽中的条目路径
        self._unhide_timer = None   # 「拖离我们所有窗口」150ms 判定定时器
        if panel.cfg.data.get('box_dblclick', True):
            self.hook.start()
        self.restore()
        self._refresh_own_hwnds()
        self.panel.card_rects_provider = self.snap_card_rects
        # 运行期间定时记桌面图标位置（没进格子的文件），崩溃重启后也能摆回
        self._icon_pos_timer = QTimer(self.panel)
        self._icon_pos_timer.setInterval(60 * 1000)
        self._icon_pos_timer.timeout.connect(self._save_desktop_icons)
        self._icon_pos_timer.start()
        _get_daemon().ensure()   # 面板启动就拉起菜单宿主并预热壳扩展，首个右键不等
        # 壳图标后台提取的回调（图标取回后回填到各格子的列表）
        _icon_worker().set_callback(self._on_icon_ready)

    def _on_icon_ready(self, path, is_dir, size, dpr, img):
        """后台图标取回（已在主线程）：烘成 QIcon → 进缓存 + 回填到等待中的行。

        img 是后台线程用纯 ctypes（DrawIconEx）画的 QImage —— QImage 可跨线程读，
        QPixmap 只能在 GUI 线程建，故 QImage → QPixmap 这一步留在这里。
        img 为 None = 后台取不到（ExtractIconExW 对某些文件返回 0）→ 回落主线程
        的 Qt 路线同步取一次，保证图标最终能显示（慢，但少见）。
        """
        try:
            if img is None or img.isNull():
                self._icon_fallback_sync(path, is_dir, size)
                return
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr)
            icon = QIcon(pm)
            key = (path, is_dir, size, dpr)
            _icon_pending.discard(key)
            _icon_cache_put(key, icon)
            for win in self.windows:
                win.list.apply_icon(path, icon, size)
                # 标题栏的文件夹图标与列表条目同源，回填时一并更新
                if is_dir and win.rec.get('kind') == 'folder' and win.rec.get('path') == path:
                    win.icon.setPixmap(pm)
        except Exception:
            pass

    def _icon_fallback_sync(self, path, is_dir, size):
        """后台取不到图标时的回落：主线程用 Qt 路线同步取一次。"""
        for win in self.windows:
            if path not in win.list._icon_items:
                continue
            dpr = win.devicePixelRatioF()
            key = (path, is_dir, size, dpr)
            _icon_pending.discard(key)
            try:
                qicon = win._icon_for(path, is_dir)
                pm = qicon.pixmap(QSize(size, size), dpr)
                icon = QIcon(pm) if not pm.isNull() else qicon
                _icon_cache_put(key, icon)
                win.list.apply_icon(path, icon, size)
            except Exception:
                pass
            return

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
        self._restore_desktop_icons()
        # 开机自启时 Explorer 的图标可能还在陆续加载，晚一拍再补一次
        QTimer.singleShot(3000, self._restore_desktop_icons)

    # ---------- 桌面图标位置记忆（没进格子的文件） ----------
    def _save_desktop_icons(self):
        """可见桌面图标的位置快照 -> boxes.json['desktop_icons']。格子里的文件已被隐藏、
        ListView 枚举不到，所以可见图标正好是「没进格子的文件」。
        退出时 + 每 60s 定时各记一次（崩溃也丢不了多少）；自动排列 / 找不到桌面层时
        不动旧快照。"""
        lay = _DesktopIconLayout()
        try:
            snap = lay.snapshot() if lay.ok else None
        finally:
            lay.close()
        if snap is None:
            return
        self.store.data['desktop_icons'] = {k: [v[0], v[1]] for k, v in snap.items()}
        self.store.save()

    def _restore_desktop_icons(self):
        """启动时把没进格子的图标摆回上次记住的位置。"""
        saved = self.store.data.get('desktop_icons') or {}
        if not saved:
            return
        lay = _DesktopIconLayout()
        try:
            lay.restore_positions(saved)
        finally:
            lay.close()

    def _note_drag_enter_own(self):
        """拖进我们的格子/落放层：取消延迟放图标（落放层落点会自己放）。"""
        timer = self._unhide_timer
        if timer is not None:
            timer.stop()
            self._unhide_timer = None

    def _note_drag_leave_own(self):
        """拖离我们的格子/落放层：150ms 内没进我们别的窗口 = 拖到外部窗口上方——
        外部落放是对方真搬文件，隐藏属性会跟着走（落到别的文件夹里也是隐藏的，
        用户会以为文件丢了），这时候才把图标放出来。离开时的落点位置不可知，
        图标会被 Explorer 摆到第一列空位——所以一放出来就可能错位？不：拖到外部
        窗口时文件随即被搬走，图标只闪现一瞬；取消/拖回则由 startDrag 收尾藏回。"""
        if self._drag_src is None or self._unhide_timer is not None:
            return
        timer = QTimer(self.panel)
        timer.setSingleShot(True)
        timer.setInterval(150)
        timer.timeout.connect(self._unhide_dragged_now)
        self._unhide_timer = timer
        timer.start()

    def _cancel_unhide(self):
        self._note_drag_enter_own()

    def _unhide_dragged_now(self):
        self._unhide_timer = None
        box = self._drag_src
        if box is None:
            return
        for p in self._drag_paths:
            box._show_icon(p)
        _shell_refresh(desktop_dir())
        ui._dbg('box: dropped on external window; revealing icons early')

    def box_by_id(self, bid):
        for w in self.windows:
            if w.rec.get('id') == bid:
                return w
        return None

    def snap_card_rects(self, exclude=None):
        """当前可见、可参与吸附的格子与悬浮面板几何。"""
        rects = [w.geometry() for w in self.windows
                 if w is not exclude and w.isVisible()]
        if self.panel is not exclude and self.panel.isVisible():
            rects.append(self.panel.geometry())
        return rects

    # ---------- 桌面落放层（格子拖出落到桌面，内部处理不走 Explorer） ----------
    def overlay_drop(self, box, paths, copy, gpos, folder=None):
        """落放层接住 = 落到桌面（folder = 落点命中的桌面文件夹图标 → 落进它，
        由落放层 begin() 时的图标区快照判定）。
        空白格子落回桌面根：文件本来就在桌面、图标还藏着——**落点这一刻才放出来**
        （提前放会被 Explorer 摆到第一列空位，桌面满了还挤开别人不弹回）；放之前
        快照其他图标位置，放完摆到落点、被挤的按快照摆回（_place_icons_at）。
        落进文件夹图标/复制 = 真搬/复制（副本要摘掉跟着拷过来的隐藏位）。
        映射格子：_shell_op 搬进/复制进目标（外壳原生进度与撞名弹窗）。
        搬走的由 box.refresh() 按「路径消失」自愈清账（含托管账本）。"""
        desk = os.path.normpath(desktop_dir())
        target = folder or desk
        stay, op_paths = [], []
        for p in paths:
            p = os.path.normpath(p)
            if os.path.isdir(p) and (target == p or target.startswith(p + os.sep)):
                continue   # 拖到自己/自己肚子里
            if not copy and os.path.normcase(os.path.dirname(p)) == os.path.normcase(target):
                stay.append(p)   # 已在目标目录（空白格子落回桌面根）：不用搬
            else:
                op_paths.append(p)
        on_desk = os.path.normcase(target) == os.path.normcase(desk)
        # 落桌面根：先快照其他图标位置（放图标/新文件落地都会让 Explorer 重排）
        lay = _DesktopIconLayout() if on_desk and (stay or op_paths) else None
        before = lay.snapshot() if lay is not None and lay.ok else None
        if op_paths:
            if box.rec['kind'] == 'blank' and copy:
                # 空白格子的复制自己干：壳复制的新名字不可知（「- 副本」后缀是本地化的），
                # 自己定名才能把图标摆到落点
                for p in op_paths:
                    try:
                        dst = os.path.join(target, _unique_name(target, os.path.basename(p)))
                        if os.path.isdir(p):
                            shutil.copytree(p, dst)
                        else:
                            shutil.copy2(p, dst)
                        _strip_hidden(dst)   # 副本不能带隐藏位（copystat 会把属性拷过去）
                    except OSError as e:
                        ui._dbg('box: copy to desktop failed %s: %s' % (p, e))
            else:
                _shell_op(0x2 if copy else 0x1, op_paths, target, hwnd=int(box.winId()))
        if box.rec['kind'] == 'blank' and not copy and stay:
            items = box.rec.get('items') or []
            for p in stay:
                if p in items:
                    items.remove(p)
                box._show_icon(p)   # 落点这一刻才放出桌面图标（见 docstring）
            self.save_rec(box)
        box.refresh()
        _shell_refresh(desk)
        if lay is not None:
            try:
                self._place_icons_at([os.path.basename(p) for p in stay + op_paths],
                                     gpos, lay, before)
            finally:
                lay.close()

    def _place_icons_at(self, names, gpos, lay, before):
        """落放后：新出现/放出的图标摆到落点，被挤开的其他图标按 before 快照摆回。
        尽力而为：自动排列桌面（lay.ok=False）/ 等不到图标（撞名被改了名）都放弃。"""
        if not names or not lay.ok:
            return
        pt = wintypes.POINT(gpos.x(), gpos.y())
        ui._u32.ScreenToClient(lay.lv, ctypes.byref(pt))
        want = {n.lower() for n in names}
        want |= {os.path.splitext(n)[0] for n in want}   # 隐藏扩展名的显示名
        deadline = time.time() + 1.5
        found = []
        delay = 0.05
        while time.time() < deadline:
            found = [(i, n) for i, n, _x, _y in lay.enum_icons() if n.lower() in want]
            if len(found) >= len(names):
                break
            # 2026-10 性能审计 P1-7：同 fixup —— 用 processEvents 代替纯 sleep，
            # GUI 线程不再整段睡死（排除用户输入事件防重入）；间隔指数退避。
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
            time.sleep(delay)
            delay = min(delay * 1.6, 0.2)
        for k, (i, _n) in enumerate(found):
            lay._set_pos(i, pt.x + lay.cx * k, pt.y)   # 多个图标从落点起横向排开
        if before:
            for i, n, x, y in lay.enum_icons():   # 重枚举：摆上我们的图标后可能又挤了人
                key = n.lower()
                if key not in want and key in before and (x, y) != before[key]:
                    lay._set_pos(i, before[key][0], before[key][1])   # 被挤的摆回

    def _upgrade_blank_boxes(self):
        """启动时把空白格子的文件弄回桌面，两种情况：

        ① 旧版把文件真搬进了 %APPDATA%\\zbox\\Boxes\\<id>\\（用户实测关程序后这些
           文件「被吞在里面」）—— 搬回桌面并转成 items，rec['path'] 随之作废；
        ② 旧版拖拽暂存的残留：新版落到桌面由落放层内部处理、不再暂存
           （见 `_DesktopDropOverlay`），但旧版在桌面下隐藏夹 `.zbox` 留下过残留 ——
           一并搬回桌面并补进记账，否则文件就留在隐藏夹里看不见了。"""
        desk = os.path.normpath(desktop_dir())
        stage = os.path.join(desk, _STAGE_NAME)
        for rec in self.store.data['boxes']:
            if rec.get('kind') != 'blank':
                continue
            moved = rec.get('moved') or {}
            # 托管账本先 prune：存放文件已没（停机期间被删）的划掉；
            # 还在的属于正常托管，不是残留，不扫回桌面
            moved = {p: s for p, s in moved.items() if os.path.exists(s)}
            rec['moved'] = moved
            items = [p for p in (rec.get('items') or [])
                     if os.path.exists(p) or p in moved]
            legacy = rec.get('path') or ''
            own = os.path.join(self.box_root, rec['id'])
            dirs = [own, stage]
            if os.path.isdir(legacy) and legacy not in dirs:
                dirs.append(legacy)
            for d in dirs:
                items = _recover_files(d, desk, items,
                                       keep=set(moved.values()) if d == own else ())
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
        name = t('menu.new_box') if n == 0 else t('boxes.new_blank_n', n=n + 1)
        rec = self._new_rec('blank', name, None)
        rec['items'] = []
        rec['attrs'] = {}
        self.store.save()
        self._spawn(rec)

    def ungroup_paths(self, paths, except_win):
        """把 paths 从别的空白格子里摘掉（一个文件只属于一个格子）。
        隐藏属性账本 rec['attrs'] 的键跟着走：格子间直接拖拽时文件一直是藏着的
        （拖出不再先摘隐藏位），账本不搬走的话，解散格子/退出程序时图标还原不回来。"""
        if not paths:
            return
        for w in self.windows:
            if w is except_win or w.rec.get('kind') != 'blank':
                continue
            items = w.rec.get('items') or []
            rest = [p for p in items if p not in paths]
            if rest != items:
                w.rec['items'] = rest
                attrs = w.rec.get('attrs') or {}
                moved = w.rec.get('moved') or {}
                for p in paths:
                    moved.pop(p, None)
                    if p in attrs:
                        except_win.rec.setdefault('attrs', {})[p] = attrs.pop(p)
                w.refresh()
        self.store.save()

    def new_folder(self, path=None):
        """新建文件夹映射格子；path 为空时弹目录选择框（原生资源管理器样式）。
        同一路径已有格子时不新建：显示出来并闪烁提示（文件夹右键「添加到Zbox桌面格子」
        与「新建文件夹格子」对话框都走这里）。"""
        if not path:
            # 静态方法原生框：模态只锁属主窗口，设置窗等其它顶层窗口照常可用。
            # 两个坑：① 必须用静态方法——QFileDialog 实例 + exec_() 在这套环境会开出
            # 隐形对话框；② GUI 线程必须是 STA（main() 入口已初始化），否则原生壳对话框
            # 在 Qt 默认的 MTA 下抛 RPC_E_WRONG_THREAD（0x8001010e）致命错误
            path = QFileDialog.getExistingDirectory(self.panel, t('boxes.pick_folder'))
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

    def _clear_selections(self):
        """单击桌面空白处（DesktopClickHook.single_clicked）：清掉所有格子的文件选中。
        格子挂在桌面带、点桌面不会触发它的失焦清选中，只能自己清。"""
        for win in self.windows:
            if win.list.selectedItems():
                win.list.clearSelection()

    def set_dblclick_enabled(self, on):
        """设置窗开关：启停「双击桌面显隐格子」的低级鼠标钩子。
        QThread 停止后可再次 start；stop() 会等线程退出，
        重启能起作用靠 run() 开头清 _stop（见那里注释）。"""
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

    # 显示三连的实测绘制延迟（2026-10 本机实测，ShowWindow/setVisible 调用到画出来）：
    # 面板 ~165ms、格子 ~255ms、桌面图标 ~480ms（Explorer 画图标最慢且不受我们控制）。
    # 按延迟倒序错峰翻牌，三者凑到同一帧出现；数值是经验值，别的机器略有出入无妨。
    _SHOW_DELAY_BOXES = 230
    _SHOW_DELAY_PANEL = 320

    def _show_everything(self, lv):
        """显示三连凑同一帧：先做掉所有慢操作（空白格子收文件图标要逐文件改属性 +
        SHChangeNotify 同步等壳刷新、写盘），然后按绘制延迟倒序错峰翻牌——
        桌面图标（最慢）→ 格子 → 面板（最快），三者同时画完。
        （旧顺序三连紧挨着翻，但三方绘制耗时长短不一，用户看到的是格子→面板→图标三批。）"""
        self.store.data['visible'] = True
        self.store.save()
        for w in self.windows:
            if w.rec['kind'] == 'blank':
                w.hide_icons()   # 慢操作全部前置（_hide_icon 对已隐藏的早退，重复调用安全）
        if lv:
            ui._u32.ShowWindow(lv, 5)   # SW_SHOW：最慢的先开始画
        QTimer.singleShot(self._SHOW_DELAY_BOXES, self._show_boxes)
        QTimer.singleShot(self._SHOW_DELAY_PANEL, self._show_panel)

    def _show_boxes(self):
        if not self.store.data.get('visible', True):
            return   # 错峰等待期间用户又双击收起来了，别再放出来
        for w in self.windows:
            w.setVisible(True)

    def _show_panel(self):
        if not self.store.data.get('visible', True):
            return   # 同上
        self.panel.show()   # 与 panel.toggle_visible 的显示分支一致
        self.panel.raise_()
        self.panel.activateWindow()

    def toggle_all(self):
        """双击桌面空白处：桌面图标 + 全部格子 + 面板一起显隐。
        任一还可见就算「显示中」，全部收起来；全收了再一起放出来。
        图标显隐 = ShowWindow 桌面 SysListView32（与右键菜单的勾选状态无关）。"""
        lv = find_desktop_listview()
        showing = (self.panel.isVisible()
                   or any(w.isVisible() for w in self.windows)
                   or bool(lv and ui._u32.IsWindowVisible(lv)))
        show = not showing
        if show:
            self._show_everything(lv)   # 慢操作前置 + 三连翻牌，三者同帧出现
        else:
            self.set_boxes_visible(False)
            self.panel.close_panel()   # 顶部栏是独立小窗，必须跟着收
            if lv:
                ui._u32.ShowWindow(lv, 0)   # SW_HIDE
        # 全隐藏态桌面右键收成唯一直链项「显示桌面图标」，恢复后切回级联六项
        sysutil.context_menu_set_icons_hidden(not show, icon_path=self.menu_icon)
        # 全隐藏态再挂上右键拦截钩（吞掉系统菜单弹自己的单项菜单）；恢复显示立即卸载，
        # 钩子只活在这一小段时间——平时对系统鼠标零开销
        if show:
            self.rhook.stop()
        elif not self.rhook.isRunning():
            self.rhook.start()

    def show_all(self):
        """桌面右键「显示桌面图标」（仅全隐藏态注入的单项）：图标 + 格子 + 面板一起
        放出，菜单切回级联。不在全隐藏态（崩溃残留的单项菜单被点到）只拨回菜单形态。"""
        self.rhook.stop()   # 两个分支的结果都是「不在全隐藏态」，拦截钩一并卸掉
        lv = find_desktop_listview()
        if (self.panel.isVisible() or any(w.isVisible() for w in self.windows)
                or bool(lv and ui._u32.IsWindowVisible(lv))):
            sysutil.context_menu_set_icons_hidden(False, icon_path=self.menu_icon)
            return
        self._show_everything(lv)   # 与 toggle_all 的显示分支同一条路：三者同帧出现
        sysutil.context_menu_set_icons_hidden(False, icon_path=self.menu_icon)

    def _popup_show_icons_menu(self):
        """全隐藏态桌面右键（系统菜单已被 DesktopRightClickHook 吞掉）：弹自己的单项菜单。
        「点外面关闭 / 右键换位置重弹」不靠 Qt 的弹窗抓取（抓不住，见钩子 proc 注释），
        由钩子的 outside_clicked 信号驱动（_menu_outside_clicked）。"""
        if self._menu is not None or not self.rhook.isRunning():
            return   # 已开着（连点右键排队的重复信号），或已不在全隐藏态（重弹定时器晚到）
        self.rhook.menu_open = True
        m = QMenu(self.panel)
        self._menu = m
        m.addAction(sysutil.show_icons_text(), self.show_all)
        m.exec(QCursor.pos())
        self._menu = None
        self.rhook.menu_open = False
        if self._reopen_menu:   # 桌面右键换了位置：exec_ 已返回、状态归位后在光标处重弹
            self._reopen_menu = False
            QTimer.singleShot(0, self._popup_show_icons_menu)

    def _menu_outside_clicked(self, reopen):
        """菜单开着时点了菜单以外（钩子信号）：左键/点别的应用 = 只关掉；
        桌面右键 = 关掉并在新位置重弹（重弹标志在 _popup_show_icons_menu 里消费）。"""
        if self._menu is None:
            return
        if reopen:
            self._reopen_menu = True
        self._menu.close()

    def shutdown(self):
        self.hook.stop()
        self.rhook.stop()   # 退出时若仍在全隐藏态（--quit / stop.cmd），拦截钩必须卸掉
        self._icon_pos_timer.stop()
        self._save_desktop_icons()   # 先记位置再释放：格子图标还藏着，快照只含没进格子的文件
        # 关程序：空白格子里的文件全部「还原」到桌面（文件本来就在桌面，只是被隐藏了
        # 图标）——不还原的话用户关掉程序后桌面上找不到它们。分组记录留着，下次启动
        # 再收进格子（用户实测：关程序后文件被吞在 AppData 里，就是这个没做）。
        for w in self.windows:
            if w.rec.get('kind') == 'blank':
                w.show_icons()
        self.store.save()
