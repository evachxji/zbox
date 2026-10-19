# -*- coding: utf-8 -*-
"""PC 语言核心的回归测试：语言归一、解析、翻译与系统语言探测。"""
import unittest
from unittest.mock import patch

import i18n


class I18nCoreTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_normalize_language(self):
        self.assertEqual(i18n.normalize_language('zh_CN'), 'zh-CN')
        self.assertEqual(i18n.normalize_language('en-GB'), 'en-US')
        self.assertEqual(i18n.normalize_language('ja'), 'en-US')
        self.assertIsNone(i18n.normalize_language(''))

    def test_resolution_prefers_first_valid_candidate(self):
        self.assertEqual(i18n.resolve_language('en-US', 'zh-CN', 'en-US'), 'en-US')
        self.assertEqual(i18n.resolve_language('', 'zh-CN', 'en-US'), 'zh-CN')
        self.assertEqual(i18n.resolve_language('', '', ''), 'zh-CN')

    def test_translation_formats_and_falls_back(self):
        i18n.set_language('en-US')
        self.assertEqual(i18n.t('settings.version', version='1.2.3'), 'Version 1.2.3')
        i18n.set_language('zh-CN')
        self.assertEqual(i18n.t('settings.version', version='1.2.3'), '版本 v1.2.3')

    @patch('i18n._windows_ui_language', return_value='zh-HK')
    def test_detection_maps_chinese_variants_to_simplified(self, _ui_lang):
        self.assertEqual(i18n.detect_system_language(), 'zh-CN')


if __name__ == '__main__':
    unittest.main()
