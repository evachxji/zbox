# -*- coding: utf-8 -*-
"""崩溃诊断报告核心测试。"""
import ctypes
import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import crash_report


class CrashReportTest(unittest.TestCase):
    def test_sanitize_text_removes_home_and_username(self):
        text = r'Traceback C:\Users\alice\demo\main.py: alice failed'
        with patch.dict(os.environ, {'USERPROFILE': r'C:\Users\alice', 'USERNAME': 'alice'}):
            result = crash_report.sanitize_text(text)
        self.assertNotIn(r'C:\Users\alice', result)
        self.assertNotIn('alice', result)
        self.assertIn('<UserProfile>', result)
        self.assertIn('<User>', result)

    def test_report_dirs_never_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime(2026, 10, 28, 12, 0, 0)
            one = crash_report.create_report_dir(tmp, now=now, pid=42)
            two = crash_report.create_report_dir(tmp, now=now, pid=42)
            self.assertNotEqual(one, two)
            self.assertTrue(os.path.isdir(one))
            self.assertTrue(os.path.isdir(two))

    def test_system_info_has_only_approved_fields(self):
        info = crash_report.system_info()
        self.assertEqual(set(info), {
            'Zbox', 'Runtime', 'Architecture', 'Python',
            'Windows', 'Windows build', 'System architecture',
        })
        self.assertNotIn('Computer name', info)
        self.assertNotIn('Username', info)

    def test_python_report_contains_trace_and_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = crash_report.create_report_dir(tmp)
            path = crash_report.write_report(
                report_dir, python_trace='ValueError: bad\nTraceback line',
                native_trace='', native_error='', dump_error='',
                qt_version='6.8.3', pyside_version='6.8.3')
            with open(path, encoding='utf-8') as f:
                text = f.read()
            self.assertIn('ValueError: bad', text)
            self.assertIn('Traceback line', text)
            self.assertIn('Qt: 6.8.3', text)
            self.assertIn('PySide6: 6.8.3', text)

    def test_issue_url_prefills_metadata_but_not_trace(self):
        url = crash_report.build_issue_url('ValueError: bad', True, True)
        query = parse_qs(urlparse(url).query)
        self.assertEqual(urlparse(url).path, '/evachxji/zbox/issues/new')
        self.assertIn('ValueError', query['title'][0])
        self.assertIn('Reproduction steps', query['body'][0])
        self.assertIn('memory', query['body'][0])
        self.assertNotIn('Traceback', url)

    def test_write_real_minidump(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'zbox-crash.dmp')
            crash_report.write_minidump(path)
            with open(path, 'rb') as f:
                self.assertEqual(f.read(4), b'MDMP')
            self.assertGreater(os.path.getsize(path), 1024)

    def test_python_exception_writes_raw_trace_and_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                raise ValueError('bad value')
            except ValueError:
                import sys
                report_dir = crash_report.report_python_exception(
                    *sys.exc_info(), data_dir=tmp, launch=False)
            with open(os.path.join(report_dir, 'python.txt'), encoding='utf-8') as f:
                self.assertIn('ValueError: bad value', f.read())
            with open(os.path.join(report_dir, 'zbox-crash.dmp'), 'rb') as f:
                self.assertEqual(f.read(4), b'MDMP')

    def test_reporter_command_uses_current_executable_and_early_mode(self):
        with patch.object(crash_report.sys, 'argv', ['main.pyw']), \
                patch.object(crash_report.sys, 'executable', r'C:\Python\pythonw.exe'), \
                patch.object(crash_report, 'BASE_DIR', r'D:\zbox', create=True):
            cmd = crash_report.reporter_command(r'C:\report', 'native.log', 12)
        self.assertEqual(cmd[1:3], [r'D:\zbox\main.pyw', '--crash-reporter'])
        self.assertIn('--native-offset', cmd)
    def _native_pointers(self):
        record = crash_report.EXCEPTION_RECORD(
            ExceptionCode=0xC0000005, ExceptionAddress=0x12345678)
        pointers = crash_report.EXCEPTION_POINTERS(
            ExceptionRecord=ctypes.pointer(record), ContextRecord=None)
        return record, pointers

    def test_native_filter_writes_exception_and_launches_reporter(self):
        record, pointers = self._native_pointers()
        with tempfile.TemporaryDirectory() as tmp:
            native_path = os.path.join(tmp, 'crash_native.log')
            with open(native_path, 'a', encoding='utf-8') as native_log, \
                    patch.object(crash_report, '_set_filter', return_value=None), \
                    patch.object(crash_report, 'write_minidump') as dump, \
                    patch.object(crash_report, 'launch_reporter') as launch:
                crash_report.install_native_handler(tmp, native_log, 0)
                result = crash_report._native_callback(ctypes.byref(pointers))
                report_dir = launch.call_args[0][0]
                self.assertEqual(result, 1)
                dump.assert_called_once()
                with open(os.path.join(report_dir, 'native.json'), encoding='utf-8') as f:
                    info = json.load(f)
                self.assertEqual(info['code'], '0xC0000005')
                self.assertEqual(info['address'], '0x12345678')

    def test_native_filter_still_launches_when_dump_fails(self):
        record, pointers = self._native_pointers()
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'native.log'), 'a', encoding='utf-8') as native_log, \
                    patch.object(crash_report, '_set_filter', return_value=None), \
                    patch.object(crash_report, 'write_minidump', side_effect=OSError('dump failed')), \
                    patch.object(crash_report, 'launch_reporter') as launch:
                crash_report.install_native_handler(tmp, native_log, 0)
                self.assertEqual(crash_report._native_callback(ctypes.byref(pointers)), 1)
                launch.assert_called_once()
                report_dir = launch.call_args[0][0]
                with open(os.path.join(report_dir, 'dump_error.txt'), encoding='utf-8') as f:
                    self.assertIn('dump failed', f.read())

if __name__ == '__main__':
    unittest.main()
