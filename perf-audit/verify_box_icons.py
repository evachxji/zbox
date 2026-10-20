# -*- coding: utf-8 -*-
"""端到端验证：真实格子窗口在后台图标回填后长什么样（截图目检）。

跑一个隔离 APPDATA 的 zbox 实例（复制真实配置，含 3 个格子），等后台图标线程
把图标取回并回填后，逐个格子窗口 grab() 存 PNG。

用法：python perf-audit\\verify_box_icons.py [--wait 10]
输出：perf-audit\\results\\box-<序号>-<名字>.png
"""
import argparse
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
import probe  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--wait', type=float, default=10.0)
    args = ap.parse_args()

    appdata = tempfile.mkdtemp(prefix='zbox_vbox_', dir=os.path.join(HERE, 'tmp'))
    probe._seed_appdata(appdata, True)
    env = probe._app_env(appdata)

    import subprocess
    # 用独立进程跑真程序（避免在本进程里构造完整 UI 树），再截图
    outdir = os.path.join(HERE, 'results')
    os.makedirs(outdir, exist_ok=True)

    code = r'''
import os, sys, time
sys.path.insert(0, %r)
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
import app as ui, boxes as bx, calendar_data as cd, transfer, platform

data_dir = sysutil_appdata = None
from sysutil import appdata_dir
data_dir = appdata_dir()
cfg = ui.Config(os.path.join(data_dir, 'config.json'))
hstore = cd.HolidayStore(os.path.join(data_dir, 'holidays.json'))
tstore = ui.TodoStore(os.path.join(data_dir, 'todos.json'))
fp = transfer.load_or_create_fingerprint(cfg.path)
cfg.data['transfer_fingerprint'] = fp
dev = transfer.DeviceInfo.local('verify', fp)
qapp = QApplication(sys.argv)
panel = ui.FloatingPanel(cfg, hstore, tstore, dev,
                         transfer_autostart=False, video_autostart=False)
mgr = bx.BoxManager(data_dir, panel)

def shoot():
    outdir = %r
    for i, w in enumerate(mgr.windows):
        pm = w.grab()
        p = os.path.join(outdir, 'box-%%d-%%s.png' %% (i, w.rec.get('name', '?')))
        pm.save(p)
        print('saved', p)
    # 同时导出格子里每行的图标尺寸/非空情况（占位图标 vs 真图标的客观判据）
    for i, w in enumerate(mgr.windows):
        n = w.list.count()
        real = 0
        for j in range(n):
            it = w.list.item(j)
            if not it.icon().isNull():
                real += 1
        print('box %%d name=%%s rows=%%d withIcon=%%d' %% (i, w.rec.get('name'), n, real))
    qapp.quit()

QTimer.singleShot(%d, shoot)
qapp.exec()
''' % (REPO, outdir, int(args.wait * 1000))

    codefile = os.path.join(HERE, 'tmp', '_verify_box_run.py')
    os.makedirs(os.path.dirname(codefile), exist_ok=True)
    with open(codefile, 'w', encoding='utf-8') as f:
        f.write(code)
    r = subprocess.run([sys.executable, codefile], cwd=REPO, env=env, timeout=args.wait + 60)
    shutil.rmtree(appdata, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
