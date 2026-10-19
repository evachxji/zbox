# -*- coding: utf-8 -*-
"""农历显示开关：默认值、设置持久化与日期格副标题行为。"""
import os
import tempfile
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QCheckBox, QWidget

import app as app_module
import i18n
from app import Config, DayCell, SettingsDialog


class _PanelStub(QWidget):
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

    def __init__(self):
        super(_PanelStub, self).__init__()
        self.cal = MagicMock()

    def apply_theme(self, _key):
        pass


class _EmptyStore(object):
    @staticmethod
    def info(_d):
        return None, None


class _HolidayStore(object):
    @staticmethod
    def info(_d):
        return '国庆', 'off'


class CalendarLunarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        i18n.set_language(i18n.ZH)

    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_default_on_and_toggle_persists_and_refreshes_calendar(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            panel = _PanelStub()
            self.addCleanup(panel.close)
            panel.cfg = Config(path)
            with patch('app.sysutil.autostart_get', return_value=False):
                dlg = SettingsDialog(panel, lambda *a, **k: None, lambda: None)
            self.addCleanup(dlg.close)
            chk = dlg.findChild(QCheckBox, 'showLunarChk')
            self.assertTrue(chk.isChecked())

            chk.setChecked(False)
            self.assertFalse(panel.cfg.data['show_lunar'])
            self.assertFalse(Config(path).data['show_lunar'])
            panel.cal.refresh.assert_called_once_with()
        finally:
            os.unlink(path)

    def test_hidden_lunar_keeps_statutory_holiday_name(self):
        d = date(2026, 10, 15)
        cell = DayCell()
        self.addCleanup(cell.deleteLater)
        cell.resize(app_module.sc(40), app_module.sc(48))

        cell.set_day(d, False, _EmptyStore(), show_lunar=False)
        self.assertEqual(cell._sub_full, '')

        cell.set_day(d, False, _HolidayStore(), show_lunar=False)
        self.assertEqual(cell._sub_full, '国庆')

        cell.set_day(d, False, _EmptyStore(), show_lunar=True)
        self.assertEqual(cell._sub_full, '初六')


if __name__ == '__main__':
    unittest.main()
