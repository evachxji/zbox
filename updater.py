# -*- coding: utf-8 -*-
"""应用自身更新：查 GitHub 最新 release、下载 PC 安装包。

纯标准库零 Qt，函数同步阻塞、由调用方放后台线程；progress_cb 也发生在该线程
（与 video_dl._fetch 同约定：(已下载, 总大小)，总大小未知为 0）。
"""
import json
import os
import platform
from urllib.request import Request, urlopen

from version import APP_VERSION, GITHUB_URL
from video_dl import GH_MIRRORS, UA, _fetch, version_key

_API = GITHUB_URL.replace('https://github.com/',
                          'https://api.github.com/repos/') + '/releases/latest'

# 安装包文件名里的架构标识（build.py 命名 zbox-Setup-v<版本>-<架构>.exe）← platform.machine()
_ARCH = {'AMD64': 'x64', 'x86': 'x86', 'ARM64': 'arm64'}


def latest_release():
    """最新 release 的 PC 安装包信息 {'tag', 'name', 'url'}；查询失败或没有安装包资产返回 None。
    GitHub API 直连优先，不通再走加速镜像。"""
    for url in [_API] + [p + _API for p in GH_MIRRORS if p]:
        try:
            req = Request(url, headers=UA)
            with urlopen(req, timeout=10) as r:
                j = json.loads(r.read().decode('utf-8'))
            asset = _pick_setup(j.get('assets') or [])
            if j.get('tag_name') and asset:
                return {'tag': j['tag_name'],
                        'name': asset['name'],
                        'url': asset['browser_download_url']}
        except Exception:
            continue
    return None


def _pick_setup(assets):
    """release 资产里挑 PC 安装包：优先匹配当前架构，没有则取第一个 zbox-Setup-*.exe。"""
    setups = [a for a in assets
              if a.get('name', '').startswith('zbox-Setup-') and a['name'].endswith('.exe')]
    arch = _ARCH.get(platform.machine(), '')
    for a in setups:
        if arch and arch in a['name']:
            return a
    return setups[0] if setups else None


def has_update(tag):
    """release 标签（如 'v0.5'）是否比当前版本新：段数补齐后按数值比（'0.10' > '0.9'）。"""
    cur, new = version_key(APP_VERSION), version_key(tag)
    n = max(len(cur), len(new))
    cur += (0,) * (n - len(cur))
    new += (0,) * (n - len(new))
    return new > cur


def download_setup(rel, dst_dir, progress_cb=None):
    """下载安装包（latest_release 的返回值）到 dst_dir，加速镜像优先、直连兜底；
    成功返回本地路径，全部失败抛最后一个异常。"""
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, rel['name'])
    err = None
    try:
        for prefix in GH_MIRRORS:
            try:
                _fetch(prefix + rel['url'], dst + '.new', progress_cb)
                os.replace(dst + '.new', dst)
                return dst
            except Exception as e:
                err = e
        raise err if err else RuntimeError('安装包下载失败')
    finally:
        try:
            os.remove(dst + '.new')
        except OSError:
            pass
