# -*- coding: utf-8 -*-
"""OCR helper：截图翻译的识别/安装子进程入口（RapidOCR/PP-OCRv4，纯本地）。

两种用法（ocr_runtime.helper_cmd 统一拼装）：
- 源码：python ocr_helper.py --site-packages <dir> --stdio / --install <dir> <pkg> --index <mirror>
- 冻结：zbox.exe --ocr-helper --site-packages ... / --install ...（main.pyw 早分派，
  pip 随 --collect-submodules pip 打进 exe）

识别协议（与 ocr_runtime 约定）：stdin 收「4 字节小端 PNG 长度 + PNG 数据」，
stdout 回单行 JSON {version, regions[]}，识别一次即退出不常驻。
安装模式：单包单镜像 pip install --target（--no-deps，依赖树由 ocr_runtime.PIP_PACKAGES 钉死）。
"""
import json
import struct
import sys


# ---------------- mini wheel 安装器（纯标准库，冻结环境没有可用 pip，distlib 会炸） ----------------

import hashlib
import os
import re
import zipfile
from urllib.request import Request, urlopen

_UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) zbox'}
_PY_MAJOR = sys.version_info[0]
_PY_MINOR = sys.version_info[1]


class InstallError(RuntimeError):
    """镜像上没有兼容 wheel / 下载或校验失败。"""


def _version_key(text):
    """数字段元组比较（4.10.0.84 > 4.9.0.80）；非数字段按字典序排在后。"""
    parts = re.split(r'[.\-+]', text)
    key = []
    for p in parts:
        key.append((0, int(p)) if p.isdigit() else (1, p))
    return key


def _wheel_compatible(filename):
    """wheel 文件名与当前解释器（CPython x64）兼容吗：
    纯 py3-none-any 直接收；二进制要求 win_amd64 + cpXY 匹配或 abi3。"""
    if not filename.endswith('.whl'):
        return False
    stem = filename[:-4]
    tags = stem.split('-')
    if len(tags) < 3:
        return False
    py_tag, abi_tag, plat_tag = tags[-3], tags[-2], tags[-1]
    if plat_tag not in ('any', 'win_amd64'):
        return False
    if plat_tag == 'any':
        return py_tag in ('py3', 'py2.py3') and abi_tag == 'none'
    if abi_tag == 'abi3':
        m = re.match(r'cp3(\d+)$', py_tag)
        return m is not None and int(m.group(1)) <= _PY_MINOR
    return py_tag == 'cp%d%d' % (_PY_MAJOR, _PY_MINOR) and abi_tag == py_tag


_STABLE_VERSION = re.compile(r'^\d+(\.\d+)*$')


def pick_wheel(index_html, name, pin, base_url=''):
    """从 PEP 503 simple 索引页选最兼容的 wheel：返回 (url, sha256|None, version)。
    只收稳定版（跳过 rc/a/b/dev 预发布）；相对 href 用 base_url 拼绝对（实测清华镜像
    全是相对链接）。"""
    from urllib.parse import urljoin
    dist = name.lower().replace('-', '_')
    best = None
    for m in re.finditer(r'href="([^"]+?\.whl)(#[^"]*)?"[^>]*>([^<]+)<', index_html):
        href, frag, text = m.group(1), m.group(2) or '', m.group(3).strip()
        filename = text if text.endswith('.whl') else href.rsplit('/', 1)[-1]
        if not filename.startswith(dist + '-') or not _wheel_compatible(filename):
            continue
        version = filename[len(dist) + 1:].split('-')[0]
        if not _STABLE_VERSION.match(version):
            continue
        if pin and version != pin:
            continue
        sha = None
        hm = re.search(r'#sha256=([0-9a-fA-F]{64})', frag)
        if hm:
            sha = hm.group(1).lower()
        cand = (_version_key(version), href, sha, version)
        if best is None or cand[0] > best[0]:
            best = cand
    if best is None:
        raise InstallError('no compatible wheel for %s%s'
                           % (name, '==%s' % pin if pin else ''))
    _key, url, sha, version = best
    return urljoin(base_url, url) if base_url else url, sha, version


def install(target_dir, pkg, index_url):
    """单包安装到 target_dir：选 wheel → 下载（校验 sha256）→ 解压。返回 0/非 0。"""
    name, _, pin = pkg.partition('==')
    try:
        index = index_url.rstrip('/') + '/' + name.lower().replace('_', '-') + '/'
        req = Request(index, headers=_UA)
        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', 'replace')
        url, sha, _version = pick_wheel(html, name, pin or None, base_url=index)
        req = Request(url, headers=_UA)
        with urlopen(req, timeout=120) as resp:
            blob = resp.read()
        if sha and hashlib.sha256(blob).hexdigest() != sha:
            raise InstallError('sha256 mismatch for %s' % name)
        os.makedirs(target_dir, exist_ok=True)
        import io
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            z.extractall(target_dir)
        return 0
    except Exception as e:
        sys.stderr.write('install %s failed: %s\n' % (pkg, e))
        return 1


def run_stdio(site_packages):
    if site_packages:
        sys.path.insert(0, site_packages)
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return 2
    (size,) = struct.unpack('<I', raw)
    png = sys.stdin.buffer.read(size)
    if len(png) < size:
        return 2
    try:
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        result, _elapse = engine(png)
    except Exception as e:
        sys.stderr.write('ocr failed: %s' % e)
        return 1
    regions = []
    for box, text, conf in (result or []):
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        regions.append({
            'text': text,
            'confidence': float(conf),
            'quad': [[x, y] for x, y in zip(xs, ys)],
            'bbox': [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)],
        })
    out = json.dumps({'version': 1, 'regions': regions}, ensure_ascii=False)
    sys.stdout.write(out + '\n')
    sys.stdout.flush()
    return 0


def cli(argv):
    """子进程命令行分派；返回退出码。"""
    if len(argv) == 5 and argv[0] == '--install' and argv[3] == '--index':
        return install(argv[1], argv[2], argv[4])
    if len(argv) == 3 and argv[0] == '--site-packages' and argv[2] == '--stdio':
        return run_stdio(argv[1])
    sys.stderr.write(
        'usage: ocr-helper --install <dir> <pkg> --index <url> | '
        '--site-packages <dir> --stdio\n')
    return 2


if __name__ == '__main__':
    sys.exit(cli(sys.argv[1:]))