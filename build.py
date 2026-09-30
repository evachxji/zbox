# -*- coding: utf-8 -*-
"""构建 exe 安装包：生成图标 + PyInstaller 打包为 onedir 目录（自身即安装向导）。
用法：python build.py
产物：dist\\ZviberPanel\\（内含 ZviberPanel.exe 与 _internal\\ 依赖）+ dist\\ZviberPanel-v<版本>-<架构>.zip
分发包——解压后双击 ZviberPanel.exe 弹出安装向导，安装后经桌面右键菜单启动。
onedir 而非 onefile：启动免解压临时目录，常驻面板每次开机都快；代价是分发要整个目录（已自动打 zip）。
中间文件（图标、DPI 清单、spec 与 PyInstaller 工作目录）一律收在 dist\\build\\ 下，
根目录保持干净；dist 整个目录已在 .gitignore 里。
"""
import os
import platform
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, 'dist')        # 最终产物放在这一层
WORK = os.path.join(DIST, 'build')       # 其余中间文件都收在这里
ICON = os.path.join(WORK, '_build_icon.ico')
MANIFEST = os.path.join(WORK, '_build_manifest.xml')

# 架构标识跟随打包用的 Python 解释器（PyInstaller 不能交叉编译）
ARCH = {'AMD64': 'x64', 'x86': 'x86', 'ARM64': 'arm64'}.get(
    platform.machine(), platform.machine().lower())

# DPI 感知清单：PyInstaller 默认 exe 无 DPI 感知声明，进程按 unaware 虚拟化，
# ui_scale() 读到 96 DPI 导致界面不放大（源码由 Qt 运行时设置感知，无此问题）。
MANIFEST_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
    </windowsSettings>
  </application>
</assembly>
'''


def gen_icon():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt5.QtWidgets import QApplication
    qapp = QApplication([])
    try:
        import app as ui
        return ui.make_icon().pixmap(64, 64).save(ICON, 'ICO')
    finally:
        qapp.quit()


def main():
    os.makedirs(WORK, exist_ok=True)     # 图标与清单要写进去，得先有目录
    # onefile 时代的残留：onedir 产物是同名目录，根下这个旧 exe 会误导分发，顺手清掉
    stale = os.path.join(DIST, 'ZviberPanel.exe')
    if os.path.isfile(stale):
        os.remove(stale)
    if not gen_icon():
        print('[ERR] 图标生成失败')
        return 1
    with open(MANIFEST, 'w', encoding='utf-8') as f:
        f.write(MANIFEST_XML)
    # 三个 path 都给绝对路径：PyInstaller 默认把 spec 丢当前目录、工作文件丢 ./build，
    # 不改的话根目录会被这两样塞满
    args = [sys.executable, '-m', 'PyInstaller',
            '--noconfirm', '--clean', '--onedir', '--windowed',
            '--name', 'ZviberPanel', '--icon', ICON, '--manifest', MANIFEST,
            '--distpath', DIST, '--workpath', WORK, '--specpath', WORK,
            os.path.join(ROOT, 'main.pyw')]
    print('[..] %s' % ' '.join(args))
    r = subprocess.call(args)
    if r == 0:
        from version import APP_VERSION
        zip_base = os.path.join(DIST, 'ZviberPanel-v%s-%s' % (APP_VERSION, ARCH))
        shutil.make_archive(zip_base, 'zip', DIST, 'ZviberPanel')
        print('[OK] 构建完成：%s' % os.path.join(DIST, 'ZviberPanel', 'ZviberPanel.exe'))
        print('[OK] 分发包：%s.zip' % zip_base)
    return r


if __name__ == '__main__':
    sys.exit(main())
