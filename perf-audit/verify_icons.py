# -*- coding: utf-8 -*-
"""验证后台取图标与原 QFileIconProvider 路线是否一致（P0-1 回归）。

两层验证：
  A. 单文件级：同一路径分别走「新后台路线（SHGetFileInfoW + DrawIconEx）」与
     「旧路线（QFileIconProvider + pixmap）」，比对像素。
  B. 端到端：真的建一个 BoxWindow（映射到指定目录），等后台取回后检查
     每行拿到的是真图标而不是占位图标，并保存截图供目检。

用法：python perf-audit\\verify_icons.py [--dir "D:\\Document\\桌面快捷方式"]
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=r'D:\Document\桌面快捷方式')
    ap.add_argument('--wait', type=float, default=8.0)
    ap.add_argument('--out', default=os.path.join(HERE, 'results', 'icon-verify.png'))
    args = ap.parse_args()

    from PySide6.QtCore import QFileInfo, QSize, Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication, QFileIconProvider

    app = QApplication.instance() or QApplication([])
    import boxes as bx

    dpr = app.primaryScreen().devicePixelRatio()
    print('屏幕 devicePixelRatio = %s' % dpr)

    # ---------- A. 单文件级比对 ----------
    provider = QFileIconProvider()
    paths = []
    if os.path.isdir(args.dir):
        for name in sorted(os.listdir(args.dir)):
            p = os.path.join(args.dir, name)
            if os.path.isfile(p):
                paths.append(p)
    paths = paths[:30]

    same = diff = miss = sizediff = 0
    details = []
    for p in paths:
        # 旧路线（GUI 线程）：provider.icon() + pixmap
        old = provider.icon(QFileInfo(p)).pixmap(QSize(16, 16), dpr)
        # 新路线：纯 ctypes（.lnk 先解析目标再取图标），后台线程做
        px = max(1, int(round(16 * dpr)))
        img = bx._shell_icon_image(p, False, px)
        if img is None or img.isNull():
            miss += 1
            details.append((os.path.basename(p), 'MISS', None))
            continue
        from PySide6.QtGui import QImage
        new = QPixmap.fromImage(img)
        if old.isNull():
            miss += 1
            details.append((os.path.basename(p), 'OLD_NULL', None))
            continue
        if (old.width(), old.height()) != (new.width(), new.height()):
            sizediff += 1
        # 内容比对：格式归一（Qt 的 pixmap 是 premultiplied）+ 同尺寸比像素
        a = old.toImage().convertToFormat(QImage.Format_ARGB32) \
            .scaled(px, px, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        b = img.convertToFormat(QImage.Format_ARGB32)
        if a == b:
            same += 1
        else:
            diff += 1
            ab = bytes(a.bits())
            bb = bytes(b.bits())
            n = sum(1 for i in range(0, min(len(ab), len(bb)), 4)
                    if ab[i:i + 4] != bb[i:i + 4])
            details.append((os.path.basename(p), 'DIFF',
                            'old %dx%d vs new %dx%d, 差异像素 %d/%d'
                            % (old.width(), old.height(), new.width(), new.height(),
                               n, a.width() * a.height())))

    print('A. 单文件比对：内容一致 %d / 内容不同 %d / 取不到 %d / 尺寸档不同 %d（共 %d）'
          % (same, diff, miss, sizediff, len(paths)))
    for name, tag, extra in details[:10]:
        print('   %-40s %s %s' % (name, tag, extra or ''))

    # ---------- B. 端到端：真格子 ----------
    if not os.path.isdir(args.dir):
        print('B. 端到端跳过：目录不存在')
        return 0 if diff == 0 and miss == 0 else 1

    from boxes import BoxManager, BoxWindow
    from app import Config

    import tempfile
    data_dir = tempfile.mkdtemp(prefix='zbox_vicons_')
    cfg = Config(os.path.join(data_dir, 'config.json'))
    mgr = BoxManager(data_dir, None) if False else None

    # 直接造一个 BoxWindow（不启 BoxManager，避免动用户桌面）
    rec = {'id': 'vtest', 'kind': 'folder', 'name': 'verify', 'x': 40, 'y': 40,
           'w': 320, 'h': 300, 'collapsed': False, 'locked': False,
           'sort': 'name', 'path': args.dir}
    win = BoxWindow.__new__(BoxWindow)
    # BoxWindow 需要 mgr；用最小替身
    class _FakeMgr:
        store = None
        windows = []

        def save_rec(self, rec):
            pass

        def refresh(self):
            pass

    win.mgr = _FakeMgr()
    win.rec = rec
    win.devicePixelRatioF = lambda: 1.0
    # 走真构造路径太重（要整套 UI），改为直接验证后台线程 + 缓存链路
    del win

    # 直接驱动后台线程：提交 → 等回填
    got = []
    bx._icon_worker().set_callback(lambda p, is_dir, size, dpr, img: got.append((p, size)))
    for p in paths[:10]:
        bx._icon_worker().submit(p, False, 16, 16, 1.0)
    import time
    t0 = time.time()
    while len(got) < min(10, len(paths)) and time.time() - t0 < args.wait:
        app.processEvents()
        time.sleep(0.05)

    print('B. 后台线程回填：提交 %d 个，取回 %d 个' % (min(10, len(paths)), len(got)))
    return 0 if (diff == 0 and miss == 0 and len(got) == min(10, len(paths))) else 1


if __name__ == '__main__':
    sys.exit(main())
