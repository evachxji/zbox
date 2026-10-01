# -*- coding: utf-8 -*-
"""构建 exe 安装包：两次 PyInstaller——
1) main.pyw → onedir 程序本体（dist\\build\\app\\zviber\\，安装后就是这个目录：一堆小文件、启动快）；
2) setup.pyw → onefile 安装包，把 onedir 目录整体内嵌为 payload（--add-data），
   产物 dist\\zviber-Setup-v<版本>-<架构>.exe——用户只拿到这一个 exe，双击弹安装向导。
中间文件（图标、DPI 清单、spec、PyInstaller 工作目录、onedir 本体）一律收在 dist\\build\\ 下，
根目录保持干净；dist 整个目录已在 .gitignore 里。
用法：python build.py
"""
import glob
import os
import platform
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, 'dist')        # 最终产物放在这一层
WORK = os.path.join(DIST, 'build')       # 其余中间文件都收在这里
APP_DIR = os.path.join(WORK, 'app')      # onedir 程序本体（payload 来源）
ICON = os.path.join(WORK, '_build_icon.ico')
MANIFEST = os.path.join(WORK, '_build_manifest.xml')

# 架构标识跟随打包用的 Python 解释器（PyInstaller 不能交叉编译）
ARCH = {'AMD64': 'x64', 'x86': 'x86', 'ARM64': 'arm64'}.get(
    platform.machine(), platform.machine().lower())

# 程序本体名（全小写）：onedir 目录名、exe 名、安装包名前缀都用它，与 sysutil.APP_NAME 一致
APP_NAME = 'zviber'

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


def run_pyinstaller(entry, name, mode, dist_dir, work_dir, extra=()):
    # 三个 path 都给绝对路径：PyInstaller 默认把 spec 丢当前目录、工作文件丢 ./build，
    # 不改的话根目录会被这两样塞满
    args = [sys.executable, '-m', 'PyInstaller',
            '--noconfirm', '--clean', mode, '--windowed',
            '--name', name, '--icon', ICON, '--manifest', MANIFEST,
            '--distpath', dist_dir, '--workpath', work_dir, '--specpath', WORK]
    args += list(extra)
    args.append(os.path.join(ROOT, entry))
    print('[..] %s' % ' '.join(args))
    return subprocess.call(args)


def main():
    os.makedirs(WORK, exist_ok=True)     # 图标与清单要写进去，得先有目录
    # 旧形态残留：onefile app、onedir 直发目录、zip 分发包，顺手清掉避免误发
    # （含改名之前的 ZviberPanel 产物）
    for name in (APP_NAME, 'ZviberPanel'):
        if os.path.isfile(os.path.join(DIST, name + '.exe')):
            os.remove(os.path.join(DIST, name + '.exe'))
        if os.path.isdir(os.path.join(DIST, name)):
            shutil.rmtree(os.path.join(DIST, name))
    for pat in ('%s-v*.zip' % APP_NAME, 'ZviberPanel-v*.zip'):
        for z in glob.glob(os.path.join(DIST, pat)):
            os.remove(z)
    if not gen_icon():
        print('[ERR] 图标生成失败')
        return 1
    with open(MANIFEST, 'w', encoding='utf-8') as f:
        f.write(MANIFEST_XML)
    from version import APP_VERSION

    # 1) 程序本体：onedir（安装到用户机器的就是这份）
    r = run_pyinstaller('main.pyw', APP_NAME, '--onedir', APP_DIR,
                        os.path.join(WORK, 'work_app'))
    if r:
        return r

    # zshell_host.exe（原生外壳菜单宿主，native\build_native.cmd 生成）放 exe 同目录进 payload
    zhost = os.path.join(ROOT, 'native', 'zshell_host.exe')
    if os.path.isfile(zhost):
        shutil.copy2(zhost, os.path.join(APP_DIR, APP_NAME, 'zshell_host.exe'))
    else:
        print('[警告] native\\zshell_host.exe 不存在，外壳菜单回退 ctypes 实现')

    # 2) 安装包：onefile，把 onedir 目录整体内嵌为 payload
    # --noupx：onefile 首次运行要把内嵌 payload 解到临时目录，若本体被 UPX 压过，
    # 每次启动都得多花解压时间（实测拖慢明显）。安装包只大几 MB，换启动快。
    name = '%s-Setup-v%s-%s' % (APP_NAME, APP_VERSION, ARCH)
    payload = os.path.join(APP_DIR, APP_NAME)
    r = run_pyinstaller('setup.pyw', name, '--onefile', DIST,
                        os.path.join(WORK, 'work_setup'),
                        extra=['--noupx', '--add-data', '%s;payload' % payload])
    if r == 0:
        print('[OK] 安装包：%s' % os.path.join(DIST, name + '.exe'))
    return r


if __name__ == '__main__':
    sys.exit(main())