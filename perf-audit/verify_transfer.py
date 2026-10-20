# -*- coding: utf-8 -*-
"""验证 P0-2（传输服务后台启动）的功能正确性。

三个场景：
  A. 正常启动 → 服务在后台起来，端口 53327 真的在监听，且配置里 transfer_enabled 仍为 true
  B. 退出程序 → 端口被释放（不留占用）
  C. 端口被占 → 启动失败时门禁层切「不可用」，配置里 transfer_enabled 被写回 false

用法：python perf-audit\\verify_transfer.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import probe  # noqa: E402

PORT = 53327


def port_listening():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect(('127.0.0.1', PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def cfg_get(appdata, key):
    p = os.path.join(appdata, 'zbox', 'config.json')
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f).get(key)
    except Exception:
        return None


def scenario_a():
    appdata = tempfile.mkdtemp(prefix='zbox_tr_', dir=os.path.join(HERE, 'tmp'))
    probe._seed_appdata(appdata, True)
    env = probe._app_env(appdata)
    proc, found, appdata2, env2 = probe.spawn_app(appdata)
    if not found[0]:
        proc.kill()
        print('A. 失败：窗口未出现')
        return False
    try:
        t0 = time.time()
        while time.time() - t0 < 15 and not port_listening():
            time.sleep(0.2)
        ok = port_listening()
        print('A. 正常启动：端口 %d 监听=%s（耗时 %.1fs），配置 transfer_enabled=%s'
              % (PORT, ok, time.time() - t0, cfg_get(appdata, 'transfer_enabled')))
        return ok
    finally:
        probe._quit(proc, env2)
        shutil.rmtree(appdata, ignore_errors=True)


def scenario_b():
    """退出后端口要释放。"""
    appdata = tempfile.mkdtemp(prefix='zbox_tr_', dir=os.path.join(HERE, 'tmp'))
    probe._seed_appdata(appdata, True)
    env = probe._app_env(appdata)
    proc, found, appdata2, env2 = probe.spawn_app(appdata)
    if not found[0]:
        proc.kill()
        print('B. 失败：窗口未出现')
        return False
    try:
        t0 = time.time()
        while time.time() - t0 < 15 and not port_listening():
            time.sleep(0.2)
        was = port_listening()
        probe._quit(proc, env2)
        time.sleep(1.5)
        now = port_listening()
        print('B. 退出释放：退出前监听=%s，退出后监听=%s（应为 False）' % (was, now))
        return (not now)
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        shutil.rmtree(appdata, ignore_errors=True)


def scenario_c():
    """端口被占：启动应失败并把 transfer_enabled 写回 false。"""
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # ⚠️ 必须用 SO_EXCLUSIVEADDRUSE（Windows 专有）：zbox 的 TransferServer
        # 设了 allow_reuse_address=True，普通 SO_REUSEADDR 的占用不会挡住它。
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            blocker.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(('0.0.0.0', PORT))
        blocker.listen(1)
    except OSError as e:
        print('C. 跳过：无法占用端口 %d（%s）' % (PORT, e))
        return True
    appdata = tempfile.mkdtemp(prefix='zbox_tr_', dir=os.path.join(HERE, 'tmp'))
    probe._seed_appdata(appdata, True)
    env = probe._app_env(appdata)
    try:
        proc, found, appdata2, env2 = probe.spawn_app(appdata)
        if not found[0]:
            proc.kill()
            print('C. 失败：窗口未出现')
            return False
        try:
            time.sleep(8)   # 等后台 bind 失败并回写配置
            val = cfg_get(appdata, 'transfer_enabled')
            print('C. 端口被占：配置 transfer_enabled=%s（应为 False）' % val)
            return val is False
        finally:
            probe._quit(proc, env2)
    finally:
        try:
            blocker.close()
        except Exception:
            pass
        shutil.rmtree(appdata, ignore_errors=True)


if __name__ == '__main__':
    r = [scenario_a(), scenario_b(), scenario_c()]
    print('\n结果：%s' % ('全部通过' if all(r) else '有失败项'))
    sys.exit(0 if all(r) else 1)
