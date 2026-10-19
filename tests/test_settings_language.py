# -*- coding: utf-8 -*-
"""设置页语言项：下拉框位置、当前语言与选择持久化。"""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QWidget

import app as app_module
import i18n
from app import Config, SettingsDialog
from i18n import ZH


class _PanelStub(QWidget):
    """SettingsDialog 的父窗口必须是 QWidget；其余属性只提供设置页用到的最小表面。"""

    class Transfer:
        def service_enabled(self):
            return False

        def set_enabled(self, value):
            return value

        enabled_changed = type('Sig', (), {'connect': lambda *args: None})()

    class Video:
        def service_enabled(self):
            return False

        def set_enabled(self, value):
            return value

        enabled_changed = type('Sig', (), {'connect': lambda *args: None})()

    _theme = 'nocturne'
    transfer = Transfer()
    video = Video()

    def apply_theme(self, _key):
        pass

    def frameGeometry(self):
        return QApplication.primaryScreen().availableGeometry()


class SettingsLanguageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        i18n.set_language(ZH)

    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_language_combo_follows_video_and_persists(self):
        with patch('app.sysutil.autostart_get', return_value=False):
            panel = _PanelStub()
            panel.cfg = Config(os.devnull)
            dlg = SettingsDialog(panel, lambda *a, **k: None, lambda: None)
        self.addCleanup(dlg.close)
        dlg.show()
        self.qapp.processEvents()
        combo = dlg.findChild(QComboBox, 'languageCombo')
        self.assertIsNotNone(combo)
        self.assertEqual(combo.currentData(), ZH)
        combo_y = combo.mapTo(dlg, QPoint()).y()
        video_y = dlg.video_chk.mapTo(dlg, QPoint()).y()
        update_y = dlg.btn_update.mapTo(dlg, QPoint()).y()
        self.assertGreater(combo_y, video_y)
        self.assertLess(combo_y, update_y)
        separators = [frame for frame in dlg.findChildren(QFrame, 'setSep')
                      if video_y < frame.mapTo(dlg, QPoint()).y() < combo_y]
        self.assertEqual(len(separators), 1)
        self.assertEqual(combo.width(), app_module.sc(150))
        with patch.object(dlg, '_confirm_language_restart', return_value=False):
            combo.setCurrentIndex(1)
        self.assertEqual(panel.cfg.data['language'], 'en-US')

    def test_combo_lists_both_languages_and_follows_current(self):
        i18n.set_language(i18n.EN)
        with patch('app.sysutil.autostart_get', return_value=False):
            panel = _PanelStub()
            panel.cfg = Config(os.devnull)
            dlg = SettingsDialog(panel, lambda *a, **k: None, lambda: None)
        combo = dlg.findChild(QComboBox, 'languageCombo')
        self.assertEqual([combo.itemText(i) for i in range(combo.count())],
                         ['简体中文', 'English'])
        self.assertEqual(combo.currentData(), i18n.EN)

    def test_config_normalizes_language_values(self):
        cases = [('en_US', 'en-US'), (' EN-US ', 'en-US'),
                 ('zh_CN', 'zh-CN'), ('invalid', ''), (None, '')]
        for raw, expected in cases:
            with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False,
                                             encoding='utf-8') as f:
                json.dump({'language': raw}, f)
                path = f.name
            try:
                self.assertEqual(Config(path).data['language'], expected, raw)
            finally:
                os.unlink(path)

    def test_selecting_effective_language_does_not_prompt_restart(self):
        """取消重启后选回当前生效语言：只更新配置，不再弹重启提示。"""
        with patch('app.sysutil.autostart_get', return_value=False):
            panel = _PanelStub()
            panel.cfg = Config(os.devnull)
            panel.cfg.data['language'] = 'en-US'   # 已选英文，但本次进程仍是中文
            dlg = SettingsDialog(panel, lambda *a, **k: None, lambda: None)
        combo = dlg.findChild(QComboBox, 'languageCombo')
        self.assertEqual(combo.currentData(), 'en-US')
        with patch.object(dlg, '_confirm_language_restart', return_value=False) as confirm:
            combo.setCurrentIndex(0)   # 选回当前生效的中文
        confirm.assert_not_called()
        self.assertEqual(panel.cfg.data['language'], 'zh-CN')

    def test_restart_failure_keeps_instance_and_relistens(self):
        """startDetached 返回 (False, -1) 时不能退出，并恢复单实例监听。"""
        fake_app = MagicMock()
        fake_app._zbox_ipc_server = MagicMock()
        with patch('app.QApplication') as qapp_cls, patch('app.QProcess') as proc_cls:
            qapp_cls.instance.return_value = fake_app
            proc_cls.startDetached.return_value = (False, -1)
            self.assertFalse(app_module.restart_application())
        fake_app._zbox_ipc_server.close.assert_called_once()
        fake_app._zbox_ipc_server.listen.assert_called_once_with(app_module.sysutil.IPC_KEY)
        fake_app.quit.assert_not_called()

    def test_restart_success_quits_instance(self):
        """startDetached 返回 (True, pid) 时先关 IPC，再退出旧实例。"""
        fake_app = MagicMock()
        fake_app._zbox_ipc_server = MagicMock()
        with patch('app.QApplication') as qapp_cls, patch('app.QProcess') as proc_cls:
            qapp_cls.instance.return_value = fake_app
            proc_cls.startDetached.return_value = (True, 1234)
            self.assertTrue(app_module.restart_application())
        fake_app._zbox_ipc_server.close.assert_called_once()
        fake_app._zbox_ipc_server.listen.assert_not_called()
        fake_app.quit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
