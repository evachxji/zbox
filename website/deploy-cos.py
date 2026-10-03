#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部署 website/ 到腾讯云 COS 静态托管（https://zbox.wzyjc.cn）

参照 ycblog/deploy-cos.py：文本资源 gzip 预压缩上传（COS 静态托管不会自动压缩）。
zbox 站点文件名都不带内容哈希，故全部 no-cache（ETag 回源验证），改完即时生效。

用法（仓库根目录或本目录均可）：
  python website/deploy-cos.py                # 上传站点文件
  python website/deploy-cos.py --bind-cert <证书ID>   # 续期后绑定新证书到 zbox.wzyjc.cn
凭证读 ~/.tccli/default.credential（与 tccli 共用同一份密钥）。
"""

import gzip
import json
import os
import sys
from pathlib import Path
from urllib.request import urlopen

from qcloud_cos import CosConfig, CosS3Client

BUCKET = 'zbox-wzyjc-cn-1257727321'
REGION = 'ap-shanghai'
DOMAIN = 'zbox.wzyjc.cn'
SITE = Path(__file__).parent  # 上传 website/ 自身（即站点根）

GZIP_EXTS = {'.html', '.css', '.js', '.svg', '.txt'}
MIME = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.txt': 'text/plain; charset=utf-8',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.mp4': 'video/mp4',
}
SELF = Path(__file__).name


def skip(p):
    # 编辑器/工具元数据与脚本自身不上传
    return (p.name == SELF or p.name.endswith('.artifact.json')
            or any(part.startswith('.') for part in p.parts))


def _client():
    cred = json.loads(
        (Path.home() / '.tccli' / 'default.credential').read_text(encoding='utf-8')
    )
    return CosS3Client(
        CosConfig(Region=REGION, SecretId=cred['secretId'], SecretKey=cred['secretKey'])
    )


def bind_cert(cert_id):
    """免费 DV 证书 90 天到期，续期（ssl ApplyCertificate）后调它绑定新证书。
    走 PEM 直传：CertID 引用方式实测报 InvalidArgument（COS 侧不同步新证书）。"""
    import subprocess
    import tempfile
    import zipfile

    out = subprocess.check_output(
        ['tccli', 'ssl', 'DescribeDownloadCertificateUrl',
         '--CertificateId', cert_id, '--region', 'ap-shanghai'],
        env=dict(os.environ, PYTHONUTF8='1'))
    url = json.loads(out.decode('utf-8'))['DownloadCertificateUrl']
    zip_path = Path(tempfile.gettempdir()) / 'zbox_cert_dl.zip'
    zip_path.write_bytes(urlopen(url).read())
    with zipfile.ZipFile(zip_path) as z:
        pem = key = None
        for n in z.namelist():
            if n.endswith('_bundle.pem'):
                pem = z.read(n).decode()
            elif n.endswith('.key'):
                key = z.read(n).decode()
    zip_path.unlink()
    _client().put_bucket_domain_certificate(
        Bucket=BUCKET,
        DomainCertificateConfiguration={
            'CertificateInfo': {'CertType': 'CustomCert', 'CustomCert': {'Cert': pem, 'PrivateKey': key}},
            'DomainList': {'DomainName': [DOMAIN]},
        })
    print('证书 %s 已绑定到 %s' % (cert_id, DOMAIN))


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--bind-cert':
        return bind_cert(sys.argv[2])

    client = _client()

    files = [p for p in SITE.rglob('*') if p.is_file() and not skip(p.relative_to(SITE))]
    total_raw = total_up = 0
    for i, p in enumerate(sorted(files), 1):
        key = p.relative_to(SITE).as_posix()
        ext = p.suffix.lower()
        body = p.read_bytes()
        total_raw += len(body)
        kwargs = {
            'ContentType': MIME.get(ext, 'application/octet-stream'),
            'CacheControl': 'no-cache',
        }
        if ext in GZIP_EXTS:
            body = gzip.compress(body, compresslevel=9, mtime=0)
            kwargs['ContentEncoding'] = 'gzip'
        client.put_object(Bucket=BUCKET, Key=key, Body=body, **kwargs)
        total_up += len(body)
        tag = ' gzip' if 'ContentEncoding' in kwargs else ''
        print('[%d/%d] %s  %.0fKB%s' % (i, len(files), key, len(body) / 1024, tag))
    print('\n完成：%d 个文件，原始 %.1fMB → 上传 %.1fMB'
          % (len(files), total_raw / 1048576, total_up / 1048576))


if __name__ == '__main__':
    sys.exit(main())
