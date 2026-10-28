# -*- coding: utf-8 -*-
"""独立崩溃报告弹窗测试。"""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

import crash_reporter
from i18n import t


class CrashReporterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name in ('zbox-crash.log', 'zbox-crash.dmp'):
            with open(os.path.join(self.tmp.name, name), 'wb') as f:
                f.write(b'x')
        self.dialog = crash_reporter.CrashDialog(self.tmp.name, 'nocturne')
        self.addCleanup(self.dialog.close)

    def test_window_uses_real_zbox_icon_and_file_status(self):
        self.assertFalse(self.dialog.windowIcon().isNull())
        self.assertEqual(self.dialog.log_status.text(), t('crash.log_ready'))
        self.assertEqual(self.dialog.dump_status.text(), t('crash.dump_ready'))

    def test_copy_button_copies_full_report_directory(self):
        self.dialog.copy_btn.click()
        self.assertEqual(self.qapp.clipboard().text(), self.tmp.name)

    def test_open_directory_uses_local_file_url(self):
        with patch.object(crash_reporter.QDesktopServices, 'openUrl') as open_url:
            self.dialog.open_btn.click()
        self.assertTrue(open_url.call_args[0][0].isLocalFile())

    def test_issue_button_does_not_put_log_contents_in_url(self):
        with patch.object(crash_reporter.QDesktopServices, 'openUrl') as open_url:
            self.dialog.issue_btn.click()
        url = open_url.call_args[0][0].url()
        self.assertIn('/issues/new?', url)
        self.assertNotIn('Traceback', url)

    def test_path_uses_info_text_theme_role(self):
        self.assertEqual(self.dialog.path_label.objectName(), 'infoText')


class CrashMainIntegrationTest(unittest.TestCase):
    def test_reporter_dispatch_precedes_panel_import_and_ipc(self):
        from pathlib import Path
        source = (Path(crash_reporter.BASE_DIR) / 'main.pyw').read_text(encoding='utf-8-sig')
        dispatch = source.index("if sys.argv[1:2] == ['--crash-reporter']:")
        self.assertLess(dispatch, source.index('import app as ui'))
        self.assertLess(dispatch, source.index('def notify_existing'))

    def test_python_hook_reports_then_exits(self):
        import main
        with patch.object(main.crash_report, 'report_python_exception') as report, \
                patch.object(main.os, '_exit') as exit_process:
            main._crash_excepthook(ValueError, ValueError('bad'), None)
        report.assert_called_once()
        exit_process.assert_called_once_with(1)

if __name__ == '__main__':
    unittest.main()
