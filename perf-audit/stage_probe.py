# -*- coding: utf-8 -*-
"""启动分阶段打点：外部插桩（不改 main.pyw 一行代码），量出启动各阶段耗时。

⚠️ 不能用「继承 + super()」的方式打点：app.py / boxes.py 里用了
   `super(FloatingPanel, self).__init__()` 这类**显式类名**的 super 调用，
   子类化会让它指回原类、参数错位抛 TypeError。故一律改用**包装函数**替换模块属性，
   并在实例上单独覆盖需要打点的方法。

量出的阶段：
    进程起点 → import 完成 → QApplication 建好 → Config/HolidayStore/TodoStore
    → FloatingPanel 构造完 → BoxManager 构造完 → 面板 show() → 事件循环跑起来

用法：python perf-audit\\stage_probe.py [--out <json>]
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

T0 = time.perf_counter()
marks = []


def mark(name):
    marks.append({'stage': name, 'ms': round((time.perf_counter() - T0) * 1000, 1)})


def wrap_call(orig, before, after):
    def wrapper(*a, **k):
        mark(before)
        r = orig(*a, **k)
        mark(after)
        return r
    return wrapper


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(HERE, 'results', 'stage.json'))
    args = ap.parse_args()

    import main as M
    mark('import main 完成')

    # main() 会把 sys.excepthook 换成落盘版，异常就看不见了 —— 先包一层，
    # 出错时既落盘又打印。
    _orig_hook = sys.excepthook

    def hook(t, v, tb):
        import traceback
        sys.stderr.write('!! 未捕获异常（stage_probe）:\n')
        traceback.print_exception(t, v, tb, file=sys.stderr)
        _orig_hook(t, v, tb)

    # --- QApplication ---
    # main() 里先调静态方法 QApplication.setAttribute / setQuitOnLastWindowClosed，
    # 再 QApplication(sys.argv)。所以代理必须是「带静态方法的类」，
    # 纯函数包装会丢这两个静态方法。
    _QA = M.QApplication

    def _install_exec_hook(app):
        from PySide6.QtCore import QTimer
        _orig_exec = app.exec

        def exec_(*a, **k):
            mark('qapp.exec() 入口')
            # 事件循环第一拍 = 真正能响应用户输入的时刻（此前还在构造）
            QTimer.singleShot(0, _mark_interactive)
            QTimer.singleShot(2500, _dump_and_quit)
            return _orig_exec(*a, **k)
        app.exec = exec_

    def _mark_interactive():
        mark('事件循环首拍（可交互）')
        try:
            p = M.ui.FloatingPanel
            # 面板实例挂在 main() 的局部变量里，从实例列表反查
            for w in _QApplication_widgets():
                if getattr(w, 'objectName', None) and w.metaObject().className().startswith('FloatingPanel'):
                    mark('面板已可见=%s' % bool(w.isVisible()))
        except Exception:
            pass

    def _QApplication_widgets():
        from PySide6.QtWidgets import QApplication
        return QApplication.topLevelWidgets()

    class QAppProxy:
        setAttribute = staticmethod(_QA.setAttribute)
        setQuitOnLastWindowClosed = staticmethod(_QA.setQuitOnLastWindowClosed)

        @staticmethod
        def instance():
            return _QA.instance()

        def __new__(cls, *a, **k):
            mark('QApplication() 前')
            app = _QA(*a, **k)
            mark('QApplication() 后')
            _install_exec_hook(app)
            return app

    M.QApplication = QAppProxy

    # --- FloatingPanel / BoxManager / 数据层 ---
    # ⚠️ 必须**在类上打补丁**，不能替换模块属性：app.py:3048 写的是
    # `super(FloatingPanel, self).__init__()` —— 显式类名的 super 会去模块全局名里找，
    # 一旦把 app.FloatingPanel 换成函数，super() 立刻报
    # 「argument 1 must be a type, not function」。
    def patch_init(cls, before, after):
        orig = cls.__init__

        def new_init(self, *a, **k):
            mark(before)
            r = orig(self, *a, **k)
            mark(after)
            return r
        cls.__init__ = new_init

    def patch_method(cls, name, before, after):
        orig = getattr(cls, name)

        def new_m(self, *a, **k):
            mark(before)
            r = orig(self, *a, **k)
            mark(after)
            return r
        setattr(cls, name, new_m)

    patch_init(M.ui.FloatingPanel, 'FloatingPanel() 前', 'FloatingPanel() 后')
    patch_method(M.ui.FloatingPanel, 'show', 'panel.show() 前', 'panel.show() 后')
    if hasattr(M.bx, 'BoxManager'):
        patch_init(M.bx.BoxManager, 'BoxManager() 前', 'BoxManager() 后')
    patch_init(M.ui.Config, 'Config() 前', 'Config() 后')
    patch_init(M.ui.TodoStore, 'TodoStore() 前', 'TodoStore() 后')
    patch_init(M.cd.HolidayStore, 'HolidayStore() 前', 'HolidayStore() 后')

    # --- 盒子模块细分（累计计时：高频函数不逐次打点，只累计次数与总耗时） ---
    acc = {}

    def patch_acc(cls, name, label):
        orig = getattr(cls, name, None)
        if orig is None:
            return
        rec = acc.setdefault(label, {'calls': 0, 'ms': 0.0})

        def new_m(self, *a, **k):
            t0 = time.perf_counter()
            try:
                return orig(self, *a, **k)
            finally:
                rec['calls'] += 1
                rec['ms'] += (time.perf_counter() - t0) * 1000
        setattr(cls, name, new_m)

    bx = M.bx
    patch_acc(bx.BoxManager, 'restore', 'boxes:BoxManager.restore')
    patch_acc(bx.BoxManager, '_upgrade_blank_boxes', 'boxes:_upgrade_blank_boxes')
    patch_acc(bx.BoxManager, '_restore_desktop_icons', 'boxes:_restore_desktop_icons')
    patch_acc(bx.BoxManager, '_save_desktop_icons', 'boxes:_save_desktop_icons')
    patch_acc(bx.BoxWindow, '__init__', 'boxes:BoxWindow.__init__')
    patch_acc(bx.BoxWindow, 'refresh', 'boxes:BoxWindow.refresh')
    patch_acc(bx.BoxWindow, '_baked_icon', 'boxes:_baked_icon')
    patch_acc(bx.BoxWindow, '_scan_dir', 'boxes:_scan_dir')
    patch_acc(bx.BoxWindow, 'hide_icons', 'boxes:hide_icons')
    patch_acc(bx.BoxWindow, 'show', 'boxes:BoxWindow.show')
    patch_acc(bx.BoxWindow, '_apply_rec_to_ui', 'boxes:_apply_rec_to_ui')
    patch_acc(bx.BoxWindow, '_request_icon', 'boxes:_request_icon')
    patch_acc(bx.BoxWindow, 'set_collapsed', 'boxes:set_collapsed')
    patch_acc(bx.BoxWindow, 'set_locked', 'boxes:set_locked')
    patch_acc(bx.BoxWindow, 'setStyleSheet', 'boxes:BoxWindow.setStyleSheet')
    patch_acc(bx.BoxList, 'set_view', 'boxes:BoxList.set_view')
    if hasattr(bx, '_DesktopIconLayout'):
        patch_acc(bx._DesktopIconLayout, 'snapshot', 'boxes:_DesktopIconLayout.snapshot')
        patch_acc(bx._DesktopIconLayout, 'enum_icons', 'boxes:_DesktopIconLayout.enum_icons')
        patch_acc(bx._DesktopIconLayout, 'restore_positions', 'boxes:_DesktopIconLayout.restore_positions')

    # --- 待办 / 日历细分 ---
    patch_acc(M.ui.TodoWidget, 'rebuild', 'app:TodoWidget.rebuild')
    patch_acc(M.ui.TodoWidget, '_sync_row_heights', 'app:TodoWidget._sync_row_heights')
    patch_acc(M.ui.TodoWidget, '_make_row', 'app:TodoWidget._make_row')
    patch_acc(M.ui.FloatingPanel, 'apply_theme', 'app:panel.apply_theme')
    if hasattr(M.ui, 'CalendarWidget'):
        patch_acc(M.ui.CalendarWidget, 'refresh', 'app:CalendarWidget.refresh')
        patch_acc(M.ui.CalendarWidget, 'build', 'app:CalendarWidget.build')
        patch_acc(M.ui.CalendarWidget, '__init__', 'app:CalendarWidget.__init__')
    patch_acc(M.ui.TodoWidget, '__init__', 'app:TodoWidget.__init__')
    patch_acc(M.ui.FloatingPanel, '_ensure_band', 'app:panel._ensure_band')
    patch_acc(M.ui.FloatingPanel, 'set_tab', 'app:panel.set_tab')
    # 传输页 / 视频页（构造期是否为空档大头）
    patch_acc(M.ui.transfer_ui.TransferWidget, '__init__', 'transfer:TransferWidget.__init__')
    patch_acc(M.ui.transfer_ui.TransferWidget, 'enable_service', 'transfer:enable_service')
    patch_acc(M.ui.transfer_ui.TransferWidget, 'set_theme', 'transfer:set_theme')
    patch_acc(M.ui.transfer_ui.TransferWidget, '_build_gate', 'transfer:_build_gate')
    patch_acc(M.ui.transfer_ui.TransferWidget, '_refresh_devices', 'transfer:_refresh_devices')
    patch_acc(M.ui.video_ui.VideoWidget, '__init__', 'video:VideoWidget.__init__')
    patch_acc(M.ui.video_ui.VideoWidget, '_refresh_versions', 'video:_refresh_versions')

    # 模块级函数（app.py 内部按全局名调用）
    def patch_func(mod, name, label):
        orig = getattr(mod, name, None)
        if orig is None:
            return
        rec = acc.setdefault(label, {'calls': 0, 'ms': 0.0})

        def new_f(*a, **k):
            t0 = time.perf_counter()
            try:
                return orig(*a, **k)
            finally:
                rec['calls'] += 1
                rec['ms'] += (time.perf_counter() - t0) * 1000
        setattr(mod, name, new_f)

    patch_func(M.ui, 'pick_fonts', 'app:pick_fonts')
    patch_func(M.ui, '_indicator_icons', 'app:_indicator_icons')
    patch_func(M.ui, 'make_icon', 'app:make_icon')
    for fn in ('_file_icon', '_refresh_icon', '_alias_icon', '_default_save_dir'):
        patch_func(M.ui.transfer_ui, fn, 'transfer:%s' % fn)
    for fn in ('_placeholder_icon', '_icon_worker', '_icon_cache_put', '_box_qss'):
        patch_func(bx, fn, 'boxes:%s' % fn)

    # --- 事件循环真正跑起来后 dump 并退出 ---
    def _dump_and_quit():
        mark('事件循环运行中（+2.5s）')
        app = M.QApplication.instance()
        out = {'marks': marks}
        out['accumulated'] = {k: {'calls': v['calls'], 'ms': round(v['ms'], 1)}
                              for k, v in sorted(acc.items(), key=lambda kv: -kv[1]['ms'])}
        out.update(_mem_snapshot())
        text = json.dumps(out, ensure_ascii=False, indent=2)
        try:
            os.makedirs(os.path.dirname(args.out), exist_ok=True)
            with open(args.out, 'w', encoding='utf-8') as f:
                f.write(text)
        except Exception:
            pass
        try:
            sys.stdout.write(text + '\n')
            sys.stdout.flush()
        except Exception:
            pass
        if app:
            app.quit()

    def _mem_snapshot():
        """进程内存快照（ctypes 直调 Win32，不引 psutil）。"""
        import ctypes as _c
        import ctypes.wintypes as _wt
        import os as _os

        class _PMC(_c.Structure):
            _fields_ = [
                ('cb', _wt.DWORD), ('PageFaultCount', _wt.DWORD),
                ('PeakWorkingSetSize', _c.c_size_t), ('WorkingSetSize', _c.c_size_t),
                ('QuotaPeakPagedPoolUsage', _c.c_size_t), ('QuotaPagedPoolUsage', _c.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', _c.c_size_t), ('QuotaNonPagedPoolUsage', _c.c_size_t),
                ('PagefileUsage', _c.c_size_t), ('PeakPagefileUsage', _c.c_size_t),
                ('PrivateUsage', _c.c_size_t),
            ]

        pid = _os.getpid()
        k32 = _c.WinDLL('kernel32', use_last_error=True)
        ps = _c.WinDLL('psapi', use_last_error=True)
        h = k32.OpenProcess(0x1000 | 0x0010, False, pid)
        if not h:
            return {}
        try:
            c = _PMC()
            c.cb = _c.sizeof(c)
            if not ps.GetProcessMemoryInfo(h, _c.byref(c), c.cb):
                return {}
            return {'working_set_mb': round(c.WorkingSetSize / 1048576, 1),
                    'private_mb': round(c.PrivateUsage / 1048576, 1),
                    'peak_ws_mb': round(c.PeakWorkingSetSize / 1048576, 1)}
        finally:
            k32.CloseHandle(h)

    try:
        M.main()
    except SystemExit:
        pass
    except BaseException:
        hook(*sys.exc_info())
        raise
    finally:
        sys.excepthook = _orig_hook
        if not os.path.exists(args.out):
            out = {'marks': marks, 'note': '进程在 dump 前结束（未进事件循环）'}
            with open(args.out, 'w', encoding='utf-8') as f:
                f.write(json.dumps(out, ensure_ascii=False, indent=2))
            print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
