# -*- coding: utf-8 -*-
"""崩溃诊断报告核心测试。"""
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


if __name__ == '__main__':
    unittest.main()
