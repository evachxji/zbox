# -*- coding: utf-8 -*-
"""全界面截图自检 harness：ZBOX_SHOT=<目录> 启动时由 main.pyw 调用。

目标：同一台机器上两次运行（PySide6 基线 / PySide6 迁移后）产出逐像素可比的 PNG 集。
手段：冻结时间（patch app 模块的 date/datetime）、注入固定示例数据（结束后还原）、
全部走 widget.grab() 离屏渲染（规避 DWM 圆角/屏幕合成差异）、版本号与磁盘剩余空间
等运行期变量一律打桩成固定值。

不覆盖：原生系统对话框（文件/目录选择）、Explorer 渲染的桌面右键级联菜单、
截图 overlay（screenshot.py，抓取真实屏幕，内容本身不确定）。
"""
import collections
import os
import shutil
import tempfile
import threading
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QImage, QPainter, QColor, QFont
from PySide6.QtWidgets import QApplication, QMenu

import app as ui
import boxes as bx
import installer
import pinshot
import sysutil
import transfer_ui
from themes import THEME_ORDER

# 冻结的时间点：日历页时钟、倒计时、「今天」高亮、待办日期 tag 全部由它推出
FIXED_NOW = datetime(2026, 10, 15, 10, 8, 30)
# 界面上的版本号统一打桩：发版 bump version.py 不影响前后两批截图的可比性
SHOT_VERSION = '0.0-shot'


def freeze_time():
    """把 app 模块命名空间里的 date/datetime 换成固定在 FIXED_NOW 的子类。
    app.py 全部时间源是 date.today()/datetime.now()（模块级 from-import），
    必须在 FloatingPanel 构造之前调用（日历页、_today 在 init 时就定型）。"""
    class _D(date):
        @classmethod
        def today(cls):
            return date(FIXED_NOW.year, FIXED_NOW.month, FIXED_NOW.day)

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(FIXED_NOW.year, FIXED_NOW.month, FIXED_NOW.day,
                            FIXED_NOW.hour, FIXED_NOW.minute, FIXED_NOW.second)
    ui.date = _D
    ui.datetime = _DT


def run(shot_dir, panel, cfg, tstore, qapp):
    """入口：600ms 后由 main.pyw 经 QTimer 触发。采集完成还原数据并退出进程。"""
    os.makedirs(shot_dir, exist_ok=True)
    runner = _Runner(shot_dir, panel, cfg, tstore, qapp)
    runner.start()


class _FakeBoxMgr(object):
    """BoxWindow 对 mgr 的全部依赖（截图场景不新建/解散/取消归组，全部空操作）。"""

    def save_rec(self, win):
        pass

    def remove(self, win):
        pass

    def ungroup_paths(self, paths):
        pass


class _Runner(object):
    def __init__(self, shot_dir, panel, cfg, tstore, qapp):
        self.dir = shot_dir
        self.panel = panel
        self.cfg = cfg
        self.tstore = tstore
        self.qapp = qapp
        self.jobs = []          # [(名称, settle_ms, setup_fn, target_fn)]
        self._i = 0
        self._keepalive = []    # 场景窗口引用：防 GC
        self._todo_backup = None
        self._box = None
        self._sample_dir = None
        self._ver_backup = None
        self._du_backup = None

    # ---------------- 准备 / 收尾 ----------------
    def start(self):
        # 示例待办：相对 FIXED_NOW 推出「逾期 2 天 / 今天 / 还剩 2 天」三档 tag
        self._todo_backup = list(self.tstore.items)
        t0 = FIXED_NOW.date()
        self.tstore.items = [
            {'id': 1, 'text': '整理 Q3 复盘文档', 'done': False,
             'due': (t0 - timedelta(days=2)).isoformat()},
            {'id': 2, 'text': '给妈妈回电话', 'done': False, 'due': t0.isoformat()},
            {'id': 3, 'text': '国庆出游订酒店', 'done': False,
             'due': (t0 + timedelta(days=2)).isoformat()},
            {'id': 4, 'text': '缴纳水电费', 'done': True},
            {'id': 5, 'text': '周报已提交', 'done': True},
        ]
        # 倒计时三档依赖这两个时间点（只改内存，不落盘；shot 模式 main.pyw 已停掉
        # 自动更新与热键，没有任何路径会把这份内存配置写回 config.json）
        self.cfg.data['off_noon'] = '12:00-13:00'
        self.cfg.data['off_evening'] = '18:00'
        # 版本号打桩（关于窗 / 设置窗左下角 / 向导标题栏）
        self._ver_backup = (ui.APP_VERSION, sysutil.APP_VERSION)
        ui.APP_VERSION = sysutil.APP_VERSION = SHOT_VERSION
        # 安装向导「磁盘可用空间」随真实磁盘变化：打桩成固定值
        self._du_backup = shutil.disk_usage
        usage = collections.namedtuple('usage', 'total used free')
        installer.shutil.disk_usage = \
            lambda _p: usage(500 * 2 ** 30, 200 * 2 ** 30, 300 * 2 ** 30)
        # 「所需空间」= payload 目录大小，随打包产物变化：同样打桩成固定值
        self._dirsize_backup = installer._dir_size
        installer._dir_size = lambda _p: 100 * 2 ** 20

        self.panel.todo.rebuild()
        self.panel.set_tab(0, save=False)
        self.panel.show()
        self._build_jobs()
        QTimer.singleShot(300, self._step)

    def finish(self):
        try:
            if self._box is not None:
                self._box._unhook_win_event()
                self._box.close()
                self._box.deleteLater()
        except Exception:
            pass
        if self._sample_dir:
            shutil.rmtree(self._sample_dir, ignore_errors=True)
        if self._du_backup:
            installer.shutil.disk_usage = self._du_backup
        if getattr(self, '_dirsize_backup', None):
            installer._dir_size = self._dirsize_backup
        if self._ver_backup:
            ui.APP_VERSION, sysutil.APP_VERSION = self._ver_backup
        for w in self._keepalive:
            try:
                w.close()
                w.deleteLater()
            except Exception:
                pass
        self.tstore.items = self._todo_backup
        self.tstore.save()
        self.qapp.quit()

    # ---------------- 场景清单 ----------------
    def _build_jobs(self):
        p = self.panel
        for theme in THEME_ORDER:
            self.job('%s_cal' % theme, 400,
                     lambda k=theme: (p.apply_theme(k, save=False),
                                      p.set_tab(0, save=False)),
                     lambda: p)
            self.job('%s_todo' % theme, 400,
                     lambda: p.set_tab(1, save=False), lambda: p)
            self.job('%s_transfer' % theme, 400,
                     lambda: p.set_tab(2, save=False), lambda: p)
            self.job('%s_titlebar' % theme, 500,
                     lambda: p._slide_titlebar(True), lambda: p.titlebar)
            self.job('%s_todo_edit' % theme, 400,
                     lambda: (p._slide_titlebar(False), p.set_tab(1, save=False),
                              p.todo._open_editor(2, '给妈妈回电话')),
                     lambda: p,
                     teardown=lambda: p.todo.rebuild())
            self.job('%s_toast_ok' % theme, 500,
                     lambda: ui.show_toast_on(p, '节假日数据已更新', ok=True,
                                              hold_ms=3600000),
                     lambda: p, teardown=self._hide_toast)
            self.job('%s_toast_fail' % theme, 500,
                     lambda: ui.show_toast_on(p, '节假日更新失败：网络不可用',
                                              ok=False, hold_ms=3600000),
                     lambda: p, teardown=self._hide_toast)
            self.job('%s_settings' % theme, 300, None,
                     self._make_settings)
            self.job('%s_about' % theme, 300, None,
                     lambda: ui.AboutDialog(p))
            self.job('%s_holiday_import' % theme, 300, None,
                     lambda: ui.HolidayImportDialog(
                         p, lambda *a, **kw: False, lambda: None))
            self.job('%s_due_popup' % theme, 300, None,
                     lambda: ui.DuePopup(p, FIXED_NOW.date().isoformat(),
                                         lambda d: None, lambda: None))
            self.job('%s_time_popup' % theme, 300, None,
                     lambda: ui.TimePickerPopup(p, '18:30', lambda t: None))
            self.job('%s_transfer_info' % theme, 300, None,
                     lambda: transfer_ui.TransferInfoDialog(p))
            # 接收确认弹窗放每主题最后：_show_recv 会往传输记录区加一条记录，
            # 之后的 transfer tab 场景（下一主题）会带上它——两批截图顺序一致即可比
            self.job('%s_recv_dialog' % theme, 600, None,
                     self._make_recv, teardown=self._close_recv)
        # ---- 格子（固定深色磨砂，不走全局主题，只出一套）----
        self.job('box_list', 400, self._make_box, lambda: self._box)
        self.job('box_icon', 300, lambda: self._box_view('icon'), lambda: self._box)
        self.job('box_locked', 300,
                 lambda: (self._box_view('list'),
                          self._box.set_locked(True, save=False)),
                 lambda: self._box,
                 teardown=lambda: self._box.set_locked(False, save=False))
        self.job('box_collapsed', 300,
                 lambda: self._box.set_collapsed(True, save=False),
                 lambda: self._box,
                 teardown=lambda: self._box.set_collapsed(False, save=False))
        self.job('box_rename', 300, lambda: self._box._start_rename(),
                 lambda: self._box, teardown=self._cancel_rename)
        self.job('box_menu', 300, None, self._make_box_menu)
        self.job('box_invalid', 300, self._box_to_invalid, lambda: self._box,
                 teardown=self._box_restore)
        self.job('box_confirm', 300, None, self._make_box_confirm)
        # ---- 钉图窗（固定内容位图）----
        self.job('pin_window', 300, None, self._make_pin)
        # ---- 全隐藏单项菜单（跟随全局主题，两套都出）----
        for theme in THEME_ORDER:
            self.job('%s_icons_menu' % theme, 300,
                     lambda k=theme: p.apply_theme(k, save=False),
                     self._make_icons_menu)
        # ---- 安装/卸载向导（固定深色，只出一套）----
        for i in (1, 2, 3):
            self.job('wizard_install_p%d' % i, 300, None,
                     lambda i=i: self._make_wizard(True, i))
            self.job('wizard_uninstall_p%d' % i, 300, None,
                     lambda i=i: self._make_wizard(False, i))

    def job(self, name, settle, setup, target, teardown=None):
        self.jobs.append((name, settle, setup, target, teardown))

    # ---------------- 逐场景执行 ----------------
    def _step(self):
        while self._i < len(self.jobs):
            name, settle, setup, target, teardown = self.jobs[self._i]
            if setup is not None:
                setup()
            self._i += 1
            QTimer.singleShot(settle, lambda n=name, t=target, td=teardown:
                              self._grab(n, t, td))
            return
        self.finish()

    def _grab(self, name, target, teardown):
        try:
            w = target()
            self._keepalive.append(w)
            w.ensurePolished()
            if w.width() < 4 or w.height() < 4:
                w.adjustSize()
            pm = w.grab()
            pm.save(os.path.join(self.dir, '%s.png' % name))
        except Exception as e:
            ui._dbg('selfshot %s 失败：%s' % (name, e))
        finally:
            if teardown is not None:
                try:
                    teardown()
                except Exception:
                    pass
            QTimer.singleShot(0, self._step)

    # ---------------- 各场景的构造辅助 ----------------
    def _hide_toast(self):
        p = self.panel
        if getattr(p, '_toast_anim', None) is not None:
            p._toast_anim.stop()
        p._toast.hide()
        p._toast_op.setOpacity(0.0)

    def _make_settings(self):
        return ui.SettingsDialog(self.panel, lambda **kw: False, lambda: None,
                                 None, lambda seq: '')

    def _make_recv(self):
        view = {'session_id': 'shot-session', 'alias': 'Pixel 6',
                'names': ['照片 001.jpg', '会议纪要.pdf', '安装包.apk'],
                'total': 2457600}
        self._recv_result = {'dir': None}
        self._recv_event = threading.Event()
        self.panel.transfer._show_recv(view, self._recv_result, self._recv_event)
        return self.panel.transfer.recv

    def _close_recv(self):
        t = self.panel.transfer
        key = t._pending[1] if t._pending else None
        try:
            t._recv_reject()
        except Exception:
            pass
        if key is not None:
            try:
                t._remove_record(key)
            except Exception:
                pass

    # ---- 格子 ----
    def _make_box(self):
        if self._box is not None:
            return
        d = tempfile.mkdtemp(prefix='zbox_shot_')
        self._sample_dir = d
        for name in ('会议纪要.docx', '季度数据.xlsx', 'README.txt'):
            with open(os.path.join(d, name), 'wb') as f:
                f.write('zbox 截图自检示例文件\n'.encode('utf-8'))
        # 1x1 PNG（真实格式，图标走系统关联）
        png = bytes.fromhex(
            '89504e470d0a1a0a0000000d494844520000000100000001080600000'
            '01f15c4890000000d4944415478da63fcffff3f030005fe02fea72d99'
            '9d0000000049454e44ae426082')
        with open(os.path.join(d, '图标.png'), 'wb') as f:
            f.write(png)
        # .url 带 IconFile：专门覆盖 _url_icon 的 HICON 提取路径
        # （Qt5 QtWinExtras vs Qt6 ctypes 实现的对比场）
        with open(os.path.join(d, '示例链接.url'), 'w', encoding='utf-8') as f:
            f.write('[InternetShortcut]\nURL=https://example.com\n'
                    'IconFile=C:\\Windows\\System32\\shell32.dll\nIconIndex=0\n')
        os.mkdir(os.path.join(d, '子文件夹'))
        rec = {'id': 'shot-box', 'kind': 'folder', 'path': d, 'name': '示例文件夹',
               'x': 60, 'y': 60, 'w': 0, 'h': 0,
               'collapsed': False, 'locked': False, 'sort': 'name', 'view': 'list'}
        self._box = bx.BoxWindow(_FakeBoxMgr(), rec)

    def _box_view(self, view):
        self._box.rec['view'] = view
        self._box.list.set_view(view)

    def _cancel_rename(self):
        self._box._edit_cancel = True
        self._box._finish_rename()

    def _make_box_menu(self):
        m = self._box._build_menu()
        m.adjustSize()
        return m

    def _box_to_invalid(self):
        self._box_real_path = self._box.rec['path']
        self._box.rec['path'] = self._box_real_path + '_nope'
        self._box.refresh()

    def _box_restore(self):
        self._box.rec['path'] = self._box_real_path
        self._box.refresh()

    def _make_box_confirm(self):
        return self._box._dissolve_confirm_dialog()

    # ---- 钉图 ----
    def _make_pin(self):
        img = QImage(320, 200, QImage.Format_ARGB32)
        img.fill(QColor('#f5f0e6'))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor('#262b45'))
        p.setFont(QFont(ui.pick_fonts()[0], 14))
        p.drawText(img.rect(), Qt.AlignCenter, '钉图示例\n2026-10-15 10:08')
        p.end()
        return pinshot.PinWindow(img, QPoint(0, 0), '#e05252')

    # ---- 全隐藏单项菜单 ----
    def _make_icons_menu(self):
        m = QMenu(self.panel)
        m.addAction(sysutil.SHOW_ICONS_TEXT, lambda: None)
        m.adjustSize()
        return m

    # ---- 向导 ----
    def _make_wizard(self, install, page):
        attr = '_wiz_install' if install else '_wiz_uninstall'
        wiz = getattr(self, attr, None)
        if wiz is None:
            wiz = installer.InstallWizard() if install else installer.UninstallWizard()
            setattr(self, attr, wiz)
            self._keepalive.append(wiz)
        wiz._stack.setCurrentIndex(page - 1)
        return wiz
