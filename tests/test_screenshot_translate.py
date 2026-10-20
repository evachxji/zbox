# -*- coding: utf-8 -*-
"""截图翻译按钮与 ShotOverlay 翻译状态机的界面回归测试（OCR/豆包均注入假货）。"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import screenshot
import translation_core as tc
from screenshot import ShotOverlay


class _Cfg:
    def __init__(self):
        self.data = {'theme': 'nocturne'}

    def save(self):
        pass


def _pin_image(w=320, h=200):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor('#f5f0e6'))
    return img


class _FakeTranslator:
    """同步应答的豆包替身：与 DoubaoSession 同接口。"""

    next_result = None     # list[str] → on_done；Exception → on_error
    next_error = None
    instances = []

    def __init__(self):
        self.on_login_required = None
        _FakeTranslator.instances.append(self)

    def translate(self, texts, target, on_done, on_error):
        self.texts = texts
        if _FakeTranslator.next_error is not None:
            on_error(_FakeTranslator.next_error)
        else:
            on_done(_FakeTranslator.next_result)

    def cancel(self):
        pass


class TranslateToolbarTest(unittest.TestCase):
    def test_translate_in_toolbar_spec_not_pin_excluded(self):
        self.assertIn('translate', screenshot.SHOT_TOOLBAR_KINDS)
        self.assertNotIn('translate', screenshot.PIN_TOOLBAR_EXCLUDED)
        # 独立分组，紧跟标注工具组之后
        groups = [[k for k, _t in g] for g in screenshot.SHOT_TOOLBAR_GROUPS]
        self.assertEqual(groups[1], ['translate'])


class TranslateFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        _FakeTranslator.next_result = ['译文一', '译文二']
        _FakeTranslator.next_error = None
        _FakeTranslator.instances = []
        self.overlay = ShotOverlay(_Cfg(), pin_image=_pin_image(), pin_pos=QPoint(0, 0))
        self.overlay.show()
        self.qapp.processEvents()
        self.addCleanup(self.overlay.close)
        # 注入假货：OCR 同步返回两行英文，翻译同步返回译文
        regions = [
            tc.OcrRegion('hello', 0.99, None, (20, 20, 60, 12)),
            tc.OcrRegion('world', 0.99, None, (20, 40, 60, 12)),
        ]
        ready = patch('ocr_runtime.ocr_ready', return_value=True)
        ready.start()
        self.addCleanup(ready.stop)
        self.overlay._run_ocr_job = lambda job: job()
        self._regions = regions
        self.overlay._ocr_recognize = lambda png, cancel: list(self._regions)
        self.overlay._make_translator = _FakeTranslator

    def _translate(self):
        self.overlay._toggle_translate()
        self.qapp.processEvents()

    def _wait_layer(self, timeout=10.0):
        """等后台线程把翻译图层构建好。

        2026-10 性能审计 P1-12：图层构建（4K 选区 132MB 分配 + 逐像素采样 +
        逐字符字体度量）原先在 paintEvent 里做，会把 GUI 线程冻住 0.2~1 秒；
        改为后台线程构建、完成后经信号回主线程回填 —— 所以「ready」之后
        图层还要等一小会儿才出现。
        """
        import time
        t0 = time.time()
        while time.time() - t0 < timeout:
            self.qapp.processEvents()
            st = self.overlay._tl8n
            if st and st.get('layer') is not None:
                return st['layer']
            time.sleep(0.01)
        return None

    def test_pin_overlay_has_translate_button(self):
        self.assertIn('translate', self.overlay._toolbar_btns)

    def test_happy_flow_reaches_ready_and_paints_layer(self):
        before = self.overlay.grab().toImage()
        self._translate()
        st = self.overlay._tl8n
        self.assertEqual(st['state'], 'ready')
        self.assertTrue(st['visible'])
        self.assertEqual(st['translations'], ['译文一', '译文二'])
        self.assertIsNotNone(self._wait_layer(), '后台线程应把翻译图层建好')
        after = self.overlay.grab().toImage()
        self.assertNotEqual(before.constBits().tobytes(),
                            after.constBits().tobytes())

    def test_translator_received_paragraph_texts(self):
        self._translate()
        session = _FakeTranslator.instances[0]
        self.assertEqual(session.texts, ['hello\nworld'])

    def test_toggle_hides_layer_and_restores(self):
        before = self.overlay.grab().toImage()
        self._translate()
        self._translate()   # 再点 = 显示原文
        st = self.overlay._tl8n
        self.assertFalse(st['visible'])
        hidden = self.overlay.grab().toImage()
        self.assertEqual(before.constBits().tobytes(),
                         hidden.constBits().tobytes())

    def test_export_flattens_translation(self):
        plain = self.overlay._result_image()
        self._translate()
        out = self.overlay._result_image()
        self.assertNotEqual(plain.constBits().tobytes(),
                            out.constBits().tobytes())

    def test_no_text_state(self):
        self._regions = []
        self._translate()
        self.assertEqual(self.overlay._tl8n['state'], 'no_text')
        import i18n
        self.assertEqual(self.overlay.tl8n_label.text(), i18n.t('shot.translate.no_text'))

    def test_same_language_skips_translation(self):
        self._regions = [tc.OcrRegion('你好世界', 0.99, None, (20, 20, 60, 12))]
        self._translate()
        self.assertEqual(self.overlay._tl8n['state'], 'same_lang')
        self.assertEqual(_FakeTranslator.instances, [])

    def test_unsupported_arch(self):
        with patch('ocr_runtime.supported', return_value=False):
            self._translate()
        self.assertEqual(self.overlay._tl8n['state'], 'unsupported')

    def test_translation_error_keeps_image(self):
        import doubao_web
        _FakeTranslator.next_error = doubao_web.DoubaoNetworkError('x')
        before = self.overlay._result_image()
        self._translate()
        self.assertEqual(self.overlay._tl8n['state'], 'error')
        # 导出图内容不受失败影响（遮罩上会多一个持续可见的失败气泡，那是 chrome）
        after = self.overlay._result_image()
        self.assertEqual(before.constBits().tobytes(),
                         after.constBits().tobytes())

    def test_selection_change_drops_layer(self):
        self._translate()
        self.overlay._sel = QRect(10, 10, 100, 100)
        self.overlay._translate_sel_guard()
        self.assertIsNone(self.overlay._tl8n)

    def test_translator_creation_failure_goes_error(self):
        def boom():
            raise RuntimeError('webengine broken')
        self.overlay._make_translator = boom
        self._translate()
        self.assertEqual(self.overlay._tl8n['state'], 'error')

    def test_status_label_hidden_when_idle_and_ready(self):
        self.assertFalse(self.overlay.tl8n_label.isVisibleTo(self.overlay))
        self._translate()
        self.assertEqual(self.overlay._tl8n['state'], 'ready')
        self.assertFalse(self.overlay.tl8n_label.isVisibleTo(self.overlay))

    def test_status_label_shows_error_text(self):
        import doubao_web
        _FakeTranslator.next_error = doubao_web.DoubaoNetworkError('x')
        self._translate()
        self.assertTrue(self.overlay.tl8n_label.isVisibleTo(self.overlay))
        import i18n
        self.assertEqual(self.overlay.tl8n_label.text(), i18n.t('shot.translate.failed'))

    def test_progress_stage_updates_label(self):
        import i18n
        self.overlay._tl8n = {'state': 'preparing', 'sel': self.overlay._sel,
                              'cancel': None, 'session': None}
        self.overlay._on_tl8n('progress', 'shot.translate.recognizing')
        self.assertEqual(self.overlay.tl8n_label.text(),
                         i18n.t('shot.translate.recognizing'))

    def test_component_missing_opens_guide_instead_of_pipeline(self):
        from unittest.mock import MagicMock, patch as _patch
        ready = {'v': False}
        dlg = MagicMock()
        dlg.exec_.return_value = 0   # 用户直接关掉，没下载
        with _patch('ocr_runtime.ocr_ready', lambda: ready['v']), \
             _patch('translate_guide.TranslateGuideDialog', MagicMock(return_value=dlg)):
            self.overlay._tl8n = None
            self.overlay._toggle_translate()
            self.qapp.processEvents()
            self.assertIsNone(self.overlay._tl8n)   # 未进入流水线
            dlg.exec_.assert_called_once()

    def test_guide_completed_continues_pipeline(self):
        from unittest.mock import MagicMock, patch as _patch
        ready = {'v': False}
        dlg = MagicMock()
        dlg.exec_.return_value = 0

        def fake_exec():
            ready['v'] = True   # 用户在引导窗里完成了下载
            return 0
        dlg.exec_.side_effect = fake_exec
        with _patch('ocr_runtime.ocr_ready', lambda: ready['v']), \
             _patch('translate_guide.TranslateGuideDialog', MagicMock(return_value=dlg)):
            self.overlay._tl8n = None
            self.overlay._toggle_translate()
            self.qapp.processEvents()
            self.assertIsNotNone(self.overlay._tl8n)
            self.assertEqual(self.overlay._tl8n['state'], 'ready')

    def test_long_mode_ignores_translate(self):
        self.overlay._long = {'dummy': True}
        self._translate()
        self.assertIsNone(self.overlay._tl8n)


if __name__ == '__main__':
    unittest.main()