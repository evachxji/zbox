# -*- coding: utf-8 -*-
"""文件操作微基准：量化「不同文件数量下」的扫描 / 刷新 / 图标提取耗时。

对应 boxes.py 的热路径：
  * `_scan_dir`        → os.scandir + 每条目 stat()          （映射格子刷新）
  * `_entries_from_items` → 每记账条目 2 次 stat            （空白格子刷新）
  * `_baked_icon`      → QFileIconProvider.icon() 取图标      （每个条目一次）

用法：python perf-audit\\microbench.py [--sizes 100 1000 10000] [--out <json>]
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def make_tree(root, n):
    """造 n 个条目：扁平放在 root 下（scandir 才能一次看到 N 个）。"""
    os.makedirs(root, exist_ok=True)
    for i in range(n):
        p = os.path.join(root, 'file_%06d.txt' % i)
        with open(p, 'w') as f:
            f.write('x' * 64)
    return root


def timeit(fn, repeat=3):
    ts = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    ts.sort()
    return {'best_ms': round(ts[0] * 1000, 2),
            'median_ms': round(ts[len(ts) // 2] * 1000, 2),
            'worst_ms': round(ts[-1] * 1000, 2)}


def bench_scan_dir(root):
    """等价 boxes._scan_dir：scandir + 每条目 stat。"""
    def run():
        out = []
        for it in os.scandir(root):
            st = it.stat()
            out.append((it.name, it.path, it.is_dir(), st))
        return out
    return timeit(run)


def bench_listdir_isdir(root):
    """等价「枚举 + 判断是不是目录」的朴素写法。"""
    def run():
        out = []
        for name in os.listdir(root):
            p = os.path.join(root, name)
            out.append((name, p, os.path.isdir(p)))
        return out
    return timeit(run)


def bench_icons(root, limit=600):
    """等价 _baked_icon：每个条目向 shell 取一次图标并烘成位图。

    limit 封顶：Windows 的 shell 图标提取有全局缓存与系统开销，
    取几千个会花很久；这里取前 limit 个并给出单条目均摊成本。
    """
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    app = QApplication.instance() or QApplication([])
    provider = app.iconProvider() if hasattr(app, 'iconProvider') else None
    from PySide6.QtWidgets import QFileIconProvider
    prov = QFileIconProvider()
    paths = []
    for base, dirs, files in os.walk(root):
        for fn in files:
            paths.append(os.path.join(base, fn))
            if len(paths) >= limit:
                break
        if len(paths) >= limit:
            break

    def run():
        out = []
        for p in paths:
            icon = prov.icon(__import__('PySide6.QtCore', fromlist=['QFileInfo']).QFileInfo(p))
            pm = icon.pixmap(16, 16)
            out.append(QIcon(pm) if not pm.isNull() else icon)
        return out

    r = timeit(run, repeat=2)
    r['items'] = len(paths)
    r['per_item_ms'] = round(r['median_ms'] / max(len(paths), 1), 3)
    r['extrapolated_1000_ms'] = round(r['per_item_ms'] * 1000, 1)
    r['extrapolated_10000_ms'] = round(r['per_item_ms'] * 10000, 1)
    return r


def bench_stat_only(root):
    """等价 _entries_from_items 的记账部分：每条目 2 次 stat。"""
    names = []
    for base, dirs, files in os.walk(root):
        for fn in files:
            names.append(os.path.join(base, fn))
        break

    def run():
        for p in names:
            os.stat(p)
            os.path.isdir(p)
        return len(names)

    r = timeit(run)
    r['items'] = len(names)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sizes', type=int, nargs='+', default=[100, 1000, 10000])
    ap.add_argument('--out', default=os.path.join(HERE, 'results', 'microbench.json'))
    args = ap.parse_args()

    base = tempfile.mkdtemp(prefix='zbox_mb_', dir=os.path.join(HERE, 'tmp'))
    out = {}
    try:
        for n in args.sizes:
            root = make_tree(os.path.join(base, 'n%d' % n), n)
            row = {
                'scan_dir': bench_scan_dir(root),
                'listdir_isdir': bench_listdir_isdir(root),
                'stat_x2': bench_stat_only(root),
            }
            row['icons'] = bench_icons(root)
            out['n=%d' % n] = row
            print('n=%d  %s' % (n, json.dumps(row, ensure_ascii=False)))
            shutil.rmtree(root, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('[saved] %s' % args.out)


if __name__ == '__main__':
    sys.exit(main())
