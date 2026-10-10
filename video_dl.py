# -*- coding: utf-8 -*-
"""视频解析下载的核心逻辑：yt-dlp / ffmpeg 组件的下载更新、版本查询、视频下载子进程。

对照 transfer.py 的分层：纯标准库零 Qt。所有阻塞操作由调用方放后台线程执行，
本模块只通过回调汇报进度（回调发生在后台线程，UI 层须用 Signal 转回主线程再碰控件）。

组件存放位置：优先 zbox 程序所在目录下的 tools\\（frozen 时是 exe 所在目录，
源码运行时是仓库根目录）——不往 C 盘塞依赖；目录不可写（如「此计算机」装到
Program Files 需管理员权限）时回落 %APPDATA%\\zbox\\tools\\。
"""

import gzip
import io
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from urllib.request import Request, urlopen

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) zbox'}   # 部分镜像无 UA 拒访

YTDLP_RELEASE = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe'
# GitHub 加速镜像（国内优先，空串 = GitHub 直连兜底）
GH_MIRRORS = ['https://ghproxy.net/', 'https://gh-proxy.com/', '']

# ffmpeg：npmmirror 的 ffmpeg-static 单文件 gz（国内直连快）→ yt-dlp 官方 FFmpeg-Builds zip（经镜像）
FFMPEG_NPM_GZ = 'https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.1.1/ffmpeg-win32-x64.gz'
FFMPEG_GH_ZIP = 'https://github.com/yt-dlp/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip'

# 清晰度选项：显示名 → 高度上限（照搬参考脚本的 height<= 策略，源没有该档自动落到次佳）
QUALITIES = [('720P', 720), ('1080P', 1080), ('2K', 1440), ('4K', 2160)]

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# yt-dlp.exe 是 PyInstaller 打包程序，stdout 恒走系统 ANSI 代码页（PYTHONIOENCODING 无效，
# 实测），中文 Windows 上是 GBK。不能用 locale.getpreferredencoding()——宿主 Python 若开了
# UTF-8 模式会返回 utf-8 而 yt-dlp 仍吐 GBK；取内核 ACP 才与冻结程序的编码一致
def _console_enc():
    try:
        import ctypes
        return 'cp%d' % ctypes.windll.kernel32.GetACP()
    except Exception:
        return locale.getpreferredencoding(False) or 'utf-8'


LOCALE_ENC = _console_enc()


# ---------------- 组件目录 ----------------

def _writable(d):
    """目录可建可写才算可用（Program Files 安装态无管理员权限写不进去）。"""
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, '.write_test')
        with open(probe, 'w') as f:
            f.write('x')
        os.remove(probe)
        return True
    except OSError:
        return False


def tools_dir():
    """组件目录：程序所在目录\\tools，不可写时回落 %APPDATA%\\zbox\\tools。"""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(base, 'tools')
    if _writable(p):
        return p
    import sysutil
    p = os.path.join(sysutil.appdata_dir(), 'tools')
    os.makedirs(p, exist_ok=True)
    return p


def ytdlp_path():
    return os.path.join(tools_dir(), 'yt-dlp.exe')


def ffmpeg_path():
    return os.path.join(tools_dir(), 'ffmpeg.exe')


def desktop_dir():
    """桌面目录：读 User Shell Folders 注册表（兼容 OneDrive 重定向），兜底 ~/Desktop。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as k:
            v, _ = winreg.QueryValueEx(k, 'Desktop')
            p = os.path.expandvars(v)
            if os.path.isdir(p):
                return p
    except Exception:
        pass
    return os.path.join(os.path.expanduser('~'), 'Desktop')


# ---------------- 浏览器 cookie（抖音等站点需要） ----------------

def cookies_path():
    """用户导入的浏览器 cookie（Netscape 格式），放组件目录；存在即随解析/下载命令带上。"""
    return os.path.join(tools_dir(), 'cookies.txt')


def has_cookies():
    return os.path.isfile(cookies_path())


def _cookie_args():
    return ['--cookies', cookies_path()] if has_cookies() else []


def is_cookie_error(msg):
    """yt-dlp 报「需要 cookie」（抖音等对匿名请求直接 403 的站点）。"""
    return 'cookies' in (msg or '').lower()


def import_cookies(src):
    """把浏览器导出的 cookies.txt 复制进组件目录。返回 (ok, 提示)；
    ok=True 时提示为空串或「没有 douyin.com 条目」的警告（cookie 文件可服务多个站点，
    缺抖音条目不拦着导入）。"""
    try:
        with open(src, 'rb') as f:
            head = f.read(65536)
    except OSError as e:
        return False, '读取文件失败：%s' % e
    text = head.decode('utf-8', 'replace')
    rows = [l for l in text.splitlines() if l.strip() and not l.startswith('#')]
    if not rows or not any('\t' in l for l in rows):
        return False, '文件格式不对：需要 Netscape 格式的 cookies.txt（扩展导出时选 cookies.txt / Netscape 格式）'
    try:
        os.makedirs(tools_dir(), exist_ok=True)
        shutil.copyfile(src, cookies_path())
    except OSError as e:
        return False, '复制失败：%s' % e
    if 'douyin.com' not in text:
        return True, '已导入，但文件里没找到 douyin.com 的 cookie——确认是在抖音页面上导出的吗？'
    return True, ''


def remove_cookies():
    try:
        os.remove(cookies_path())
    except OSError:
        pass


# ---------------- yt-dlp / ffmpeg 组件 ----------------

def _fetch(url, dst, progress_cb=None):
    """流式下载 url 到 dst 文件；progress_cb(已下载, 总大小)，总大小未知时为 0。"""
    req = Request(url, headers=UA)
    with urlopen(req, timeout=30) as r:
        total = int(r.headers.get('Content-Length') or 0)
        done = 0
        with open(dst, 'wb') as f:
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)


def _try_sources(urls, progress_cb=None, what='组件'):
    """多个下载源依次尝试，成功返回完整字节；全部失败抛最后一个异常。"""
    err = None
    tmp = os.path.join(tools_dir(), '.dl_partial')
    try:
        for url in urls:
            try:
                _fetch(url, tmp,
                       lambda d, t: progress_cb and progress_cb(what, d, t))
                with open(tmp, 'rb') as f:
                    return f.read()
            except Exception as e:
                err = e
        raise err if err else RuntimeError('%s 下载失败' % what)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def download_ytdlp(progress_cb=None):
    """下载最新 yt-dlp.exe：GitHub 加速镜像优先、直连兜底。"""
    dst = ytdlp_path()
    err = None
    for prefix in GH_MIRRORS:
        try:
            _fetch(prefix + YTDLP_RELEASE, dst + '.new',
                   lambda d, t: progress_cb and progress_cb('yt-dlp', d, t))
            os.replace(dst + '.new', dst)
            return
        except Exception as e:
            err = e
    raise err if err else RuntimeError('yt-dlp 下载失败')


def _ffmpeg_from_gz(data):
    return gzip.decompress(data)                      # ffmpeg-static 的 gz 解压即是 exe 本体


def _ffmpeg_from_zip(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            if n.endswith('/bin/ffmpeg.exe') or n.endswith('ffmpeg.exe'):
                return z.read(n)
    raise RuntimeError('压缩包里没有 ffmpeg.exe')


def download_ffmpeg(progress_cb=None, ver=None):
    """下载 ffmpeg.exe：npmmirror gz（国内直连，ver 指定版本目录如 '6.1.1'，None 用内置默认）
    → yt-dlp FFmpeg-Builds zip（经 GitHub 镜像）。"""
    npm = ('https://registry.npmmirror.com/-/binary/ffmpeg-static/b%s/ffmpeg-win32-x64.gz'
           % ver) if ver else FFMPEG_NPM_GZ
    data = _try_sources([npm] +
                        [p + FFMPEG_GH_ZIP for p in GH_MIRRORS],
                        progress_cb, 'ffmpeg')
    for extract in (_ffmpeg_from_gz, _ffmpeg_from_zip):
        try:
            exe = extract(data)
            break
        except Exception:
            continue
    else:
        raise RuntimeError('ffmpeg 解压失败')
    dst = ffmpeg_path()
    with open(dst + '.new', 'wb') as f:
        f.write(exe)
    os.replace(dst + '.new', dst)


def tools_ready():
    """两个组件都已在本地（启动时据此判断能否直接恢复功能，避免未经操作就联网下载）。"""
    return os.path.isfile(ytdlp_path()) and os.path.isfile(ffmpeg_path())


def ensure_tools(progress_cb=None):
    """保证 yt-dlp / ffmpeg 就位（缺失才下载）。返回 (ok, err)。"""
    try:
        if not os.path.exists(ytdlp_path()):
            download_ytdlp(progress_cb)
        if not os.path.exists(ffmpeg_path()):
            download_ffmpeg(progress_cb)
        return True, ''
    except Exception as e:
        return False, str(e)


# ---------------- 版本查询 ----------------

def local_version():
    """本地 yt-dlp 版本（`--version` 输出如 2026.8.19）；取不到返回空串。"""
    try:
        r = subprocess.run([ytdlp_path(), '--version'], capture_output=True,
                           text=True, timeout=15, creationflags=CREATE_NO_WINDOW)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def version_key(v):
    """版本字符串转数值元组供比较：'2026.08.19' 与 '2026.8.19' 视为同一版本；
    ffmpeg 的 '6.1.1-essentials_build-...' 取前导数字段。"""
    try:
        return tuple(int(p) for p in re.findall(r'\d+', str(v))[:4])
    except (TypeError, ValueError):
        return ()


def latest_version():
    """最新 yt-dlp 版本：pypi JSON → GitHub API 兜底；都失败返回 None。"""
    for url in ('https://pypi.org/pypi/yt-dlp/json',
                'https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest'):
        try:
            req = Request(url, headers=UA)
            with urlopen(req, timeout=10) as r:
                j = json.loads(r.read().decode('utf-8'))
            v = j.get('info', {}).get('version') or j.get('tag_name', '')
            if v:
                return v
        except Exception:
            continue
    return None


def latest_ffmpeg_version():
    """npmmirror ffmpeg-static 目录里最新的版本号（如 '6.1.1'）；查询失败返回 None。"""
    try:
        req = Request('https://registry.npmmirror.com/-/binary/ffmpeg-static/', headers=UA)
        with urlopen(req, timeout=10) as r:
            j = json.loads(r.read().decode('utf-8'))
        vers = [e['name'].rstrip('/') for e in j
                if e.get('type') == 'dir' and re.match(r'^b[\d.]+/?$', e.get('name', ''))]
        vers = [v.lstrip('b') for v in vers]
        if vers:
            return max(vers, key=version_key)
    except Exception:
        pass
    return None


def ffmpeg_version():
    """本地 ffmpeg 版本（`-version` 首行 'ffmpeg version N.N.N-...'）；取不到返回空串。"""
    try:
        r = subprocess.run([ffmpeg_path(), '-version'], capture_output=True,
                           timeout=15, creationflags=CREATE_NO_WINDOW)
        if r.returncode == 0:
            first = r.stdout.decode(LOCALE_ENC, 'replace').splitlines()[0]
            m = re.search(r'version\s+(\S+)', first)
            return m.group(1) if m else ''
    except Exception:
        pass
    return ''


def uninstall_tools():
    """卸载组件：删除 yt-dlp.exe / ffmpeg.exe 及半截下载残留；tools 目录空了顺带删掉。"""
    d = tools_dir()
    for name in ('yt-dlp.exe', 'ffmpeg.exe', 'cookies.txt'):
        for suffix in ('', '.new', '.part'):
            p = os.path.join(d, name + suffix)
            if os.path.exists(p):
                os.remove(p)
    try:
        os.rmdir(d)   # 只在空目录时成功
    except OSError:
        pass


def parse_video(url, timeout=60):
    """解析视频信息（-J 全量 JSON）：返回 {'title', 'duration', 'heights'}，
    heights 为源视频实际提供的分辨率高度降序（最多 8 档）；失败抛带可读信息的异常。"""
    r = subprocess.run([ytdlp_path(), '-J', '--no-playlist', '--no-color',
                        '--encoding', 'utf-8']
                       + _cookie_args() + [url],
                       capture_output=True, timeout=timeout,
                       creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        text = r.stderr.decode('utf-8', 'replace') + r.stdout.decode('utf-8', 'replace')
        lines = [l.replace('ERROR:', '').strip() for l in text.splitlines() if 'ERROR' in l]
        raise RuntimeError(lines[-1][:120] if lines else '解析失败（退出码 %d）' % r.returncode)
    j = json.loads(r.stdout.decode('utf-8', 'replace'))
    fmts = j.get('formats', [])
    heights = sorted({f['height'] for f in fmts
                      if f.get('height') and f.get('vcodec') != 'none'},
                     reverse=True)
    # 分流判定：该高度有纯视频流（acodec=none），且整站有纯音频流可配
    has_audio_only = any(f.get('acodec') != 'none' and f.get('vcodec') in (None, 'none')
                         for f in fmts)
    split_heights = sorted({f['height'] for f in fmts
                            if f.get('height') and f.get('vcodec') != 'none'
                            and f.get('acodec') == 'none'},
                           reverse=True) if has_audio_only else []
    return {'title': j.get('title') or '',
            'duration': j.get('duration') or 0,
            'heights': heights[:8],
            'split_heights': split_heights,
            'thumbnail': j.get('thumbnail') or ''}


# ---------------- 视频下载 ----------------

_PROGRESS_RE = re.compile(
    r'\[download\]\s+([\d.]+)%(?:\s+of\s+~?(\S+))?.*?at\s+(\S+)(?:\s+ETA\s+(\S+))?')
_MERGE_RE = re.compile(r'\[Merger\] Merging formats into "(.+?)"')
_DEST_RE = re.compile(r'\[download\] Destination: (.+)$')


def download_cmd(url, height, out_dir):
    """照搬参考脚本的参数：bestvideo[height<=N]+bestaudio 合并 mp4，
    补 --ffmpeg-location / -P / --newline（逐行进度便于解析，映射成单趟：下载 0→95%、合并 95→100）/ --no-color。
    height=None 为「自动」档：bestvideo+bestaudio 不限高度。"""
    # fmt 见下方：/best 兜底合流源
    # /best 兜底：合流单文件平台（直链 mp4 等）没有分离流，不兜底会直接报格式不可用
    fmt = ('bestvideo[height<=%d]+bestaudio/best' % height) if height else 'bestvideo+bestaudio/best'
    return [ytdlp_path(),
            '-f', fmt,
            '--merge-output-format', 'mp4',
            '--ffmpeg-location', tools_dir(),
            '-P', out_dir,
            '--encoding', 'utf-8',   # 强制 UTF-8 输出：文件名含 emoji 时 cp936 会丢字符
            '--newline', '--no-color'] + _cookie_args() + [url]


class Download(object):
    """一次视频下载：start() 在当前线程阻塞执行，terminate() 可随时中止。
    同名成品已存在时 yt-dlp 会直接跳过（rc=0 但什么都没下），检测到跳过后
    自动给文件名追加「-2160P」式分辨率后缀重试一次；后缀名也撞车才报「未重复下载」。"""

    def __init__(self, url, height, out_dir, split=True):
        self.cmd = download_cmd(url, height, out_dir)
        self._height = height
        self._split = split   # 音视频分流下载（三段）；合流单文件一段到底
        self._out_dir = out_dir
        self._proc = None
        self._terminated = False
        self._paused = False              # 暂停中（进程已杀、.part 保留，等「继续」）
        self._resume_evt = threading.Event()

    def _cleanup_parts(self, dests):
        """失败/中止时清掉本次下载的中间文件（视频/音频流本体及 .part / .ytdl 边车文件）。
        只动本次会话亲眼看到的 Destination 路径；成功的完整 mp4 不在其列。"""
        for p in dests:
            if not os.path.isabs(p):
                p = os.path.join(self._out_dir, p)
            for suffix in ('', '.part', '.ytdl'):
                try:
                    os.remove(p + suffix)
                except OSError:
                    pass

    def _run_once(self, progress_cb, dests):
        """执行一次下载进程。返回 (退出码, 输出文件, 是否因同名被跳过, 错误行)。"""
        outfile = ''
        skipped = False
        err_lines = []
        stream_idx = 0      # 第几路流：1=视频 2=音频（bestvideo+bestaudio 先视频后音频）
        stage = ''          # 当前阶段名，前缀进进度文案
        self._proc = subprocess.Popen(
            self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',   # 与 --encoding utf-8 配对
            creationflags=CREATE_NO_WINDOW)
        for line in self._proc.stdout:
            line = line.strip()
            m = _PROGRESS_RE.search(line)
            if m:
                raw = float(m.group(1))
                # 进度条单趟走完：下载段 0→95%（分流源 视频 0–85 / 音频 85–95），
                # 95→100 留给合并（done 时置 100）——不再每路流各走一遍
                if self._split:
                    pct = raw * 0.85 if stream_idx <= 1 else 85.0 + raw * 0.10
                else:
                    pct = raw * 0.95
                detail = '%.1f%% · %s' % (raw, m.group(3))
                if m.group(4):
                    detail += ' · 剩 ' + m.group(4)
                if stage:
                    detail = '%s · %s' % (stage, detail)
                progress_cb(min(pct, 95.0), detail, m.group(2) or '',
                            m.group(3) or '', m.group(4) or '')
                continue
            m = _DEST_RE.search(line)
            if m:
                stream_idx += 1
                if self._split:
                    stage = '(1/3) 下载视频' if stream_idx == 1 else '(2/3) 下载音频'
                outfile = m.group(1)
                dests.append(m.group(1))
            else:
                m = _MERGE_RE.search(line)
                if m:
                    outfile = m.group(1)
                    stage = ''
                    # pct=None + 非空文案 = 阶段提示（合并只在分流时发生）
                    progress_cb(None, '(3/3) 合并中…' if self._split else '合并中…')
            if 'has already been downloaded' in line:
                skipped = True
            if 'ERROR' in line:
                err_lines.append(line)
        rc = self._proc.wait()
        self._proc = None
        return rc, outfile, skipped, err_lines

    def start(self, progress_cb, done_cb):
        """progress_cb(percent_or_None, detail)；done_cb(ok, 文件名或错误摘要)。"""
        rc, outfile, err_lines, dests = 1, '', [], []
        retried = False
        try:
            while True:
                rc, outfile, skipped, err_lines = self._run_once(progress_cb, dests)
                if self._terminated:
                    break
                if self._paused:
                    # 暂停：进程已杀但 .part 中间文件保留；「继续」后同一条命令
                    # 重跑，yt-dlp 默认 --continue 会从 .part 断点续传
                    self._paused = False
                    self._resume_evt.wait()
                    self._resume_evt.clear()
                    if self._terminated:
                        break
                    continue
                if rc == 0 and skipped and not retried:
                    retried = True
                    suffix = '-%dP' % self._height if self._height else '-auto'
                    self.cmd = (self.cmd[:-1] +
                                ['-o', '%%(title)s [%%(id)s]%s.%%(ext)s' % suffix,
                                 self.cmd[-1]])
                    progress_cb(None, '检测到同名文件，以 %s 后缀重新下载' % suffix)
                    continue
                break
        except Exception as e:
            self._proc = None
            self._cleanup_parts(dests)
            done_cb(False, str(e))
            return
        if rc == 0:
            if outfile:
                done_cb(True, outfile)   # 完整路径（抓不到输出名时为空串）
            else:
                done_cb(False, '同名文件已存在（含分辨率后缀），未重复下载')
        else:
            self._cleanup_parts(dests)
            tail = err_lines[-1] if err_lines else 'yt-dlp 退出码 %d' % rc
            done_cb(False, tail.replace('ERROR:', '').strip())

    def pause(self):
        """暂停：杀掉下载进程树但保留 .part 中间文件，resume() 后自动断点续传。"""
        if self._terminated or self._paused:
            return
        self._paused = True
        self._kill_tree()

    def resume(self):
        """继续：唤醒 start() 里挂起的下载线程，同一条命令重跑（续传 .part）。"""
        self._resume_evt.set()

    def terminate(self):
        self._terminated = True
        self._resume_evt.set()   # 暂停中等「继续」的线程也要唤醒走取消收尾
        self._kill_tree()

    def _kill_tree(self):
        p = self._proc
        if p is not None:
            # yt-dlp.exe 是 PyInstaller 双进程结构（引导器 + 真正的下载子进程），
            # 只 terminate 父进程会让子进程带着 stdout 管道继续跑（点了取消却还在下载），
            # 必须 taskkill /T 整棵树
            try:
                subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'],
                               capture_output=True, timeout=10,
                               creationflags=CREATE_NO_WINDOW)
            except Exception:
                try:
                    p.terminate()
                except Exception:
                    pass
