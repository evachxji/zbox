# -*- coding: utf-8 -*-
"""视频组件更新进度文字回归测试。"""
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

import video_dl
import video_ui


class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _Cfg:
    def __init__(self):
        self.data = {'video_enabled': False, 'video_dir': ''}

    def set(self, key, value):
        self.data[key] = value


class UpdateProgressTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def _bare_widget(self):
        w = video_ui.VideoWidget.__new__(video_ui.VideoWidget)
        w._update_stat = None
        w.sig_update = _Signal()
        return w

    def test_progress_formats_size_eta_and_speed_without_prefix(self):
        w = self._bare_widget()
        if not hasattr(w, '_update_progress'):
            self.fail('组件更新缺少进度回调')
        with patch.object(video_ui.time, 'monotonic', side_effect=(100.0, 102.0)):
            w._update_progress('yt-dlp', 1048576, 8388608)
            w._update_progress('yt-dlp', 3145728, 8388608)
        self.assertEqual(w.sig_update.calls, [
            ('yt-dlp', '1.0 MB/8.0 MB', '', ''),
            ('yt-dlp', '3.0 MB/8.0 MB', '0:05', '1.0 MB/s'),
        ])

    def test_update_work_passes_progress_callback_to_both_downloads(self):
        w = self._bare_widget()
        if not hasattr(w, '_update_progress'):
            self.fail('组件更新缺少进度回调')
        w._yt_new = True
        w._ff_new = True
        w._ff_latest = '6.1.1'
        w._updating = True
        w.sig_ver = _Signal()
        w.sig_msg = _Signal()
        callbacks = {}

        def fake_yt(progress_cb=None):
            callbacks['yt'] = progress_cb

        def fake_ff(progress_cb=None, ver=None):
            callbacks['ff'] = progress_cb
            callbacks['ver'] = ver

        with patch.multiple(video_dl, download_ytdlp=fake_yt,
                            download_ffmpeg=fake_ff, local_version=lambda: '1',
                            latest_version=lambda: '1', ffmpeg_version=lambda: '1',
                            latest_ffmpeg_version=lambda: '1'):
            w._update_work()
        self.assertEqual(callbacks['yt'], w._update_progress)
        self.assertEqual(callbacks['ff'], w._update_progress)
        self.assertEqual(callbacks['ver'], '6.1.1')

    def test_progress_labels_show_during_update_and_hide_on_result(self):
        w = video_ui.VideoWidget(_Cfg(), auto_start=False)
        self.addCleanup(w.deleteLater)
        if not hasattr(w, 'update_size_lab'):
            self.fail('组件更新状态行缺少三段进度标签')
        w._on_update_progress('yt-dlp', '1.0 MB/8.0 MB', '0:05', '1.0 MB/s')
        labs = (w.update_size_lab, w.update_eta_lab, w.update_speed_lab)
        self.assertEqual([lab.text() for lab in labs],
                         ['1.0 MB/8.0 MB', '0:05', '1.0 MB/s'])
        self.assertTrue(all(not lab.isHidden() for lab in labs))
        w.resize(344, 370)
        w.show()
        self.qapp.processEvents()
        self.assertTrue(all(lab.width() > 0 for lab in labs))
        w._set_state('done', 'updated')
        self.assertTrue(all(lab.isHidden() for lab in labs))
        self.assertEqual([lab.text() for lab in labs], ['', '', ''])


if __name__ == '__main__':
    unittest.main()
