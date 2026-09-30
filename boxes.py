# -*- coding: utf-8 -*-
"""桌面格子：仿腾讯桌面整理的桌面格子功能。

- 空白格子：背后对应 %APPDATA%\\ZviberPanel\\Boxes\\<id>\\ 真实文件夹，
  拖入 = 把文件移动进去；解散 = 把文件全部还原回桌面（不删文件）。
- 文件夹映射格子：实时映射任意磁盘文件夹，QFileSystemWatcher 监听内容变化自动刷新；
  路径失效时显示提示 + 「解散格子」按钮（对齐腾讯桌面整理的表现）。
- 窗口：无边框 Tool 窗，半透明磨砂；属主挂到桌面图标窗（免疫 Win+D），
  z-order 沉在应用窗口之下、桌面表层之上——复用 app.py 的 pin_to_desktop / sink_to_desktop。
- 双击桌面空白处显隐全部格子：WH_MOUSE_LL 低级钩子自判双击，命中桌面家族窗口才算数。
  （双击桌面图标上也会触发，与腾讯桌面整理行为一致。）
- 视觉固定深色磨砂：格子贴在壁纸上，跟随面板明暗主题都不合适，故不挂主题系统。
  注意 WA_TranslucentBackground 会禁用 ClearType（app.py 面板因此不用它），
  格子文字少且参考软件本身就是半透明的，这里接受这个取舍。
"""
import ctypes
import json
import os
import shutil
import subprocess
import time
from ctypes import wintypes

from PyQt5.QtCore import (Qt, QTimer, QThread, QUrl, QPoint, QRect, QSize, QEvent,
                          QFileSystemWatcher, pyqtSignal)
from PyQt5.QtGui import QIcon, QCursor, QPainter, QColor, QPen, QFont
from PyQt5.QtWidgets import (QWidget, QListWidget, QListWidgetItem, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QLabel, QToolButton,
                             QPushButton, QStackedLayout, QMenu, QActionGroup,
                             QInputDialog, QMessageBox, QFileDialog,
                             QAbstractItemView, QApplication, QStyle)

import app as ui   # sc / pin_to_desktop / sink_to_desktop / _PROG_FAMILY / _class_name

# 64 位安全的 ctypes 签名（windll 默认按 32 位 int 截断，句柄/指针高位会丢）
_h32 = ctypes.windll.user32
_h32.SetWindowsHookExW.restype = ctypes.c_void_p
_h32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
_h32.UnhookWindowsHookEx.restype = wintypes.BOOL
_h32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_h32.CallNextHookEx.restype = ctypes.c_longlong
_h32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p]
_h32.PostThreadMessageW.restype = wintypes.BOOL
_h32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, ctypes.c_size_t, ctypes.c_void_p]
_h32.GetMessageW.restype = ctypes.c_int
_h32.GetMessageW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT]
_h32.TranslateMessage.restype = wintypes.BOOL
_h32.TranslateMessage.argtypes = [ctypes.c_void_p]
_h32.DispatchMessageW.restype = ctypes.c_longlong
_h32.DispatchMessageW.argtypes = [ctypes.c_void_p]
_h32.ShowWindow.restype = wintypes.BOOL
_h32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]

SORT_CHOICES = [('name', '按名称'), ('type', '按类型'), ('mtime', '按修改时间')]

TITLE_H = 30        # 标题栏高（设计像素，运行时过 sc()）
EDGE = 6            # 边缘缩放命中宽度
MIN_W, MIN_H = 200, 120
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


def _unique_name(dest_dir, name):
    """目标目录里的不重名文件名：冲突时 '名 (2).ext' 递增。"""
    if not os.path.exists(os.path.join(dest_dir, name)):
        return name
    base, ext = os.path.splitext(name)
    n = 2
    while os.path.exists(os.path.join(dest_dir, '%s (%d)%s' % (base, n, ext))):
        n += 1
    return '%s (%d)%s' % (base, n, ext)


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
    记录字段：id / name / kind('blank'|'folder') / path / x,y,w,h / collapsed / locked / sort。
    blank 的 path 是背地里的存储文件夹；folder 的 path 是被映射的磁盘文件夹。"""

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

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and e.source() is not self:
            e.acceptProposedAction()
        else:
            super(BoxList, self).dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls() and e.source() is not self:
            e.acceptProposedAction()
        else:
            super(BoxList, self).dragMoveEvent(e)

    def dropEvent(self, e):
        if e.source() is self:
            e.ignore()   # 列表按排序填充，不支持内部拖放换位
            return
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.box.import_paths(paths)
            e.acceptProposedAction()

    def mimeData(self, items):
        """拖出时附带文件 URL：落到桌面/资源管理器/别的格子都是一次真实移动。"""
        md = super(BoxList, self).mimeData(items)
        md.setUrls([QUrl.fromLocalFile(it.data(Qt.UserRole)) for it in items])
        return md

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete:
            self.box.delete_items(self.selectedItems())
        else:
            super(BoxList, self).keyPressEvent(e)

    def contextMenuEvent(self, e):
        it = self.itemAt(e.pos())
        menu = QMenu(self)
        if it:
            path = it.data(Qt.UserRole)
            menu.addAction('打开', lambda: self.box.open_path(path))
            menu.addAction('在资源管理器中显示', lambda: self.box.reveal_path(path))
            menu.addSeparator()
            menu.addAction('删除', lambda: self.box.delete_items(self.selectedItems()))
        else:
            menu.addAction('刷新', self.box.refresh)
            menu.addAction('在资源管理器中打开', lambda: self.box.open_path(self.box.rec['path']))
        if menu.actions():
            menu.exec_(e.globalPos())


class BoxWindow(QWidget):
    """单个桌面格子窗口。"""

    def __init__(self, mgr, rec):
        super(BoxWindow, self).__init__(None, Qt.FramelessWindowHint | Qt.Tool)
        self.mgr = mgr
        self.rec = rec
        self._desk_pinned = False
        self._desk_surface = None   # 探测到的第三方桌面表层（沉底锚点缓存）
        self._floating = False      # True = 被点击激活浮起到应用窗口之上，失焦后需要沉回
        self._op = None          # ('move', 起点全局坐标, 起始几何) 或 ('resize', 边缘掩码, ...)
        self._press_pos = None   # 拖拽起点（全局坐标），用于区分点击与拖动
        self._last_drag_ts = 0.0   # 最近一次发生位移的拖拽结束时间（抑制拖拽连带的双击收起）
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setMinimumSize(ui.sc(MIN_W), ui.sc(TITLE_H) + ui.sc(60))
        self.setStyleSheet(_box_qss())
        self.setFont(QFont(ui.pick_fonts()[0]))

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        # 标题栏：文件夹图标 + 名称 + 收起/锁定/菜单
        self.title = QWidget()
        self.title.setFixedHeight(ui.sc(TITLE_H))
        tb = QHBoxLayout(self.title)
        tb.setContentsMargins(ui.sc(10), 0, ui.sc(6), 0)
        tb.setSpacing(ui.sc(4))
        self.icon = QLabel()
        self.icon.setFixedSize(ui.sc(16), ui.sc(16))
        self.icon.setScaledContents(True)
        tb.addWidget(self.icon)
        self.name = QLabel(rec['name'])
        self.name.setObjectName('boxName')
        tb.addWidget(self.name, 1)
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
        page_list = QWidget()
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
        root.addLayout(self.pages, 1)

        # 子控件默认继承顶层窗口的光标：边缘悬停设了双箭头后划入列表不会复位。
        # 给会盖住窗口背景的子控件装过滤器，MouseMove 时按窗口坐标同步光标。
        for w in (self.title, self.list, self.list.viewport(), self.hint):
            w.installEventFilter(self)

        # 文件夹内容变化自动刷新（300ms 去抖）
        self.watcher = QFileSystemWatcher(self)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self.refresh)
        self.watcher.directoryChanged.connect(lambda _p: self._debounce.start())

        # 桌面层级：归属桌面带 + 看门狗沉底 + WinEvent 钩子（与面板同一套）：
        # 桌面整理软件（TXMiniSkin）每 ~2.5s 重建表层，靠钩子毫秒级抬回，等看门狗会闪半秒
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

    def refresh(self):
        """重新扫描目录填充列表；映射文件夹失效时切到失效页。"""
        path = self.rec['path']
        if self.rec['kind'] == 'folder' and not os.path.isdir(path):
            self.pages.setCurrentIndex(1)
            self._rewatch()
            return
        self.pages.setCurrentIndex(0)
        self._rewatch()
        entries = []
        try:
            for it in os.scandir(path):
                try:
                    st = it.stat()
                except OSError:
                    continue
                if getattr(st, 'st_file_attributes', 0) & 0x2:
                    continue   # 隐藏文件不显示
                entries.append((it.name, it.path, it.is_dir(), st))
        except OSError:
            pass
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
            item = QListWidgetItem(self._icon_for(p, is_dir), name)
            item.setData(Qt.UserRole, p)
            item.setToolTip(p)
            self.list.addItem(item)
        self.hint.setVisible(not entries and self.rec['kind'] == 'blank')
        # 标题图标：映射格子用目标文件夹图标，空白格子用文件夹图标
        pm = self._icon_for(path, True).pixmap(ui.sc(16), ui.sc(16))
        self.icon.setPixmap(pm)

    def _rewatch(self):
        old = self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        if os.path.isdir(self.rec['path']):
            self.watcher.addPath(self.rec['path'])

    # ---------- 文件操作 ----------
    def import_paths(self, paths):
        """拖入文件：真实移动到格子目录（跨格子拖动也是移动）。跳过已在目录内/父目录拖进自己。"""
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

    def open_path(self, path):
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

    def rename(self):
        name, ok = QInputDialog.getText(self, '重命名格子', '格子名称：',
                                        text=self.rec['name'])
        name = name.strip()
        if ok and name and name != self.rec['name']:
            self.rec['name'] = name
            self.name.setText(name)
            self.mgr.save_rec(self)

    def dissolve(self):
        """解散格子：空白格子把文件还原回桌面后删掉背后的存储目录；映射格子直接移除。"""
        if self.rec['kind'] == 'blank' and os.path.isdir(self.rec['path']):
            desk = desktop_dir()
            try:
                for name in os.listdir(self.rec['path']):
                    src = os.path.join(self.rec['path'], name)
                    try:
                        shutil.move(src, os.path.join(desk, _unique_name(desk, name)))
                    except OSError:
                        pass
            except OSError:
                pass
            shutil.rmtree(self.rec['path'], ignore_errors=True)
        self.mgr.remove(self)

    def _show_menu(self):
        menu = QMenu(self)
        menu.addAction('重命名格子', self.rename)
        menu.addAction('解散格子', self.dissolve)
        menu.addSeparator()
        grp = QActionGroup(menu)
        for key, label in SORT_CHOICES:
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self.rec.get('sort', 'name') == key)
            grp.addAction(act)
            act.triggered.connect(lambda _c=False, k=key: self._set_sort(k))
        menu.exec_(QCursor.pos())

    def _set_sort(self, key):
        self.rec['sort'] = key
        self.mgr.save_rec(self)
        self.refresh()

    # ---------- 桌面层级 ----------
    def showEvent(self, e):
        super(BoxWindow, self).showEvent(e)
        self._ensure_band()
        QTimer.singleShot(300, lambda: ui.sink_to_desktop(self))

    def _ensure_band(self):
        if self._op is not None:
            return   # 拖拽期间故意脱离桌面带（见 mousePressEvent），别补挂
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
        hwnd = int(self.winId())
        if not ui._u32.IsWindow(hwnd):
            self._sink_timer.stop()
            return
        self._ensure_band()
        extra = []
        if self.isVisible():
            extra.append((self.x() + self.width() // 2, self.y() + self.height() // 2))
        self._desk_surface, _t = ui.probe_desktop(skip=(hwnd,), extra=extra)
        # 空闲时不动 z-order：空发 SetWindowPos 会触发表层反压，与桌面整理软件振荡闪烁
        if self._covered_by_surface():
            if self._op is None:
                ui.sink_to_desktop(self, self._desk_surface)   # 被表层压住：无条件抬回
        else:
            self._ensure_desktop_level()

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

    def event(self, e):
        if e.type() == QEvent.WindowActivate:
            self._floating = True    # 点击激活会浮到应用窗口之上，记下待沉
        elif e.type() == QEvent.WindowDeactivate:
            QTimer.singleShot(300, self._ensure_desktop_level)   # 失焦后压回桌面层
        return super(BoxWindow, self).event(e)

    def _ensure_desktop_level(self):
        """格子被点击激活后会浮到普通窗口之上；空闲（未激活/未悬停/未拖拽）时压回桌面层。
        没浮起过就不动——z-order 变动会触发表层反压，空发会振荡闪烁。"""
        if (not self._floating or not self.isVisible() or self.isActiveWindow()
                or self.underMouse() or self._op is not None):
            return
        self._floating = False
        ui.sink_to_desktop(self, self._desk_surface)

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
            ui.unpin_from_desktop(self)   # 拖拽期间退出桌面带：普通窗口移动不触发表层反压
            self._desk_pinned = False

    def mouseMoveEvent(self, e):
        if not self._op:
            self._sync_cursor(e.pos())
            super(BoxWindow, self).mouseMoveEvent(e)
            return
        kind, edges, start_pos, start_geo = self._op
        delta = e.globalPos() - start_pos
        if kind == 'move':
            self.move(start_geo.topLeft() + delta)
        else:
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
            op, _edges, start_pos, _geo = self._op
            self._op = None
            if self._press_pos is not None and \
                    (e.globalPos() - self._press_pos).manhattanLength() > 4:
                self._last_drag_ts = time.time()
            self._press_pos = None
            self._clamp_to_screen()   # 拖出屏幕会再也够不着标题栏，钳回来
            self.rec['x'], self.rec['y'] = self.x(), self.y()
            if not self.rec.get('collapsed'):
                self.rec['w'], self.rec['h'] = self.width(), self.height()
            self.mgr.save_rec(self)
            self._repin()   # 归位：重新归属桌面带并沉回表层之上
            ui.sink_to_desktop(self, self._desk_surface)
        super(BoxWindow, self).mouseReleaseEvent(e)

    def _clamp_to_screen(self):
        """保证至少标题栏露在屏幕内（面板同款思路，见 FloatingPanel._clamp_to_screen）。"""
        ag = QApplication.primaryScreen().availableGeometry()
        x = min(max(self.x(), ag.left() - self.width() + 80), ag.right() - 80)
        y = min(max(self.y(), ag.top()), ag.bottom() - 40)
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def mouseDoubleClickEvent(self, e):
        # 快速连续两次点标题拖拽时，第二次 press 会被系统判成双击：
        # 若前一次点击发生了位移（是在拖不是在点），或在拖拽途中，都不收起
        if self._op is not None or time.time() - self._last_drag_ts < 0.5:
            return super(BoxWindow, self).mouseDoubleClickEvent(e)
        if e.pos().y() < ui.sc(TITLE_H) and not self._hit_edges(e.pos()):
            self.set_collapsed(not self.rec['collapsed'])
        super(BoxWindow, self).mouseDoubleClickEvent(e)


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
        self._tid = []
        self._hook = []

    def run(self):
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        proc_t = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int,
                                    wintypes.WPARAM, wintypes.LPARAM)

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [('pt', wintypes.POINT), ('mouseData', wintypes.DWORD),
                        ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                        ('dwExtraInfo', ctypes.c_void_p)]

        state = {'t': 0, 'x': -9999, 'y': -9999}
        dbl_t = u32.GetDoubleClickTime()
        dbl_x = u32.GetSystemMetrics(36)   # SM_CXDOUBLECLK
        dbl_y = u32.GetSystemMetrics(37)   # SM_CYDOUBLECLK

        sw = u32.GetSystemMetrics(0)
        sh = u32.GetSystemMetrics(1)

        def _is_desktop(pt):
            h = ui._u32.WindowFromPoint(pt)
            own = self.own_hwnds()
            while h:
                if h in own:
                    return False
                cls = ui._class_name(h)
                if cls in ui._PROG_FAMILY or cls == 'SysListView32':
                    return True
                # 桌面整理软件的全屏覆盖层（腾讯 TXMiniSkin 等）：与 app.probe_desktop 同一判定
                if ui._is_desktop_surface(h, sw, sh):
                    return True
                h = ui._u32.GetParent(h)
            return False

        def proc(nCode, wParam, lParam):
            if nCode == 0 and wParam == 0x0201:   # WM_LBUTTONDOWN
                s = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                now = s.time
                if (now - state['t'] <= dbl_t and abs(s.pt.x - state['x']) <= dbl_x
                        and abs(s.pt.y - state['y']) <= dbl_y and _is_desktop(s.pt)):
                    state['t'] = 0
                    self.double_clicked.emit()
                else:
                    state['t'], state['x'], state['y'] = now, s.pt.x, s.pt.y
            return _h32.CallNextHookEx(None, nCode, wParam, lParam)

        self._proc = proc_t(proc)   # 留引用防 GC
        hook = _h32.SetWindowsHookExW(14, ctypes.cast(self._proc, ctypes.c_void_p), None, 0)   # WH_MOUSE_LL
        if not hook:
            return
        self._hook[:] = [hook]
        self._tid[:] = [k32.GetCurrentThreadId()]
        msg = wintypes.MSG()
        while _h32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _h32.TranslateMessage(ctypes.byref(msg))
            _h32.DispatchMessageW(ctypes.byref(msg))
        _h32.UnhookWindowsHookEx(hook)
        self._hook[:] = []

    def stop(self):
        if self._tid:
            _h32.PostThreadMessageW(self._tid[0], 0x0012, 0, 0)   # WM_QUIT
            self.wait(2000)


class BoxManager(object):
    """格子总管：恢复/新建/解散/显隐，维护双击桌面钩子。"""

    def __init__(self, data_dir, panel):
        self.store = BoxStore(os.path.join(data_dir, 'boxes.json'))
        self.box_root = os.path.join(data_dir, 'Boxes')
        self.panel = panel
        self.windows = []
        self.hook = DesktopClickHook(self.own_hwnds)
        self.hook.double_clicked.connect(self.toggle_visible)
        self.hook.start()
        self.restore()

    def own_hwnds(self):
        s = set()
        for w in [self.panel, getattr(self.panel, 'titlebar', None)] + self.windows:
            if w is not None:
                try:
                    s.add(int(w.winId()))
                except Exception:
                    pass
        return s

    def restore(self):
        ag = QApplication.primaryScreen().virtualGeometry()
        for rec in self.store.data['boxes']:
            win = BoxWindow(self, rec)
            x = min(max(rec.get('x', ag.left() + 60), ag.left()), ag.right() - 80)
            y = min(max(rec.get('y', ag.top() + 60), ag.top()), ag.bottom() - 60)
            win.move(x, y)
            self.windows.append(win)
            if self.store.data.get('visible', True):
                win.show()

    def _new_rec(self, kind, name, path):
        rec = {'id': 'b%d' % int(time.time() * 1000), 'kind': kind, 'name': name,
               'path': path, 'x': None, 'y': None, 'w': 0, 'h': 0,
               'collapsed': False, 'locked': False, 'sort': 'name'}
        n = len(self.windows)
        rec['x'] = 60 + (n % 5) * 40
        rec['y'] = 60 + (n % 5) * 40
        self.store.data['boxes'].append(rec)
        self.store.save()
        return rec

    def new_blank(self):
        """新建空白格子：背地里是数据目录下的真实文件夹。"""
        n = len([r for r in self.store.data['boxes'] if r['kind'] == 'blank'])
        name = '新建格子' if n == 0 else '新建格子 %d' % (n + 1)
        rec = self._new_rec('blank', name, '')
        rec['path'] = os.path.join(self.box_root, rec['id'])
        os.makedirs(rec['path'], exist_ok=True)
        self.store.save()
        self._spawn(rec)

    def new_folder(self, path=None):
        """新建文件夹映射格子；path 为空时弹目录选择框。"""
        if not path:
            path = QFileDialog.getExistingDirectory(None, '选择要映射的文件夹')
        if not path:
            return
        rec = self._new_rec('folder', os.path.basename(os.path.normpath(path)) or path,
                            os.path.normpath(path))
        self._spawn(rec)

    def _spawn(self, rec):
        win = BoxWindow(self, rec)
        win.move(rec['x'], rec['y'])
        self.windows.append(win)
        win.show()
        if not self.store.data.get('visible', True):
            win.hide()

    def save_rec(self, _win):
        self.store.save()

    def remove(self, win):
        if win in self.windows:
            self.windows.remove(win)
        self.store.data['boxes'] = [r for r in self.store.data['boxes'] if r is not win.rec]
        self.store.save()
        win._unhook_win_event()
        win.setParent(None)
        win.deleteLater()

    def toggle_visible(self):
        show = not any(w.isVisible() for w in self.windows)
        self.store.data['visible'] = show
        self.store.save()
        for w in self.windows:
            w.setVisible(show)

    def shutdown(self):
        self.hook.stop()
        self.store.save()
