# -*- coding: utf-8 -*-
"""截图翻译核心纯逻辑测试：OCR 协议解析、语言判断、段落聚类、豆包译文解析、排版。"""
import json
import unittest

import translation_core as tc


def _region(text, x, y, w, h, confidence=0.99):
    return {
        'text': text,
        'confidence': confidence,
        'quad': [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        'bbox': [x, y, w, h],
    }


class OcrProtocolTest(unittest.TestCase):
    def test_parse_valid_payload(self):
        payload = json.dumps({
            'version': 1,
            'regions': [_region('Hello', 10, 20, 50, 16)],
        }).encode('utf-8')
        regions = tc.parse_ocr_payload(payload)
        self.assertEqual(len(regions), 1)
        r = regions[0]
        self.assertEqual(r.text, 'Hello')
        self.assertAlmostEqual(r.confidence, 0.99)
        self.assertEqual(r.bbox, (10, 20, 50, 16))

    def test_parse_applies_dpr_scale(self):
        payload = json.dumps({
            'version': 1,
            'regions': [_region('Hi', 20, 40, 60, 20)],
        })
        regions = tc.parse_ocr_payload(payload, scale=0.5)
        self.assertEqual(regions[0].bbox, (10, 20, 30, 10))
        self.assertEqual(regions[0].quad[0], (10.0, 20.0))

    def test_rejects_wrong_version(self):
        payload = json.dumps({'version': 2, 'regions': []})
        with self.assertRaises(tc.OcrProtocolError):
            tc.parse_ocr_payload(payload)

    def test_rejects_malformed_region(self):
        payload = json.dumps({'version': 1, 'regions': [{'text': 'x'}]})
        with self.assertRaises(tc.OcrProtocolError):
            tc.parse_ocr_payload(payload)

    def test_rejects_non_json(self):
        with self.assertRaises(tc.OcrProtocolError):
            tc.parse_ocr_payload('not json at all')

    def test_empty_regions_ok(self):
        regions = tc.parse_ocr_payload(json.dumps({'version': 1, 'regions': []}))
        self.assertEqual(regions, [])


class LanguageDetectTest(unittest.TestCase):
    def test_chinese_text(self):
        self.assertEqual(tc.detect_lang('你好世界，这是一段中文'), 'zh')

    def test_english_text(self):
        self.assertEqual(tc.detect_lang('Hello world, this is English'), 'en')

    def test_mixed_majority_chinese(self):
        self.assertEqual(tc.detect_lang('这是中文 mostly 中文内容 ok'), 'zh')

    def test_mixed_majority_english(self):
        self.assertEqual(tc.detect_lang('English words 中文 hello world test'), 'en')

    def test_empty_or_digits(self):
        self.assertEqual(tc.detect_lang(''), 'other')
        self.assertEqual(tc.detect_lang('12345 !!!'), 'other')

    def test_target_language_from_ui(self):
        self.assertEqual(tc.target_language('zh-CN'), 'zh')
        self.assertEqual(tc.target_language('en-US'), 'en')

    def test_should_translate(self):
        self.assertTrue(tc.should_translate('en', 'zh'))
        self.assertTrue(tc.should_translate('zh', 'en'))
        self.assertFalse(tc.should_translate('zh', 'zh'))
        self.assertFalse(tc.should_translate('en', 'en'))
        self.assertFalse(tc.should_translate('other', 'zh'))


class ClusterTest(unittest.TestCase):
    def test_reading_order_top_to_bottom_left_to_right(self):
        regions = [
            tc.OcrRegion('right', 0.9, None, (100, 0, 50, 10)),
            tc.OcrRegion('left', 0.9, None, (0, 0, 50, 10)),
            tc.OcrRegion('second', 0.9, None, (0, 20, 60, 10)),
        ]
        ordered = tc.reading_order(regions)
        self.assertEqual([r.text for r in ordered], ['left', 'right', 'second'])

    def test_lines_grouped_into_paragraphs(self):
        regions = [
            tc.OcrRegion('line one', 0.9, None, (10, 10, 100, 14)),
            tc.OcrRegion('line two', 0.9, None, (10, 26, 100, 14)),
            tc.OcrRegion('far away', 0.9, None, (10, 120, 100, 14)),
        ]
        paras = tc.cluster_paragraphs(regions)
        self.assertEqual(len(paras), 2)
        self.assertEqual([l.text for l in paras[0].lines], ['line one', 'line two'])
        self.assertEqual([l.text for l in paras[1].lines], ['far away'])
        self.assertEqual(paras[0].rect, (10, 10, 100, 30))

    def test_paragraph_text_joined(self):
        regions = [
            tc.OcrRegion('第一行', 0.9, None, (0, 0, 80, 14)),
            tc.OcrRegion('第二行', 0.9, None, (0, 16, 80, 14)),
        ]
        paras = tc.cluster_paragraphs(regions)
        self.assertEqual(paras[0].text, '第一行\n第二行')


class DoubaoReplyParseTest(unittest.TestCase):
    def test_parse_numbered_json_reply(self):
        reply = '```json\n[{"id": 1, "text": "你好"}, {"id": 2, "text": "世界"}]\n```'
        out = tc.parse_translations(reply, 2)
        self.assertEqual(out, ['你好', '世界'])

    def test_parse_plain_json(self):
        reply = '[{"id": 1, "text": "hi"}]'
        self.assertEqual(tc.parse_translations(reply, 1), ['hi'])

    def test_missing_id_rejected(self):
        reply = '[{"id": 1, "text": "hi"}]'
        with self.assertRaises(tc.TranslationParseError):
            tc.parse_translations(reply, 2)

    def test_extra_id_rejected(self):
        reply = '[{"id": 1, "text": "a"}, {"id": 2, "text": "b"}]'
        with self.assertRaises(tc.TranslationParseError):
            tc.parse_translations(reply, 1)

    def test_non_json_rejected(self):
        with self.assertRaises(tc.TranslationParseError):
            tc.parse_translations('好的，翻译如下：你好', 1)

    def test_empty_text_rejected(self):
        reply = '[{"id": 1, "text": "  "}]'
        with self.assertRaises(tc.TranslationParseError):
            tc.parse_translations(reply, 1)

    def test_prompt_contains_numbered_items_and_json_only_instruction(self):
        prompt = tc.build_prompt(['Hello', 'World'], 'zh')
        self.assertIn('"id": 1', prompt)
        self.assertIn('Hello', prompt)
        self.assertIn('World', prompt)
        self.assertIn('JSON', prompt)
        self.assertEqual(prompt.count('Hello'), 1)


class LayoutTest(unittest.TestCase):
    def _measure(self, text, size, width):
        """模拟度量：每字符宽 size*0.6，行高 size*1.3，返回 (行数, 总高)。"""
        char_w = size * 0.6
        per_line = max(1, int(width / char_w))
        lines = 0
        for para in text.split('\n'):
            lines += max(1, -(-len(para) // per_line))
        return lines, lines * size * 1.3

    def test_fit_keeps_base_size_when_fits(self):
        size, lines = tc.fit_text('short', 200, 100, base=14, minimum=8,
                                  measure=self._measure)
        self.assertEqual(size, 14)
        self.assertEqual(lines, 1)

    def test_fit_shrinks_until_fits(self):
        size, _lines = tc.fit_text('a very long line of english text that wraps',
                                   120, 60, base=18, minimum=8, measure=self._measure)
        self.assertLess(size, 18)
        self.assertGreaterEqual(size, 8)

    def test_fit_floors_at_minimum(self):
        size, _lines = tc.fit_text('x' * 500, 40, 20, base=18, minimum=8,
                                   measure=self._measure)
        self.assertEqual(size, 8)

    def test_mosaic_rect_expands_and_clips(self):
        rect = tc.mosaic_rect((10, 10, 50, 16), expand=3, bounds=(0, 0, 100, 100))
        self.assertEqual(rect, (7, 7, 56, 22))
        rect = tc.mosaic_rect((0, 0, 20, 10), expand=5, bounds=(0, 0, 100, 100))
        self.assertEqual(rect, (0, 0, 25, 15))


if __name__ == '__main__':
    unittest.main()