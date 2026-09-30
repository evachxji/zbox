# -*- coding: utf-8 -*-
"""ZviberPanel-Setup 安装包入口：build.py 把它打成 onefile exe（内嵌 onedir 程序目录为 payload），
双击弹出安装向导，把 payload 复制到安装目录。源码运行仅供调试向导界面（payload 回退到构建中间产物）。
"""
import sys

from PyQt5.QtWidgets import QApplication


def main():
    qapp = QApplication(sys.argv)
    qapp.setApplicationName('ZviberPanelSetup')
    import installer
    return installer.setup_main()


if __name__ == '__main__':
    sys.exit(main())