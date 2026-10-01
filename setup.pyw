# -*- coding: utf-8 -*-
"""ZviberPanel-Setup 安装包入口：build.py 把它打成 onefile exe（内嵌 onedir 程序目录为 payload），
双击弹出安装向导，把 payload 复制到安装目录。源码运行仅供调试向导界面（payload 回退到构建中间产物）。
"""
import ctypes
import sys

# 同 main.pyw：Qt 默认把 GUI 线程的 COM 初始化为 MTA，安装向导「浏览…」的原生目录框
# 在 MTA 下会抛 RPC_E_WRONG_THREAD（0x8001010e）致命错误。必须在 PyQt5 导入前初始化 STA。
ctypes.windll.ole32.CoInitializeEx(None, 0)   # COINIT_APARTMENTTHREADED

from PyQt5.QtWidgets import QApplication


def main():
    qapp = QApplication(sys.argv)
    qapp.setApplicationName('ZviberPanelSetup')
    import installer
    return installer.setup_main()


if __name__ == '__main__':
    sys.exit(main())