# -*- coding: utf-8 -*-
"""验证：PySide6 的方法调用在非 GUI 线程执行时，是否释放 GIL。

方法：主线程做一个纯 Python 忙循环并测推进速度；worker 线程同时调
  A) 纯 ctypes 调用（ctypes 官方保证释放 GIL）
  B) PySide6 调用（QFileIconProvider.icon）
若 worker 调 PySide6 时主线程被卡住 → PySide6 不释放 GIL。

用法：python perf-audit\\gil_test.py
"""
import ctypes
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from PySide6.QtCore import QFileInfo
from PySide6.QtWidgets import QApplication, QFileIconProvider

app = QApplication.instance() or QApplication([])

DIR = r'D:\Document\桌面快捷方式'
paths = []
if os.path.isdir(DIR):
    paths = [os.path.join(DIR, n) for n in sorted(os.listdir(DIR))
             if os.path.isfile(os.path.join(DIR, n))][:20]


def spin(label, seconds=3.0):
    """主线程忙循环，统计推进次数与被卡的最长间隔。"""
    t_end = time.perf_counter() + seconds
    n = 0
    worst = 0.0
    last = time.perf_counter()
    while time.perf_counter() < t_end:
        n += 1
        now = time.perf_counter()
        gap = now - last
        if gap > worst:
            worst = gap
        last = now
    return {'label': label, 'iterations': n, 'worst_gap_ms': round(worst * 1000, 1)}


def run_worker(fn, label):
    done = threading.Event()
    th = threading.Thread(target=fn, daemon=True)
    t0 = time.perf_counter()
    th.start()
    r = spin(label)
    r['worker_ms'] = round((time.perf_counter() - t0) * 1000, 1)
    done.set()
    th.join(timeout=10)
    return r


def worker_ctypes():
    """纯 ctypes：ctypes 的 CDLL 调用会释放 GIL。"""
    import ctypes as c
    from ctypes import wintypes

    class SFI(ctypes.Structure):
        _fields_ = [('hIcon', ctypes.c_void_p), ('iIcon', ctypes.c_int),
                    ('dwAttributes', wintypes.DWORD),
                    ('szDisplayName', wintypes.WCHAR * 260),
                    ('szTypeName', wintypes.WCHAR * 80)]

    s32 = c.windll.shell32
    s32.SHGetFileInfoW.restype = c.c_size_t
    s32.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, c.c_void_p,
                                   wintypes.UINT, wintypes.UINT]
    for p in paths:
        sfi = SFI()
        s32.SHGetFileInfoW(p, 0, c.byref(sfi), c.sizeof(sfi), 0x000100)
        if sfi.hIcon:
            c.windll.user32.DestroyIcon(int(sfi.hIcon))


def worker_pyside():
    prov = QFileIconProvider()
    for p in paths:
        prov.icon(QFileInfo(p))


print('样本：%d 个文件（%s）' % (len(paths), DIR))
print('基线（无 worker）：', spin('baseline'))

# 让 shell 缓存先热，测的是「GIL 占用」而非「IO 等待」
prov = QFileIconProvider()
for p in paths:
    prov.icon(QFileInfo(p))

print('worker=ctypes :', run_worker(worker_ctypes, 'ctypes'))
print('worker=pyside :', run_worker(worker_pyside, 'pyside'))
print('基线（无 worker）：', spin('baseline2'))
