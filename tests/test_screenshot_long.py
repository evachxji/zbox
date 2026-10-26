# -*- coding: utf-8 -*-
"""长截图手动滚轮不限速与断点恢复回归测试。"""
import ctypes
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from i18n import t
import screenshot


def _frame(start, width=32, height=40):
    """制作每行灰度不同的页面帧，模拟向下滚动后的重叠区域。"""
    img = QImage(width, height, QImage.Format_RGB32)
    for y in range(height):
        value = (start + y) % 240
        for x in range(width):
            img.setPixelColor(x, y, QColor(value, value, value))
    return img


def _state():
    return {'chunks': [], 'prev_img': None, 'prev_sig': None,
            'interrupted': False}


class LongScreenshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def test_wheel_is_held_until_initial_anchor_has_been_captured(self):
        guard = screenshot._WheelGuard()
        guard.sel_phys = (0, 0, 100, 100)
        event = screenshot._MSLLHOOKSTRUCT()
        event.mouseData = 120 << 16
        event.pt.x = 50
        event.pt.y = 50
        with patch.object(screenshot._u32, 'CallNextHookEx', return_value=0) as next_hook:
            result = guard._wheel_callback(
                0, screenshot._WM_MOUSEWHEEL, ctypes.addressof(event))

        self.assertEqual(result, 1)
        self.assertEqual(guard.wheel_seq, 0)
        next_hook.assert_not_called()

    def test_startup_holds_wheels_before_anchor_even_outside_selection(self):
        guard = screenshot._WheelGuard()
        guard.sel_phys = (10, 10, 100, 100)
        event = screenshot._MSLLHOOKSTRUCT()
        event.mouseData = 120 << 16
        event.pt.x = 5
        event.pt.y = 5
        with patch.object(screenshot._u32, 'CallNextHookEx', return_value=0) as next_hook:
            result = guard._wheel_callback(
                0, screenshot._WM_MOUSEWHEEL, ctypes.addressof(event))

        self.assertEqual(result, 1)
        self.assertEqual(guard.wheel_seq, 0)
        next_hook.assert_not_called()

    def test_manual_wheel_events_are_all_forwarded_without_reinjection(self):
        guard = screenshot._WheelGuard()
        guard.capture_ready = True
        guard.sel_phys = (0, 0, 100, 100)
        event = screenshot._MSLLHOOKSTRUCT()
        event.mouseData = 120 << 16
        event.pt.x = 50
        event.pt.y = 50
        forwarded = []
        with patch.object(screenshot._u32, 'CallNextHookEx',
                          side_effect=lambda *args: forwarded.append(args) or 0), \
                patch.object(screenshot._u32, 'mouse_event') as inject:
            results = [guard._wheel_callback(
                0, screenshot._WM_MOUSEWHEEL, ctypes.addressof(event))
                for _ in range(4)]

        self.assertEqual(results, [0, 0, 0, 0])
        self.assertEqual(len(forwarded), 4)
        inject.assert_not_called()
        self.assertEqual(guard.wheel_seq, 4)

    def test_unmatched_manual_scroll_marks_interruption_and_keeps_anchor(self):
        state = _state()
        anchor = _frame(0)
        status, chunk = screenshot._long_feed_frame(state, anchor, False)
        self.assertEqual(status, 'seed')
        self.assertIs(chunk, anchor)

        jumped = _frame(32)
        status, chunk = screenshot._long_feed_frame(state, jumped, True)

        self.assertEqual(status, 'interrupted')
        self.assertIsNone(chunk)
        self.assertTrue(state['interrupted'])
        self.assertEqual(len(state['chunks']), 1)
        self.assertIs(state['prev_img'], anchor)

    def test_unmatched_frame_without_wheel_input_is_not_a_break(self):
        state = _state()
        anchor = _frame(0)
        screenshot._long_feed_frame(state, anchor, False)

        status, chunk = screenshot._long_feed_frame(state, _frame(32), False)

        self.assertEqual(status, 'ignored')
        self.assertIsNone(chunk)
        self.assertFalse(state['interrupted'])
        self.assertIs(state['prev_img'], anchor)
        self.assertEqual(len(state['chunks']), 1)

    def test_wheel_pending_survives_a_frame_before_page_moves(self):
        state = _state()
        anchor = _frame(0)
        screenshot._long_feed_frame(state, anchor, False)
        state['wheel_pending'] = True

        status, chunk = screenshot._long_feed_frame(state, _frame(0), True)

        self.assertEqual(status, 'pending')
        self.assertIsNone(chunk)
        self.assertTrue(state['wheel_pending'])

    def test_pending_wheel_clears_after_two_unchanged_frames(self):
        state = _state()
        anchor = _frame(0)
        screenshot._long_feed_frame(state, anchor, False)
        state['wheel_pending'] = True

        first, _ = screenshot._long_feed_frame(state, _frame(0), True)
        self.assertEqual(first, 'pending')
        self.assertTrue(state['wheel_pending'])

        second, _ = screenshot._long_feed_frame(state, _frame(0), True)
        self.assertEqual(second, 'settled')
        self.assertFalse(state['wheel_pending'])

    def test_return_to_anchor_resumes_and_appends_only_new_pixels(self):
        state = _state()
        anchor = _frame(0)
        screenshot._long_feed_frame(state, anchor, False)
        screenshot._long_feed_frame(state, _frame(32), True)

        status, chunk = screenshot._long_feed_frame(state, _frame(0), False)
        self.assertEqual(status, 'recovered')
        self.assertIsNone(chunk)
        self.assertFalse(state['interrupted'])
        self.assertEqual(len(state['chunks']), 1)

        status, chunk = screenshot._long_feed_frame(state, _frame(8), True)
        self.assertEqual(status, 'appended')
        self.assertEqual(chunk.height(), 8)
        self.assertEqual(len(state['chunks']), 2)
        self.assertEqual(sum(part.height() for part in state['chunks']), 48)

    def test_interruption_is_visible_and_disables_controls(self):
        bar = screenshot._LongBar(
            screenshot._qss(screenshot.PALETTES['nocturne'], 'Arial', 'Arial'))
        self.addCleanup(bar.close)

        bar.show()
        self.qapp.processEvents()
        bar.set_interrupted(True)
        self.qapp.processEvents()
        self.assertEqual(bar._hint.text(), t('shot.long.interrupted'))
        self.assertTrue(bar._hint.isVisible())
        self.assertFalse(bar._done_btn.isEnabled())

        bar.set_interrupted(False)
        self.assertFalse(bar._hint.isVisible())
        self.assertTrue(bar._auto_btn.isEnabled())
        self.assertTrue(bar._done_btn.isEnabled())

    def test_interrupted_capture_cannot_be_forced_to_export(self):
        stub = type('Stub', (), {'stop': lambda self: None,
                                 'close': lambda self: None})()
        fake = type('FakeOverlay', (), {})()
        guard = type('Guard', (), {'esc': False, 'wheel_seq': 0,
                                   'stop': lambda self: None})()
        fake._long = {'interrupted': True, 'wheel_pending': False, 'wheel_seq': 0,
                      'chunks': [], 'timer': stub, 'guard': guard,
                      'bar': stub, 'chrome': stub, 'mask': stub}
        fake._close = lambda: setattr(fake, 'closed', True)

        screenshot.ShotOverlay._stop_long(fake, save=True)

        self.assertIsNotNone(fake._long)
        self.assertFalse(getattr(fake, 'closed', False))

    def test_manual_scroll_outside_capture_area_is_still_tracked(self):
        guard = screenshot._WheelGuard()
        guard.capture_ready = True
        guard.sel_phys = (10, 10, 100, 100)
        event = screenshot._MSLLHOOKSTRUCT()
        event.mouseData = 120 << 16
        event.pt.x = 5
        event.pt.y = 5
        with patch.object(screenshot._u32, 'CallNextHookEx', return_value=0):
            result = guard._wheel_callback(
                0, screenshot._WM_MOUSEWHEEL, ctypes.addressof(event))
        self.assertEqual(result, 0)
        self.assertEqual(guard.wheel_seq, 1)

    def test_guard_start_reports_missing_mouse_hook(self):
        guard = screenshot._WheelGuard()

        def start_without_mouse_hook():
            guard._hook = None
            guard._khook = object()
            guard._ready.set()

        guard._run = start_without_mouse_hook
        self.assertIs(guard.start(), False)

    def test_initial_capture_arms_scrolling_only_after_seed_frame(self):
        calls = []
        guard = type('Guard', (), {'capture_ready': False})()
        timer = type('Timer', (), {'start': lambda self, ms: calls.append(('timer', ms))})()
        bar = type('Bar', (), {'show': lambda self: calls.append(('show',))})()
        fake = type('FakeOverlay', (), {})()
        fake._long = {'prev_img': None, 'guard': guard, 'bar': bar, 'timer': timer}
        fake._long_tick = lambda: fake._long.update(prev_img=object())

        started = screenshot.ShotOverlay._long_capture_initial(fake)

        self.assertTrue(started)
        self.assertTrue(guard.capture_ready)
        self.assertEqual(calls, [('show',), ('timer', 280)])

    def test_initial_capture_exception_cleans_up_long_session(self):
        fake = type('FakeOverlay', (), {})()
        fake._long = {'guard': object()}
        stopped = []
        fake._long_tick = lambda: (_ for _ in ()).throw(RuntimeError('capture'))
        fake._stop_long = lambda save: stopped.append(save)
        with patch.object(screenshot, '_guard_log'):
            started = screenshot.ShotOverlay._long_capture_initial(fake)
        self.assertFalse(started)
        self.assertEqual(stopped, [False])

    def test_pending_wheel_blocks_completion(self):
        stub = type('Stub', (), {'stop': lambda self: None,
                                 'close': lambda self: None})()
        fake = type('FakeOverlay', (), {})()
        guard = type('Guard', (), {'esc': False, 'wheel_seq': 0,
                                   'stop': lambda self: None})()
        fake._long = {'interrupted': False, 'wheel_pending': True, 'wheel_seq': 0,
                      'chunks': [], 'timer': stub, 'guard': guard,
                      'bar': stub, 'chrome': stub, 'mask': stub}
        fake._long_set_pending = lambda on: setattr(fake, 'pending_shown', on)
        fake._close = lambda: setattr(fake, 'closed', True)

        screenshot.ShotOverlay._stop_long(fake, save=True)

        self.assertIsNotNone(fake._long)
        self.assertFalse(getattr(fake, 'closed', False))

    def test_signature_collision_after_scroll_marks_interruption(self):
        state = _state()
        anchor = _frame(0)
        screenshot._long_feed_frame(state, anchor, False)
        with patch.object(screenshot, '_find_shift', return_value=(0, 0)):
            status, chunk = screenshot._long_feed_frame(state, _frame(8), True)

        self.assertEqual(status, 'interrupted')
        self.assertIsNone(chunk)
        self.assertTrue(state['interrupted'])
        self.assertIs(state['prev_img'], anchor)

    def test_near_anchor_does_not_clear_interruption(self):
        state = _state()
        anchor = _frame(0)
        screenshot._long_feed_frame(state, anchor, False)
        state['interrupted'] = True
        near_anchor = _frame(1)
        with patch.object(screenshot, '_find_shift', return_value=(0, 1)):
            status, chunk = screenshot._long_feed_frame(state, near_anchor, False)

        self.assertEqual(status, 'interrupted')
        self.assertIsNone(chunk)
        self.assertTrue(state['interrupted'])
        self.assertIs(state['prev_img'], anchor)

    def test_esc_during_finalization_cannot_copy_long_image(self):
        guard = type('Guard', (), {'esc': False, 'wheel_seq': 0,
                                   'stop': lambda self: None})()
        chunk = _frame(0)
        fake = type('FakeOverlay', (), {})()
        fake._long = {'interrupted': False, 'wheel_pending': False, 'wheel_seq': 0,
                      'chunks': [chunk], 'timer': type('Timer', (), {'stop': lambda self: None})(),
                      'guard': guard, 'bar': type('Widget', (), {'close': lambda self: None})(),
                      'chrome': type('Widget', (), {'close': lambda self: None})(),
                      'mask': type('Widget', (), {'close': lambda self: None})(),
                      'screen': type('Screen', (), {
                          'devicePixelRatio': lambda self: setattr(guard, 'esc', True) or 1.0})()}
        fake._close = lambda: None
        with patch.object(screenshot.QApplication, 'clipboard') as clipboard:
            screenshot.ShotOverlay._stop_long(fake, save=True)

        clipboard.return_value.setImage.assert_not_called()

    def test_finish_gate_consumes_wheel_before_final_sequence_check(self):
        guard = screenshot._WheelGuard()
        guard.capture_ready = True
        guard.finishing = True
        guard.sel_phys = (0, 0, 100, 100)
        event = screenshot._MSLLHOOKSTRUCT()
        event.mouseData = 120 << 16
        event.pt.x = 150
        event.pt.y = 150
        with patch.object(screenshot._u32, 'CallNextHookEx', return_value=0):
            result = guard._wheel_callback(
                0, screenshot._WM_MOUSEWHEEL, ctypes.addressof(event))

        self.assertEqual(result, 1)
        self.assertEqual(guard.wheel_seq, 0)

    def test_auto_scroll_still_consumes_manual_wheel_events(self):
        guard = screenshot._WheelGuard()
        guard.manual = False
        event = screenshot._MSLLHOOKSTRUCT()
        event.mouseData = 120 << 16
        with patch.object(screenshot._u32, 'CallNextHookEx', return_value=0):
            result = guard._wheel_callback(
                0, screenshot._WM_MOUSEWHEEL, ctypes.addressof(event))
        self.assertEqual(result, 1)
        self.assertEqual(guard.wheel_seq, 0)


if __name__ == '__main__':
    unittest.main()
