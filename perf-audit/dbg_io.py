# -*- coding: utf-8 -*-
"""精确测量 `_dbg` 的写盘频率与吞吐（验证 P0-3）。

跑一个真实 zbox 实例（ZBOX_DEBUG=1），观察 %TEMP%\\zbox_debug.log 在固定窗口内的
行数增长与字节增长 -> 得出「每秒写盘次数」与「每秒写入字节」。

用法：python perf-audit\\dbg_io.py [--seconds 60]
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import probe  # noqa: E402

LOG = os.path.join(os.environ.get('TEMP', '.'), 'zbox_debug.log')


def stat_log():
    if not os.path.exists(LOG):
        return 0, 0
    with open(LOG, 'rb') as f:
        data = f.read()
    return data.count(b'\n'), len(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=60)
    args = ap.parse_args()

    if probe.instance_running():
        print('!! 已有实例在跑')
        return 2

    appdata = os.path.join(HERE, 'tmp', 'dbgio')
    probe._seed_appdata(appdata, True)
    env = probe._app_env(appdata)
    env['ZBOX_DEBUG'] = '1'

    before = stat_log()
    proc, found, appdata2, env2 = probe.spawn_app()
    if not found[0]:
        proc.kill()
        print('窗口未出现')
        return 1
    try:
        time.sleep(3)          # 跳过启动期
        t0 = time.perf_counter()
        start = stat_log()
        time.sleep(args.seconds)
        end = stat_log()
        dt = time.perf_counter() - t0
        lines = end[0] - start[0]
        byts = end[1] - start[1]
        print(json_result := (
            '窗口 %.1fs：日志 +%d 行 (+%d 字节)  =>  %.2f 行/秒，%.1f 字节/秒'
            % (dt, lines, byts, lines / dt, byts / dt)))
        # 估算每秒的 open/write/close 次数：_dbg 每次调用 = 1 次 open+write+close
        print('每次 _dbg 调用 = 1 次 open(append)+write+close'
              '  => 约 %.1f 次/秒 的文件打开与关闭' % (lines / dt))
    finally:
        probe._quit(proc, env2)
        import shutil
        shutil.rmtree(appdata, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
