# -*- coding: utf-8 -*-
"""构建 exe 安装包：生成图标 + PyInstaller 打包为单文件 exe（自身即安装包）。
用法：python build.py
产物：dist\\ZviberPanel.exe —— 双击运行弹出安装向导，安装后经桌面右键菜单启动。
"""
import os
import subprocess
import sys

ICON = os.path.abspath('_build_icon.ico')
MANIFEST = os.path.abspath('_build_manifest.xml')

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
    if not gen_icon():
        print('[ERR] 图标生成失败')
        return 1
    with open(MANIFEST, 'w', encoding='utf-8') as f:
        f.write(MANIFEST_XML)
    args = [sys.executable, '-m', 'PyInstaller',
            '--noconfirm', '--clean', '--onefile', '--windowed',
            '--name', 'ZviberPanel', '--icon', ICON, '--manifest', MANIFEST,
            'main.pyw']
    print('[..] %s' % ' '.join(args))
    r = subprocess.call(args)
    if r == 0:
        print('[OK] 构建完成：%s' % os.path.abspath(os.path.join('dist', 'ZviberPanel.exe')))
    return r


if __name__ == '__main__':
    sys.exit(main())
