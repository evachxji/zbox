# -*- coding: utf-8 -*-
"""安装器双语与旧 Zbox 清理：默认目录、清理边界、语言下拉、注册表语言往返。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import installer
import i18n
import sysutil
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QLabel,
                               QPushButton, QToolButton)


def _has_chinese(text):
    return any('一' <= ch <= '鿿' for ch in text)


class InstallerLanguageTest(unittest.TestCase):
    def test_all_user_install_directory_is_program_files(self):
        with patch.dict(os.environ, {'ProgramFiles': r'C:\Program Files'}):
            self.assertEqual(installer.install_dir(True), r'C:\Program Files\zbox')

    def test_cleanup_removes_only_directories_containing_zbox_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / 'old-zbox'
            bad = Path(tmp) / 'not-zbox'
            good.mkdir()
            bad.mkdir()
            (good / 'zbox.exe').write_bytes(b'exe')
            (bad / 'keep.txt').write_text('keep', encoding='utf-8')
            with patch.object(installer, '_registered_zbox_dirs', return_value={str(good), str(bad)}), \
                    patch.object(installer, 'request_quit', return_value=True), \
                    patch.object(installer.time, 'sleep'), \
                    patch.object(installer.sysutil, 'autostart_remove'), \
                    patch.object(installer.sysutil, 'context_menu_remove_zbox'), \
                    patch.object(installer.sysutil, 'uninstall_reg_remove_zbox'):
                installer.cleanup_existing_zbox()
            self.assertFalse(good.exists())
            self.assertTrue((bad / 'keep.txt').exists())

    def test_cleanup_failure_aborts_before_registry_cleanup(self):
        i18n.set_language(i18n.EN)
        self.addCleanup(i18n.set_language, i18n.DEFAULT_LANGUAGE)
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / 'old-zbox'
            good.mkdir()
            (good / 'zbox.exe').write_bytes(b'exe')
            with patch.object(installer, '_registered_zbox_dirs', return_value={str(good)}), \
                    patch.object(installer, 'request_quit', return_value=True), \
                    patch.object(installer, '_rmtree_retry', side_effect=OSError('locked')), \
                    patch.object(installer.sysutil, 'autostart_remove') as autostart, \
                    patch.object(installer.sysutil, 'context_menu_remove_zbox') as menu, \
                    patch.object(installer.sysutil, 'uninstall_reg_remove_zbox') as reg:
                with self.assertRaises(RuntimeError) as ctx:
                    installer.cleanup_existing_zbox()
            self.assertIn('Task Manager', str(ctx.exception))
            autostart.assert_not_called()
            menu.assert_not_called()
            reg.assert_not_called()

    def test_rmtree_retry_recovers_after_transient_failure(self):
        with patch.object(installer.shutil, 'rmtree',
                          side_effect=[OSError('busy'), None]) as rmtree, \
                patch.object(installer.time, 'sleep'):
            installer._rmtree_retry('dummy', timeout=1.0)
        self.assertEqual(rmtree.call_count, 2)

    def test_rmtree_retry_raises_after_timeout(self):
        with patch.object(installer.shutil, 'rmtree', side_effect=OSError('busy')) as rmtree, \
                patch.object(installer.time, 'sleep'), \
                patch.object(installer.time, 'monotonic', side_effect=[0.0, 0.0, 100.0]):
            with self.assertRaises(OSError):
                installer._rmtree_retry('dummy', timeout=15.0)
        self.assertEqual(rmtree.call_count, 2)

    def test_fresh_install_does_not_report_waiting_for_exit(self):
        """没有实例在运行时（request_quit=False）不该显示「等待旧版本退出」。"""
        i18n.set_language(i18n.EN)
        self.addCleanup(i18n.set_language, i18n.DEFAULT_LANGUAGE)
        waiting = i18n.t('installer.progress.waiting_exit')
        texts = []
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / 'old-zbox'
            good.mkdir()
            (good / 'zbox.exe').write_bytes(b'exe')
            with patch.object(installer, '_registered_zbox_dirs', return_value={str(good)}), \
                    patch.object(installer, 'request_quit', return_value=False), \
                    patch.object(installer.sysutil, 'autostart_remove'), \
                    patch.object(installer.sysutil, 'context_menu_remove_zbox'), \
                    patch.object(installer.sysutil, 'uninstall_reg_remove_zbox'):
                installer.cleanup_existing_zbox(
                    progress=lambda _pct, text: texts.append(text))
            self.assertFalse(good.exists())
        self.assertIn(i18n.t('installer.progress.cleaning'), texts)
        self.assertNotIn(waiting, texts)

    def test_install_aborts_when_cleanup_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(installer, 'cleanup_existing_zbox',
                              side_effect=RuntimeError('busy')) as cleanup, \
                    patch.object(installer, '_copy_tree_with_progress') as copy, \
                    patch.object(installer, '_gen_icon') as icon, \
                    patch.object(installer.sysutil, 'context_menu_install') as menu, \
                    patch.object(installer.sysutil, 'uninstall_reg_install') as reg:
                with self.assertRaises(RuntimeError):
                    installer.install(str(Path(tmp) / 'zbox'), all_users=True)
            cleanup.assert_called_once()
            copy.assert_not_called()
            icon.assert_not_called()
            menu.assert_not_called()
            reg.assert_not_called()

    def test_desktop_shortcut_uses_brand_name_and_removes_legacy(self):
        self.assertEqual(installer.SHORTCUT_NAME, 'Zbox')
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'Zbox.lnk').write_text('x', encoding='utf-8')
            Path(tmp, 'Zbox桌面格子.lnk').write_text('x', encoding='utf-8')
            with patch.object(installer, '_desktop_dir', return_value=tmp):
                installer.remove_desktop_shortcut()
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_uninstall_reg_language_round_trip(self):
        store = {}

        class _Key:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_set(_key, name, _reserved, _vtype, value):
            store[name] = value

        with patch.object(sysutil.winreg, 'CreateKey', return_value=_Key()), \
                patch.object(sysutil.winreg, 'SetValueEx', side_effect=fake_set), \
                patch.object(sysutil, '_get',
                             side_effect=lambda _root, _path, name: store.get(name)):
            sysutil.uninstall_reg_install(r'C:\Program Files\zbox\zbox.exe',
                                          all_users=True, size_kb=1, language='en-US')
            self.assertEqual(sysutil.installed_language(True), 'en-US')
        self.assertEqual(store['Language'], 'en-US')

    def test_uninstall_reg_omits_empty_language(self):
        store = {}

        class _Key:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_set(_key, name, _reserved, _vtype, value):
            store[name] = value

        with patch.object(sysutil.winreg, 'CreateKey', return_value=_Key()), \
                patch.object(sysutil.winreg, 'SetValueEx', side_effect=fake_set), \
                patch.object(sysutil.winreg, 'DeleteValue') as delete_value:
            sysutil.uninstall_reg_install(r'C:\Program Files\zbox\zbox.exe',
                                          all_users=True, size_kb=1, language='')
        self.assertNotIn('Language', store)
        delete_value.assert_called_once_with(ANY, 'Language')

    def test_language_from_args_falls_back_to_system_for_invalid_value(self):
        with patch('i18n.detect_system_language', return_value=i18n.ZH):
            self.assertEqual(installer.language_from_args(['app', '--lang']), i18n.ZH)
            self.assertEqual(installer.language_from_args(['app', '--lang', '']), i18n.ZH)
            self.assertEqual(installer.language_from_args(['app']), i18n.ZH)
        self.assertEqual(installer.language_from_args(['app', '--lang', 'en-US']), i18n.EN)

    def test_relaunch_elevated_prepends_script_in_source_mode(self):
        import ctypes
        with patch.object(ctypes.windll.shell32, 'ShellExecuteW', return_value=33) as shell:
            self.assertTrue(installer.relaunch_elevated(
                ['--install-elevated', r'C:\Program Files\zbox']))
        params = shell.call_args[0][3]
        self.assertIn(os.path.abspath(sys.argv[0]), params)
        self.assertTrue(params.index(os.path.abspath(sys.argv[0])) <
                        params.index('--install-elevated'))
        self.assertIn('--install-elevated', params)
        self.assertIn('"C:\\Program Files\\zbox"', params)

    def test_setup_main_applies_lang_argument(self):
        i18n.set_language(i18n.ZH)
        try:
            with patch.object(installer, 'InstallWizard') as wizard, \
                    patch.object(sys, 'argv', ['zbox-setup.exe', '--lang', 'en-US']), \
                    patch.dict(os.environ, {'ZBOX_AUTO_INSTALL': ''}):
                installer.setup_main()
            wizard.return_value.exec.assert_called_once()
            self.assertEqual(i18n.get_language(), 'en-US')
        finally:
            i18n.set_language(i18n.DEFAULT_LANGUAGE)


class InstallerWizardLanguageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def tearDown(self):
        installer.install_qt_translator(self.qapp, i18n.EN)
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def _visible_texts(self, widget):
        texts = [widget.windowTitle()]
        for cls in (QLabel, QPushButton, QCheckBox, QToolButton):
            texts.extend(w.text() for w in widget.findChildren(cls))
        return texts

    def test_install_wizard_english_has_no_chinese_literals(self):
        i18n.set_language(i18n.EN)
        wizard = installer.InstallWizard()
        try:
            offenders = [x for x in self._visible_texts(wizard) if _has_chinese(x)]
            self.assertEqual(offenders, [])
            self.assertEqual(wizard.windowTitle(), 'Zbox Desktop Boxes')
        finally:
            wizard.deleteLater()

    def test_uninstall_wizard_english_has_no_chinese_literals(self):
        i18n.set_language(i18n.EN)
        wizard = installer.UninstallWizard()
        try:
            offenders = [x for x in self._visible_texts(wizard) if _has_chinese(x)]
            self.assertEqual(offenders, [])
        finally:
            wizard.deleteLater()

    def test_language_selector_switches_wizard_text(self):
        i18n.set_language(i18n.ZH)
        wizard = installer.InstallWizard()
        try:
            combo = wizard.findChild(QComboBox, 'installLanguage')
            self.assertIsNotNone(combo)
            wizard.show()
            self.qapp.processEvents()
            self.assertEqual([combo.itemText(i) for i in range(combo.count())],
                             ['简体中文', 'English'])
            self.assertEqual(combo.currentData(), i18n.ZH)
            self.assertEqual(combo.width(), installer._sc(150))
            self.assertGreater(combo.geometry().x(), wizard._language_label.geometry().x())
            self.assertLess(abs(combo.geometry().center().y()
                                - wizard._language_label.geometry().center().y()),
                            installer._sc(4))
            combo.setCurrentIndex(combo.findData(i18n.EN))
            self.assertEqual(i18n.get_language(), i18n.EN)
            labels = [w.text() for w in wizard.findChildren(QLabel)]
            self.assertIn('Install location', labels)
        finally:
            wizard.deleteLater()

    def test_qt_translator_follows_language_switch(self):
        from PySide6.QtCore import QCoreApplication
        i18n.set_language(i18n.EN)
        installer.install_qt_translator(self.qapp, i18n.EN)
        english = QCoreApplication.translate('QLineEdit', '&Copy')
        i18n.set_language(i18n.ZH)
        self.assertIsNotNone(installer.install_qt_translator(self.qapp, i18n.ZH))
        chinese = QCoreApplication.translate('QLineEdit', '&Copy')
        self.assertNotEqual(english, chinese)
        # 切回英文：旧 translator 被摘掉，文案回到 Qt 默认
        self.assertIsNone(installer.install_qt_translator(self.qapp, i18n.EN))
        self.assertEqual(QCoreApplication.translate('QLineEdit', '&Copy'), english)

    @staticmethod
    def _content_width():
        """卡片内容区宽度（设计 442px）：窗口宽减去卡片与页面的左右边距。
        与 `_sc(442)` 逐项取整结果可能差 1px（125% 下为 553 vs 552），
        按布局同一套缩放常量推导才与实际控件宽度严格一致。"""
        return (installer._sc(480) - installer._sc(18) - installer._sc(14)
                - installer._sc(2) - installer._sc(4))

    def test_english_space_messages_wrap_without_clipping(self):
        i18n.set_language(i18n.EN)
        # 按 125% DPI 构造：可用宽度必须随 DPI 放大，断言不能写死像素
        with patch('app.ui_scale', return_value=1.25):
            wizard = installer.InstallWizard()
            limit = self._content_width()
        try:
            self.assertTrue(wizard._space.wordWrap())
            wizard.show()
            self.qapp.processEvents()
            cases = [
                ('installer.space_info', dict(need='100 MB', free='10 GB', drive='C:')),
                ('installer.err.not_empty', {}),
                ('installer.err.space', dict(need='100 MB', free='1 MB', drive='C:')),
            ]
            for key, kwargs in cases:
                wizard._space.setText(i18n.t(key, **kwargs))
                wizard._space.updateGeometry()
                wizard.adjustSize()
                self.qapp.processEvents()
                self.assertLessEqual(wizard._space.width(), limit, key)
                self.assertGreaterEqual(
                    wizard._space.height(),
                    wizard._space.heightForWidth(wizard._space.width()), key)
        finally:
            wizard.deleteLater()

    def test_english_uninstall_texts_fit_or_wrap(self):
        i18n.set_language(i18n.EN)
        with patch('app.ui_scale', return_value=1.25):
            wizard = installer.UninstallWizard()
            limit = self._content_width()
        try:
            wizard.show()
            self.qapp.processEvents()
            fm = wizard._del_data.fontMetrics()
            self.assertLessEqual(
                fm.horizontalAdvance(wizard._del_data.text()), limit)
            desc = next(w for w in wizard.findChildren(QLabel) if w.wordWrap())
            self.assertLessEqual(desc.width(), limit)
            self.assertGreaterEqual(desc.height(), desc.heightForWidth(desc.width()))
        finally:
            wizard.deleteLater()

    def test_language_selector_passes_language_to_elevated_install(self):
        i18n.set_language(i18n.EN)
        wizard = installer.InstallWizard()
        try:
            with patch.object(installer, 'is_admin', return_value=False), \
                    patch.object(installer, 'relaunch_elevated', return_value=True) as relaunch, \
                    patch.object(wizard, 'accept'):
                wizard._on_install()
            args = relaunch.call_args[0][0]
            self.assertIn('--install-elevated', args)
            self.assertIn('--lang', args)
            self.assertEqual(args[args.index('--lang') + 1], 'en-US')
        finally:
            wizard.deleteLater()


if __name__ == '__main__':
    unittest.main()
