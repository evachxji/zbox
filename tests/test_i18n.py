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

    def test_zh_and_en_catalogs_have_identical_keys(self):
        import i18n_en
        import i18n_zh
        self.assertEqual(set(i18n_zh.CATALOG), set(i18n_en.CATALOG))

    def test_zh_and_en_placeholder_fields_match(self):
        import string
        import i18n_en
        import i18n_zh

        def fields(text):
            return {name for _lit, name, _spec, _conv
                    in string.Formatter().parse(text) if name is not None}

        for key, zh_text in i18n_zh.CATALOG.items():
            self.assertEqual(fields(zh_text), fields(i18n_en.CATALOG[key]), key)

    def test_missing_key_falls_back_to_key(self):
        i18n.set_language('en-US')
        self.assertEqual(i18n.t('no.such.key'), 'no.such.key')

    def test_data_values_translate_and_fall_back(self):
        i18n.set_language('en-US')
        self.assertEqual(i18n.t_data('春节'), 'Spring Festival')
        i18n.set_language('zh-CN')
        self.assertEqual(i18n.t_data('春节'), '春节')
        self.assertEqual(i18n.t_data('自定义节日'), '自定义节日')
        self.assertEqual(i18n.t_data(''), '')
        self.assertIsNone(i18n.t_data(None))


if __name__ == '__main__':
    unittest.main()
