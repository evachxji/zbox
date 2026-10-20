# -*- coding: utf-8 -*-
"""本地 OCR 组件运行时：组件按需安装（pip + 国内镜像链）、zbox.exe --ocr-helper 子进程协议。

组件 = 一组 pinned PyPI 包（rapidocr_onnxruntime 的 wheel 自带 PP-OCRv4 三个 ONNX 模型，
onnxruntime 是推理引擎），装到 tools\\ocr\\site-packages\\。全部来自公共免费源
（清华 TUNA → 阿里云 → PyPI 官方），无自建 CDN、无 GitHub、无模型服务器。

- 源码运行：helper = 当前 Python 跑仓库里的 ocr_helper.py
- 冻结 exe：helper = zbox.exe --ocr-helper（main.pyw 早分派，一个 exe 两种身份）；
  pip 由打包时 --collect-submodules pip 带进 exe
- 组件版本：PACKAGES/镜像变了就 bump COMPONENT_VERSION，旧组件标记不符自动重装
"""

import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time

import translation_core
import video_dl

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

COMPONENT_VERSION = 3    # v1 = onefile exe；v2 = site-packages 缺 PyYAML/Pillow/tqdm；v3 补齐

# pip 镜像链：国内公益源优先，PyPI 官方兜底
PIP_MIRRORS = [
    'https://pypi.tuna.tsinghua.edu.cn/simple',
    'https://mirrors.aliyun.com/pypi/simple/',
    'https://pypi.org/simple',
]

# 逐一安装（--no-deps 人工钉全依赖树：rapidocr 声明的是 opencv-python，
# 我们换成 headless 变体，少拉一堆 Qt GUI 库；版本只钉核心两个，其余跟最新兼容版）
PIP_PACKAGES = [
    'six',
    'numpy',
    'pyclipper',
    'shapely',
    'pyyaml',
    'pillow',
    'tqdm',
    'opencv-python-headless',
    'onnxruntime==1.31.0',
    'rapidocr_onnxruntime==1.4.4',
]

OCR_TIMEOUT = 120     # 大图首次推理要加载模型，给足时间


class OcrRuntimeError(RuntimeError):
    """helper 进程非零退出或组件不可用。"""


class OcrTimeout(OcrRuntimeError):
    """OCR 推理超时。"""


class OcrCancelled(OcrRuntimeError):
    """用户取消了本次 OCR。"""


class OcrDownloadError(OcrRuntimeError):
    """组件安装失败（所有镜像都不可用或校验失败）。"""


def supported():
    """ONNX Runtime 方案只支持 x64；x86/arm64 隐藏翻译入口。"""
    return platform.machine().lower() in ('amd64', 'x86_64')


def ocr_dir():
    return os.path.join(video_dl.tools_dir(), 'ocr')


def site_packages_dir():
    return os.path.join(ocr_dir(), 'site-packages')


def ocr_ready():
    """组件就绪 = 版本标记匹配 + site-packages 里核心包都在。"""
    marker = os.path.join(ocr_dir(), 'component.json')
    try:
        with open(marker, 'r', encoding='utf-8') as f:
            if json.load(f).get('version') != COMPONENT_VERSION:
                return False
    except (OSError, ValueError):
        return False
    sp = site_packages_dir()
    return all(os.path.isdir(os.path.join(sp, pkg)) for pkg in
               ('rapidocr_onnxruntime', 'onnxruntime', 'numpy', 'cv2'))


def helper_cmd():
    """OCR helper 子进程命令：冻结 = zbox.exe --ocr-helper；源码 = python ocr_helper.py。"""
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--ocr-helper']
    return [sys.executable,
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ocr_helper.py')]


def stdio_cmd():
    return helper_cmd() + ['--site-packages', site_packages_dir(), '--stdio']


# ---------------- stdio 识别协议 ----------------

def encode_request(png_bytes):
    """4 字节小端 PNG 长度 + PNG 数据（不落地临时文件）。"""
    return struct.pack('<I', len(png_bytes)) + png_bytes


def run_ocr(png_bytes, cmd=None, timeout=OCR_TIMEOUT, scale=1.0, cancel_event=None):
    """跑一遍 OCR：子进程 stdin 喂帧、stdout 收单行 JSON，按协议解析成逻辑像素坐标。
    在调用方的后台线程里阻塞；cancel_event 置位时杀进程抛 OcrCancelled。"""
    if cmd is None:
        if not ocr_ready():
            raise OcrRuntimeError('ocr component not installed')
        cmd = stdio_cmd()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
    result = {}

    def _io():
        try:
            out, err = proc.communicate(input=encode_request(png_bytes))
            result['out'], result['err'] = out, err
        except Exception as e:      # 管道被 kill 打断等
            result['error'] = e

    worker = threading.Thread(target=_io, daemon=True)
    worker.start()
    deadline = time.monotonic() + timeout
    while worker.is_alive():
        if cancel_event is not None and cancel_event.is_set():
            proc.kill()
            raise OcrCancelled()
        if time.monotonic() > deadline:
            proc.kill()
            raise OcrTimeout()
        worker.join(0.05)
    if proc.returncode != 0:
        err = result.get('err', b'')
        if isinstance(err, bytes):
            err = err.decode('utf-8', 'replace')
        raise OcrRuntimeError('ocr helper exited %d: %s' % (proc.returncode, err.strip()))
    return translation_core.parse_ocr_payload(result.get('out', b''), scale=scale)


# ---------------- 组件安装 ----------------

def _install_one(pkg, mirror, target):
    """单包单镜像安装；返回 (成功与否, stderr 摘要)。测试可替换。"""
    cmd = helper_cmd() + ['--install', target, pkg, '--index', mirror]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=CREATE_NO_WINDOW)
    out, err = proc.communicate()
    return proc.returncode == 0, err.decode('utf-8', 'replace')[-400:]


def download_components(progress_cb=None, install_one=None):
    """按镜像链逐包安装到 ocr_dir\\site-packages。任何一包所有镜像都失败 = 整体失败，
    清掉 staging 不留半成品；成功后写版本标记并清理 v1 旧 exe。
    progress_cb(done_packages, total_packages)。"""
    install = install_one or _install_one
    parent = os.path.dirname(ocr_dir())
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix='.ocr_stage_', dir=parent)
    total = len(PIP_PACKAGES)
    try:
        for idx, pkg in enumerate(PIP_PACKAGES):
            last_error = ''
            for mirror in PIP_MIRRORS:
                ok, last_error = install(pkg, mirror, staging)
                if ok:
                    break
            if not ok:
                raise OcrDownloadError('%s install failed: %s' % (pkg, last_error))
            if progress_cb:
                progress_cb(idx + 1, total)
        if os.path.isdir(ocr_dir()):
            shutil.rmtree(ocr_dir())     # 连 v1 旧 exe 一起清掉
        os.makedirs(ocr_dir())
        os.replace(staging, site_packages_dir())
        with open(os.path.join(ocr_dir(), 'component.json'), 'w', encoding='utf-8') as f:
            json.dump({'version': COMPONENT_VERSION}, f)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return ocr_dir()