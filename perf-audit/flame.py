# -*- coding: utf-8 -*-
"""启动期 CPU 采样：用 py-spy record 抓启动全程的热点，定位耗时落在哪个函数。

输出 perf-audit\\results\\flame-<tag>.raw（py-spy raw 格式）与
perf-audit\\results\\flame-<tag>.top.json（按自身耗时聚合的 Top 函数）。

用法：python perf-audit\\flame.py [--tag baseline]
"""
import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import probe  # noqa: E402


def parse_raw(path):
    """py-spy raw 格式：每行 `func (file:line);func (file:line);...;N`
    —— 栈帧**从叶子到根**，末位 N 是该栈的样本数（不是时间）。

    leaf      = 栈顶（真正在执行的代码）样本数
    inclusive = 该帧出现在栈上任意位置的样本数（含子调用）
    """
    leaf = collections.Counter()
    inclusive = collections.Counter()
    total = 0
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # 末位样本数是用**空格**分隔的（`...;_icon_for (boxes.py:1243) 1`）
            head, _, tail = line.rpartition(' ')
            try:
                n = int(tail)
            except ValueError:
                continue
            frames = head.split(';')
            if not frames:
                continue
            total += n
            leaf[frames[0]] += n
            for fr in set(frames):
                inclusive[fr] += n
    return leaf, inclusive, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='baseline')
    ap.add_argument('--duration', type=int, default=9)
    ap.add_argument('--rate', type=int, default=250)
    args = ap.parse_args()

    appdata = tempfile.mkdtemp(prefix='zbox_flame_', dir=os.path.join(HERE, 'tmp'))
    probe._seed_appdata(appdata, True)
    env = probe._app_env(appdata)
    raw = os.path.join(HERE, 'results', 'flame-%s.raw' % args.tag)
    stage_out = os.path.join(HERE, 'tmp', 'flame_stage.json')

    pythonw = probe.pythonw_path()
    proc = subprocess.Popen([pythonw, os.path.join(HERE, 'stage_probe.py'),
                             '--out', stage_out],
                            cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.35)   # 让解释器起来再挂 py-spy
    try:
        r = subprocess.run(['py-spy', 'record', '--pid', str(proc.pid),
                            '--duration', str(args.duration), '--rate', str(args.rate),
                            '--format', 'raw', '--output', raw],
                           capture_output=True, text=True, timeout=args.duration + 30)
        if r.stderr.strip():
            print('[py-spy stderr]\n' + r.stderr[:2000])
        if r.stdout.strip():
            print('[py-spy stdout]\n' + r.stdout[:800])
    finally:
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    if not os.path.exists(raw):
        print('py-spy 无输出')
        shutil.rmtree(appdata, ignore_errors=True)
        return 1

    leaf, inclusive, total = parse_raw(raw)
    out = {
        'tag': args.tag,
        'total_samples': total,
        'top_leaf': [{'frame': k, 'samples': v, 'pct': round(v * 100.0 / max(total, 1), 2)}
                     for k, v in leaf.most_common(30)],
        'top_inclusive': [{'frame': k, 'samples': v, 'pct': round(v * 100.0 / max(total, 1), 2)}
                          for k, v in inclusive.most_common(40)],
    }
    dst = os.path.join(HERE, 'results', 'flame-%s.top.json' % args.tag)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    shutil.rmtree(appdata, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
