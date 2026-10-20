# -*- coding: utf-8 -*-
"""图标提取耗时归因：验证「83.6ms/次」的成因。

候选假设：
  ① .lnk 快捷方式需要解析目标并取目标图标 → 显著慢于普通文件
  ② 提取时 Explorer UI 线程正忙于重排桌面图标 → 同步消息被阻塞（与文件类型无关）

本脚本对同一批路径做三组测量：
  A. 普通文件（.txt）
  B. 快捷方式（.lnk，指向真实存在的 exe）
  C. 用户真实映射目录里的混合条目
外加「同一路径重复提取」的耗时（衡量缓存命中收益）。

用法：python perf-audit\\icon_bench.py [--dir "<真实目录>"]
"""
import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def make_links(root, n, target):
    """造 n 个 .lnk 指向 target（用 IShellLink COM，最接近真实快捷方式）。"""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [('Data1', ctypes.c_ulong), ('Data2', ctypes.c_ushort),
                    ('Data3', ctypes.c_ushort), ('Data4', ctypes.c_ubyte * 8)]

    ole32 = ctypes.WinDLL('ole32')
    # ⚠️ 必须显式声明 argtypes/restype：windll 默认按 32 位截断指针参数，
    # 64 位下指针高位丢失（AGENTS.md 记载的通用坑）。
    ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(GUID)]
    ole32.CLSIDFromString.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p,
                                       wintypes.DWORD, ctypes.POINTER(GUID),
                                       ctypes.POINTER(ctypes.c_void_p)]
    ole32.CoCreateInstance.restype = ctypes.c_long

    def clsid(s):
        g = GUID()
        if ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g)) != 0:
            raise RuntimeError('CLSIDFromString failed: %s' % s)
        return g

    CLSID_ShellLink = clsid('{00021401-0000-0000-C000-000000000046}')
    IID_IShellLinkW = clsid('{000214F9-0000-0000-C000-000000000046}')

    # IShellLinkW vtable 索引：QueryInterface0 AddRef1 Release2 SetPath3 ... Save18
    IDX_SET_PATH = 3
    IDX_SAVE = 18

    out = []
    for i in range(n):
        p = os.path.join(root, 'lnk_%03d.lnk' % i)
        obj = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(CLSID_ShellLink), None, 1,
                                    ctypes.byref(IID_IShellLinkW), ctypes.byref(obj))
        if hr != 0 or not obj:
            continue
        # COM 接口指针的首 DWORD 是 vtable 地址
        vtbl_addr = ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p)).contents.value
        vtbl = ctypes.cast(vtbl_addr, ctypes.POINTER(ctypes.c_void_p))
        fn_set_path = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)(
            vtbl[IDX_SET_PATH])
        fn_save = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)(
            vtbl[IDX_SAVE])
        fn_set_path(obj, target)
        fn_save(obj, p)
        if os.path.exists(p):
            out.append(p)
    return out


def measure(paths, provider, dpr=1.0):
    """逐个取图标并烘成位图，返回 [(耗时ms, 路径)]。"""
    from PySide6.QtCore import QFileInfo
    times = []
    for p in paths:
        t0 = time.perf_counter()
        icon = provider.icon(QFileInfo(p))
        pm = icon.pixmap(16, dpr)
        times.append(((time.perf_counter() - t0) * 1000, p))
    return times


def summarize(name, pairs):
    if not pairs:
        return {'name': name, 'count': 0}
    times = sorted(t for t, _ in pairs)
    slowest = sorted(pairs, key=lambda x: -x[0])[:5]
    return {
        'name': name,
        'count': len(times),
        'total_ms': round(sum(times), 1),
        'min_ms': round(times[0], 3),
        'median_ms': round(statistics.median(times), 3),
        'p90_ms': round(times[int(len(times) * 0.9) - 1], 3),
        'max_ms': round(times[-1], 3),
        'mean_ms': round(statistics.mean(times), 3),
        'slowest': [{'ms': round(t, 1), 'path': p} for t, p in slowest],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=None, help='用户真实映射目录（混合条目）')
    args = ap.parse_args()

    from PySide6.QtWidgets import QApplication, QFileIconProvider
    app = QApplication.instance() or QApplication([])
    provider = QFileIconProvider()

    base = tempfile.mkdtemp(prefix='zbox_icon_', dir=os.path.join(HERE, 'tmp'))
    rows = []
    try:
        # A. 普通文件
        txt_dir = os.path.join(base, 'txt')
        os.makedirs(txt_dir)
        txts = []
        for i in range(42):
            p = os.path.join(txt_dir, 'f_%03d.txt' % i)
            with open(p, 'w') as f:
                f.write('x')
            txts.append(p)
        rows.append(summarize('A. 普通文件 .txt (42)', measure(txts, provider)))

        # B. 快捷方式（COM 造 .lnk 不可靠时跳过，用 C 组真实目录替代对比）
        try:
            lnk_dir = os.path.join(base, 'lnk')
            os.makedirs(lnk_dir)
            target = os.path.join(txt_dir, 'f_000.txt')
            lnks = make_links(lnk_dir, 42, target)
            if lnks:
                rows.append(summarize('B. 快捷方式 .lnk (%d)' % len(lnks), measure(lnks, provider)))
        except Exception as e:
            rows.append({'name': 'B. 快捷方式 .lnk', 'skipped': str(e)[:120]})

        # C. 用户真实目录
        if args.dir and os.path.isdir(args.dir):
            real = []
            for name in os.listdir(args.dir):
                p = os.path.join(args.dir, name)
                if os.path.isfile(p):
                    real.append(p)
            rows.append(summarize('C. 真实目录 %s (%d)' % (os.path.basename(args.dir), len(real)),
                                  measure(real, provider)))

        # D. 同一路径重复提取（第二次起 shell 有缓存）
        if txts:
            measure(txts[:5], provider)   # 预热
            rows.append(summarize('D. 重复提取（热）', measure(txts, provider)))

        # E. 整批再来一次（模拟第二次 refresh）
        if txts:
            rows.append(summarize('E. 第二轮整批提取', measure(txts, provider)))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    out = {'rows': rows}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    dst = os.path.join(HERE, 'results', 'icon-bench.json')
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('[saved] %s' % dst)


if __name__ == '__main__':
    sys.exit(main())
