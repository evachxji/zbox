# -*- coding: utf-8 -*-
"""zbox 性能基线探针（零侵入，不改业务代码）。

在真实 Windows 环境下测量：
  * 冷/热启动耗时：进程创建 → 主面板窗口首次可见且消息循环可响应（WM_NULL 往返）
  * 内存占用：工作集（Working Set）、私有内存（Private Usage）
  * CPU 占用：内核态+用户态累计时间，按采样窗口折算成「单核百分比」
  * 资源计数：句柄数、线程数、GDI/USER 对象数（Win32 资源泄漏的经典指标）
  * 长跑内存曲线：验证是否存在持续增长（泄漏）
  * import 开销分解（-X importtime）

用法见同目录 README.md。

依赖：仅标准库（ctypes 直调 Win32），不引入 psutil。
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.dirname(os.path.abspath(__file__))

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

WM_NULL = 0x0000
SMTO_ABORTIFHUNG = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
TH32CS_SNAPTHREAD = 0x00000004
INVALID_HANDLE_VALUE = -1


# ---------------------------------------------------------------- 进程指标

class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ('cb', wt.DWORD),
        ('PageFaultCount', wt.DWORD),
        ('PeakWorkingSetSize', ctypes.c_size_t),
        ('WorkingSetSize', ctypes.c_size_t),
        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
        ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
        ('PagefileUsage', ctypes.c_size_t),
        ('PeakPagefileUsage', ctypes.c_size_t),
        ('PrivateUsage', ctypes.c_size_t),
    ]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ('dwSize', wt.DWORD),
        ('cntUsage', wt.DWORD),
        ('th32ThreadID', wt.DWORD),
        ('th32OwnerProcessID', wt.DWORD),
        ('tpBasePri', ctypes.c_long),
        ('tpDeltaPri', ctypes.c_long),
        ('dwFlags', wt.DWORD),
    ]


def proc_handle(pid):
    return kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)


def mem_info(pid):
    """返回 (工作集, 私有内存, 峰值工作集) 字节。"""
    h = proc_handle(pid)
    if not h:
        return None
    try:
        c = PROCESS_MEMORY_COUNTERS_EX()
        c.cb = ctypes.sizeof(c)
        if not psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
            return None
        return (c.WorkingSetSize, c.PrivateUsage, c.PeakWorkingSetSize)
    finally:
        kernel32.CloseHandle(h)


def cpu_times(pid):
    """返回 (内核态秒, 用户态秒, 进程创建墙钟秒)。"""
    h = proc_handle(pid)
    if not h:
        return None
    try:
        c, e, k, u = (wt.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                                        ctypes.byref(k), ctypes.byref(u)):
            return None

        def to_sec(ft):
            return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7
        return (to_sec(k), to_sec(u), to_sec(c))
    finally:
        kernel32.CloseHandle(h)


def handle_count(pid):
    h = proc_handle(pid)
    if not h:
        return None
    try:
        n = wt.DWORD()
        if not kernel32.GetProcessHandleCount(h, ctypes.byref(n)):
            return None
        return n.value
    finally:
        kernel32.CloseHandle(h)


def thread_count(pid):
    """用 toolhelp32 快照数线程。"""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == INVALID_HANDLE_VALUE:
        return None
    try:
        te = THREADENTRY32()
        te.dwSize = ctypes.sizeof(te)
        n = 0
        if kernel32.Thread32First(snap, ctypes.byref(te)):
            while True:
                if te.th32OwnerProcessID == pid:
                    n += 1
                if not kernel32.Thread32Next(snap, ctypes.byref(te)):
                    break
        return n
    finally:
        kernel32.CloseHandle(snap)


def gui_object_counts(pid):
    """GDI / USER 对象数（Win32 资源泄漏的经典指标）。

    GetGuiResources 导出在 **user32.dll**（psapi 里没有这个符号）。
    """
    h = proc_handle(pid)
    if not h:
        return None, None
    try:
        gdi = wt.DWORD()
        usr = wt.DWORD()
        ok1 = user32.GetGuiResources(h, 0, ctypes.byref(gdi))
        ok2 = user32.GetGuiResources(h, 1, ctypes.byref(usr))
        if not (ok1 and ok2):
            return None, None
        return gdi.value, usr.value
    finally:
        kernel32.CloseHandle(h)


# ---------------------------------------------------------------- 窗口查找

def _pid_of(hwnd):
    p = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def _class_of(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _desktop_band_roots():
    """桌面带根窗口：Progman + 所有 WorkerW。

    面板挂带（pin_to_desktop）后是桌面带的 child，**不是本进程顶层窗口**，
    EnumWindows 枚举不到 —— 必须从带根往下找。
    """
    roots = []
    h = user32.FindWindowW('Progman', None)
    if h:
        roots.append(h)

    @WNDENUMPROC
    def cb(hwnd, _):
        if _class_of(hwnd) == 'WorkerW':
            roots.append(hwnd)
        return True
    user32.EnumWindows(cb, 0)
    return roots


def find_pid_windows(pid):
    """列出属于该 PID 的全部窗口。

    两条路径都要走：
      ① 本进程顶层窗口（设置窗、关于窗等未挂带的窗口）
      ② 桌面带（Progman/WorkerW）下的 child —— 面板与格子挂带后在这里
    """
    found = []
    seen = set()

    def add(h):
        if h not in seen and _pid_of(h) == pid:
            seen.add(h)
            found.append(h)

    @WNDENUMPROC
    def cb(hwnd, _):
        add(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    # 顶层窗口的 child
    for h in list(found):
        @WNDENUMPROC
        def cb2(hwnd, _):
            add(hwnd)
            return True
        user32.EnumChildWindows(h, cb2, 0)
    # 桌面带下的 child（挂带后的面板 / 格子在这里）
    for root in _desktop_band_roots():
        @WNDENUMPROC
        def cb3(hwnd, _):
            add(hwnd)
            return True
        user32.EnumChildWindows(root, cb3, 0)
    return found


def window_info(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, 256)
    return {
        'hwnd': hwnd,
        'visible': bool(user32.IsWindowVisible(hwnd)),
        'class': buf.value,
        'title': title.value,
        'rect': (r.left, r.top, r.right, r.bottom),
        'w': r.right - r.left,
        'h': r.bottom - r.top,
    }


def window_responds(hwnd, timeout_ms=3000):
    """向窗口发 WM_NULL 并等它被 GUI 线程处理 —— 处理了就说明事件循环在跑 = 可交互。"""
    res = ctypes.c_ulong()
    rc = user32.SendMessageTimeoutW(hwnd, WM_NULL, 0, 0,
                                     SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(res))
    return rc != 0


def find_main_window(pid, deadline, verbose=False):
    """返回 (hwnd, t_visible, t_responsive)；超时返回 (None, None, None)。

    主面板判定：visible + 有尺寸，优先取标题为 'zbox' 的（面板与格子的窗口标题
    都叫 'zbox'），同标题按面积最大者胜出；否则退化为面积最大的 visible 窗口。
    """
    t_visible = None
    last = []
    while time.perf_counter() < deadline:
        wins = find_pid_windows(pid)
        last = [window_info(h) for h in wins]
        cands = [w for w in last if w['visible'] and w['w'] > 0 and w['h'] > 0]
        if cands:
            named = [w for w in cands if w['title'] == 'zbox']
            best = max(named or cands, key=lambda w: w['w'] * w['h'])
            if t_visible is None:
                t_visible = time.perf_counter()
            if window_responds(best['hwnd']):
                return best['hwnd'], t_visible, time.perf_counter()
        time.sleep(0.005)
    if verbose:
        print('--- 窗口快照 ---')
        for w in last:
            print(w)
    return None, None, None


# ---------------------------------------------------------------- 实例探测

def instance_running():
    """主实例的 IPC named pipe 存在 = 已有实例在跑（会干扰启动测量）。"""
    try:
        with open('\\\\.\\pipe\\zbox-panel-v1', 'rb', buffering=0):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------- 环境

def site_packages_paths():
    """当前解释器的 site-packages 列表（改 APPDATA 后要靠 PYTHONPATH 补回来）。"""
    out = []
    for p in sys.path:
        if 'site-packages' in p or ('packages' in p and 'dist-packages' in p):
            out.append(p)
    return out


def _app_env(appdata, extra_path=None):
    env = dict(os.environ)
    env['APPDATA'] = appdata
    env.pop('ZBOX_SHOT', None)
    env.pop('ZBOX_GRABSCREEN', None)
    env['ZBOX_DEBUG'] = '1'
    # ⚠️ 改 APPDATA 会连带屏蔽 %APPDATA%\Python\...\site-packages（PySide6 在那儿），
    # 因此把原 site-packages 显式塞进 PYTHONPATH。
    pp = list(site_packages_paths())
    if extra_path:
        pp.append(extra_path)
    if pp:
        env['PYTHONPATH'] = os.pathsep.join(pp)
    return env


def pythonw_path():
    p = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    return p if os.path.exists(p) else sys.executable


# ---------------------------------------------------------------- 启动测量

def _seed_appdata(dst, copy_real=True):
    """准备一份隔离的 APPDATA。

    copy_real=True：把用户真实的 %APPDATA%\\zbox 复制一份过去 —— 这样既有同样的
    盒子/待办/配置（启动路径与真实使用一致），又不会写坏用户数据、不会动用户桌面图标。
    copy_real=False：空目录，模拟「首次安装」。
    """
    os.makedirs(dst, exist_ok=True)
    if not copy_real:
        return
    src = os.path.join(os.environ.get('APPDATA', ''), 'zbox')
    if not os.path.isdir(src):
        return
    zbox_dst = os.path.join(dst, 'zbox')
    os.makedirs(zbox_dst, exist_ok=True)
    skip_dirs = {'doubao_profile', 'QtWebEngine'}   # Chromium profile：体积大且带锁
    for name in os.listdir(src):
        if name.endswith('.log'):
            continue
        s = os.path.join(src, name)
        d = os.path.join(zbox_dst, name)
        try:
            if os.path.isdir(s):
                if name in skip_dirs:
                    continue
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
        except OSError:
            pass


def measure_startup(runs=5, copy_real=True):
    """启动耗时基准：跑 stage_probe.py（进程内插桩），取「事件循环首拍（可交互）」。

    为什么不用外部窗口探测：面板挂到桌面带后是 Progman 的 child，且格子窗口与
    面板同名同标题（'zbox'），外部探测会误认格子窗口、测出偏小的数。
    进程内插桩能精确区分「面板构造完」「首帧显示」「事件循环首拍」。
    """
    pythonw = pythonw_path()
    stage = os.path.join(WORK, 'stage_probe.py')
    results = []
    appdata = tempfile.mkdtemp(prefix='zbox_perf_', dir=os.path.join(WORK, 'tmp'))
    try:
        for i in range(runs):
            shutil.rmtree(appdata, ignore_errors=True)
            _seed_appdata(appdata, copy_real)
            env = _app_env(appdata)
            out_json = os.path.join(appdata, 'stage.json')
            try:
                subprocess.run([pythonw, stage, '--out', out_json], cwd=REPO, env=env,
                               timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                results.append({'run': i + 1, 'error': 'stage_probe 失败: %s' % e})
                continue
            if not os.path.exists(out_json):
                results.append({'run': i + 1, 'error': 'stage_probe 未产出结果'})
                continue
            with open(out_json, encoding='utf-8') as f:
                data = json.load(f)
            marks = {m['stage']: m['ms'] for m in data.get('marks', [])}
            row = {'run': i + 1}
            for key, name in (('import', 'import main 完成'),
                              ('qapp', 'QApplication() 后'),
                              ('panel_ctor', 'FloatingPanel() 后'),
                              ('boxmgr', 'BoxManager() 后'),
                              ('shown', 'panel.show() 后'),
                              ('interactive', '事件循环首拍（可交互）')):
                if name in marks:
                    row[key + '_ms'] = marks[name]
            if '面板已可见=True' in marks:
                row['panel_visible'] = True
            row.update({k: v for k, v in data.items() if k.endswith('_mb')})
            results.append(row)
    finally:
        shutil.rmtree(appdata, ignore_errors=True)
    return results


def _quit(proc, env=None):
    """正常退出（走 aboutToQuit 清理：还原桌面图标 / 右键菜单形态）。"""
    try:
        subprocess.run([sys.executable, 'main.pyw', '--quit'], cwd=REPO, env=env or dict(os.environ),
                       timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    try:
        proc.wait(timeout=15)
    except Exception:
        proc.kill()


# ---------------------------------------------------------------- 常驻测量

def spawn_app(appdata=None, copy_real=True):
    pythonw = pythonw_path()
    appdata = appdata or tempfile.mkdtemp(prefix='zbox_perf_', dir=os.path.join(WORK, 'tmp'))
    _seed_appdata(appdata, copy_real)
    env = _app_env(appdata)
    t0 = time.perf_counter()
    proc = subprocess.Popen([pythonw, 'main.pyw'], cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    hwnd, t_vis, t_resp = find_main_window(proc.pid, t0 + 60)
    return proc, (hwnd, t_vis, t_resp), appdata, env


def measure_idle(seconds=30):
    proc, found, appdata, env = spawn_app()
    if not found[0]:
        proc.kill()
        return {'error': '窗口未出现'}
    try:
        time.sleep(3)   # 前 3 秒是启动余热，之后才是稳态空闲
        t_cpu0 = cpu_times(proc.pid)
        t_wall0 = time.perf_counter()
        time.sleep(seconds)
        ct = cpu_times(proc.pid)
        d_cpu = (ct[0] - t_cpu0[0]) + (ct[1] - t_cpu0[1])
        d_wall = time.perf_counter() - t_wall0
        mi = mem_info(proc.pid)
        gdi, usr = gui_object_counts(proc.pid)
        return {
            'idle_seconds': seconds,
            'cpu_pct_1core': round(d_cpu / d_wall * 100, 3),
            'cpu_total_s': round(d_cpu, 3),
            'working_set_mb': round(mi[0] / 1048576, 2),
            'private_mb': round(mi[1] / 1048576, 2),
            'peak_ws_mb': round(mi[2] / 1048576, 2),
            'handles': handle_count(proc.pid),
            'threads': thread_count(proc.pid),
            'gdi': gdi,
            'user': usr,
        }
    finally:
        _quit(proc, env)
        shutil.rmtree(appdata, ignore_errors=True)


def measure_longrun(seconds=600, interval=10):
    proc, found, appdata, env = spawn_app()
    if not found[0]:
        proc.kill()
        return {'error': '窗口未出现'}
    samples = []
    try:
        t_cpu0 = cpu_times(proc.pid)
        t_wall0 = time.perf_counter()
        deadline = t_wall0 + seconds
        while time.perf_counter() < deadline:
            time.sleep(interval)
            now = time.perf_counter()
            mi = mem_info(proc.pid)
            ct = cpu_times(proc.pid)
            if not mi or not ct:
                continue
            gdi, usr = gui_object_counts(proc.pid)
            d_cpu = (ct[0] - t_cpu0[0]) + (ct[1] - t_cpu0[1])
            samples.append({
                't_s': round(now - t_wall0, 1),
                'ws_mb': round(mi[0] / 1048576, 2),
                'priv_mb': round(mi[1] / 1048576, 2),
                'cpu_pct_1core': round(d_cpu / (now - t_wall0) * 100, 2),
                'handles': handle_count(proc.pid),
                'threads': thread_count(proc.pid),
                'gdi': gdi,
                'user': usr,
            })
        ws = [s['ws_mb'] for s in samples]
        priv = [s['priv_mb'] for s in samples]
        hd = [s['handles'] for s in samples]
        gd = [s['gdi'] for s in samples]
        us = [s['user'] for s in samples]
        half = max(1, len(samples) // 2)
        return {
            'samples': samples,
            'ws_first_half_avg': round(statistics.mean(ws[:half]), 2),
            'ws_second_half_avg': round(statistics.mean(ws[half:]), 2),
            'ws_growth_mb': round(statistics.mean(ws[half:]) - statistics.mean(ws[:half]), 2),
            'priv_first_half_avg': round(statistics.mean(priv[:half]), 2),
            'priv_second_half_avg': round(statistics.mean(priv[half:]), 2),
            'priv_growth_mb': round(statistics.mean(priv[half:]) - statistics.mean(priv[:half]), 2),
            'handles_delta': (hd[-1] - hd[0]) if hd else None,
            'gdi_delta': (gd[-1] - gd[0]) if gd else None,
            'user_delta': (us[-1] - us[0]) if us else None,
        }
    finally:
        _quit(proc, env)
        shutil.rmtree(appdata, ignore_errors=True)


def measure_imports():
    """import 开销分解：-X importtime 跑一次模块导入，按累计耗时排序。"""
    appdata = tempfile.mkdtemp(prefix='zbox_perf_', dir=os.path.join(WORK, 'tmp'))
    try:
        env = _app_env(appdata)
        p = subprocess.run([sys.executable, '-X', 'importtime', '-c',
                            'import main'],
                           cwd=REPO, env=env, capture_output=True, text=True, timeout=120)
        rows = []
        for line in p.stderr.splitlines():
            if not line.startswith('import time:'):
                continue
            parts = line.split('|')
            if len(parts) < 3:
                continue
            try:
                self_us = int(parts[0].split(':')[1].strip())
                cum_us = int(parts[1].strip())
            except ValueError:
                continue
            name = parts[2].strip()
            rows.append({'module': name, 'self_ms': round(self_us / 1000, 2),
                         'cum_ms': round(cum_us / 1000, 2)})
        rows.sort(key=lambda r: -r['cum_ms'])
        total = sum(r['self_ms'] for r in rows)
        return {'total_self_ms': round(total, 2),
                'top_cum': rows[:30],
                'top_self': sorted(rows, key=lambda r: -r['self_ms'])[:20]}
    finally:
        shutil.rmtree(appdata, ignore_errors=True)


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(description='zbox 性能基线探针')
    ap.add_argument('mode', choices=['startup', 'idle', 'longrun', 'imports', 'info', 'all'])
    ap.add_argument('--runs', type=int, default=5)
    ap.add_argument('--seconds', type=float, default=30)
    ap.add_argument('--interval', type=float, default=10)
    ap.add_argument('--out', default=None, help='结果 JSON 保存路径')
    args = ap.parse_args()

    os.makedirs(os.path.join(WORK, 'tmp'), exist_ok=True)

    if args.mode == 'info':
        out = {'instance_running': instance_running(),
               'python': sys.version.split()[0],
               'pythonw': pythonw_path()}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if instance_running():
        print('!! 已有 zbox 实例在运行，测量会失真（新的启动会被 IPC 转发后立即退出）。')
        print('   请先退出面板（桌面右键 → 退出），再重跑。')
        return 2

    out = {}
    if args.mode in ('startup', 'all'):
        out['startup'] = measure_startup(args.runs)
    if args.mode in ('idle', 'all'):
        out['idle'] = measure_idle(int(args.seconds))
    if args.mode in ('longrun', 'all'):
        out['longrun'] = measure_longrun(int(args.seconds), args.interval)
    if args.mode in ('imports', 'all'):
        out['imports'] = measure_imports()

    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(text)
        print('\n[saved] %s' % args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
