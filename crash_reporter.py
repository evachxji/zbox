# -*- coding: utf-8 -*-
"""独立崩溃报告进程：整理文本日志并显示轻量双主题弹窗。"""
import argparse
import ctypes
import json
import os
import sys

import PySide6
from PySide6.QtCore import QCoreApplication, QLibraryInfo, Qt, QUrl
from PySide6.QtGui import (QDesktopServices, QIcon, QLinearGradient, QPainter,
                           QPen, QPixmap)
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QToolButton, QVBoxLayout, QWidget)

import crash_report
import i18n
import sysutil
from i18n import t
from themes import build_qss

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_UI_SCALE = None


def ui_scale():
    global _UI_SCALE
    if _UI_SCALE is None:
        try:
            _UI_SCALE = ctypes.windll.user32.GetDpiForSystem() / 96.0
        except Exception:
            _UI_SCALE = 1.0
        _UI_SCALE = max(0.75, min(_UI_SCALE, 3.0))
    return _UI_SCALE


def sc(value):
    return int(round(value * ui_scale()))


def _vector_icon():
    """与 app.make_icon 相同的 Z 图形；冻结环境没有 assets 目录时兜底。"""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(size / 64.0, size / 64.0)
        bg = QLinearGradient(0, 0, 64, 64)
        bg.setColorAt(0, '#262b45')
        bg.setColorAt(1, '#161a2b')
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(QRectF(2, 2, 60, 60), 15, 15)
        painter.setPen(QPen('#f5f6fa', 5.5, Qt.SolidLine, Qt.FlatCap))
        painter.drawLine(QPointF(18, 20), QPointF(46, 20))
        painter.drawLine(QPointF(18, 44), QPointF(46, 44))
        gradient = QLinearGradient(46, 20, 18, 44)
        gradient.setColorAt(0, '#ffc531')
        gradient.setColorAt(1, '#ff7a18')
        painter.setPen(QPen(gradient, 5.5, Qt.SolidLine, Qt.FlatCap))
        painter.drawLine(QPointF(46, 20), QPointF(18, 44))
        painter.end()
        icon.addPixmap(pm)
    return icon


def app_icon():
    path = os.path.join(BASE_DIR, 'assets', 'icon.png')
    return QIcon(path) if os.path.isfile(path) else _vector_icon()


def _read_text(path):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except (OSError, UnicodeError):
        return ''


def _read_config():
    try:
        with open(os.path.join(sysutil.appdata_dir(), 'config.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _summary(report_dir):
    trace = _read_text(os.path.join(report_dir, 'python.txt')).strip()
    if trace:
        return trace.splitlines()[-1]
    native = _read_text(os.path.join(report_dir, 'native.json'))
    try:
        return json.loads(native).get('code') or 'Native crash'
    except ValueError:
        return 'Native crash'


class CrashDialog(QDialog):
    """与设置窗同族的崩溃结果弹窗，只负责展示和用户主动操作。"""

    def __init__(self, report_dir, theme_key='nocturne'):
        super().__init__()
        self.report_dir = report_dir
        self.theme_key = theme_key
        accent = '#0067c0' if theme_key == 'mica' else '#e8a33d'
        self.setObjectName('settingsDlg')
        self.setWindowTitle(t('crash.window'))
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = QWidget()
        card.setObjectName('settingsPanel')
        root.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(sc(16), sc(7), sc(16), sc(15))
        lay.setSpacing(sc(8))

        title_row = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(sc(20), sc(20)))
        title_row.addWidget(logo)
        app_name = QLabel(t('crash.window'))
        app_name.setObjectName('setLabel')
        title_row.addWidget(app_name)
        title_row.addStretch(1)
        close = QToolButton()
        close.setObjectName('closeBtn')
        close.setText('✕')
        close.setFixedSize(sc(28), sc(24))
        close.setToolTip(t('common.close'))
        close.clicked.connect(self.reject)
        title_row.addWidget(close)
        lay.addLayout(title_row)

        hero = QHBoxLayout()
        warning = QLabel('!')
        warning.setAlignment(Qt.AlignCenter)
        warning.setFixedSize(sc(34), sc(34))
        warning.setStyleSheet('QLabel { color: %s; background: %s; border-radius: %dpx; '
                              'font: 700 %dpx "Segoe UI"; }' %
                              (accent, 'rgba(0,103,192,20)' if theme_key == 'mica'
                               else 'rgba(232,163,61,24)', sc(17), sc(20)))
        hero.addWidget(warning, 0, Qt.AlignTop)
        message_box = QVBoxLayout()
        title = QLabel(t('crash.title'))
        title.setObjectName('setTitle')
        message_box.addWidget(title)
        message = QLabel(t('crash.message'))
        message.setObjectName('infoText')
        message.setWordWrap(True)
        message_box.addWidget(message)
        hero.addLayout(message_box, 1)
        lay.addLayout(hero)

        saved = QLabel(t('crash.saved_at'))
        saved.setObjectName('setLabel')
        lay.addWidget(saved)
        path_row = QHBoxLayout()
        path = QLabel(report_dir)
        self.path_label = path
        path.setObjectName('infoText')
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path.setStyleSheet('QLabel { font: %dpx Consolas; }' % sc(10))
        path_row.addWidget(path, 1)
        self.copy_btn = QPushButton(t('common.copy'))
        self.copy_btn.setObjectName('setBtn')
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self.copy_path)
        path_row.addWidget(self.copy_btn, 0, Qt.AlignTop)
        lay.addLayout(path_row)

        log_ready = os.path.isfile(os.path.join(report_dir, 'zbox-crash.log'))
        dump_ready = os.path.isfile(os.path.join(report_dir, 'zbox-crash.dmp'))
        self.log_status = QLabel(t('crash.log_ready' if log_ready else 'crash.log_missing'))
        self.log_status.setObjectName('setLabel')
        lay.addWidget(self.log_status)
        self.dump_status = QLabel(t('crash.dump_ready' if dump_ready else 'crash.dump_missing'))
        self.dump_status.setObjectName('setLabel')
        lay.addWidget(self.dump_status)
        privacy = QLabel(t('crash.privacy'))
        privacy.setObjectName('setLabel')
        privacy.setWordWrap(True)
        lay.addWidget(privacy)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.open_btn = QPushButton(t('crash.open_dir'))
        self.open_btn.setObjectName('setBtn')
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(self.open_directory)
        buttons.addWidget(self.open_btn)
        self.issue_btn = QPushButton(t('crash.issue'))
        self.issue_btn.setObjectName('setSave')
        self.issue_btn.setCursor(Qt.PointingHandCursor)
        self.issue_btn.clicked.connect(self.open_issue)
        buttons.addWidget(self.issue_btn)
        lay.addLayout(buttons)

        self.setFixedWidth(sc(400))
        self.adjustSize()

    def copy_path(self):
        QApplication.clipboard().setText(self.report_dir)

    def open_directory(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.report_dir))

    def open_issue(self):
        log_ready = os.path.isfile(os.path.join(self.report_dir, 'zbox-crash.log'))
        dump_ready = os.path.isfile(os.path.join(self.report_dir, 'zbox-crash.dmp'))
        QDesktopServices.openUrl(QUrl(crash_report.build_issue_url(
            _summary(self.report_dir), log_ready, dump_ready)))


def _native_stack(path, offset):
    if not path:
        return ''
    try:
        with open(path, 'rb') as f:
            f.seek(max(0, offset))
            return f.read().decode('utf-8', errors='replace')
    except OSError:
        return ''


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('report_dir')
    parser.add_argument('--native-log', default='')
    parser.add_argument('--native-offset', type=int, default=0)
    args = parser.parse_args(argv)

    cfg = _read_config()
    i18n.set_language(i18n.resolve_language(
        cfg.get('language'), sysutil.installed_language(), i18n.detect_system_language()))
    theme = cfg.get('theme', 'nocturne')
    if theme == 'auto':
        theme = 'mica' if sysutil.system_uses_light_theme() else 'nocturne'
    if theme not in ('nocturne', 'mica'):
        theme = 'nocturne'

    QCoreApplication.addLibraryPath(os.path.join(os.path.dirname(PySide6.__file__), 'plugins'))
    qapp = QApplication.instance() or QApplication(sys.argv[:1])
    qapp.setApplicationName(sysutil.APP_NAME)
    qapp.setQuitOnLastWindowClosed(True)
    qapp.setStyleSheet(build_qss(theme, 'Microsoft YaHei UI', 'Segoe UI', ui_scale()))

    native_error = ''
    try:
        info = json.loads(_read_text(os.path.join(args.report_dir, 'native.json')) or '{}')
        native_error = ' '.join(v for v in (info.get('code'), info.get('address')) if v)
    except ValueError:
        pass
    crash_report.write_report(
        args.report_dir,
        python_trace=_read_text(os.path.join(args.report_dir, 'python.txt')),
        native_trace=_native_stack(args.native_log, args.native_offset),
        native_error=native_error,
        dump_error=_read_text(os.path.join(args.report_dir, 'dump_error.txt')),
        qt_version=QLibraryInfo.version().toString(), pyside_version=PySide6.__version__)

    dialog = CrashDialog(args.report_dir, theme)
    qapp._crash_dialog = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return qapp.exec()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
