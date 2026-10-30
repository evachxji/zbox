# -*- coding: utf-8 -*-
"""桌面带挂接：兼容 Progman 直连与 Wallpaper Engine 的 WorkerW 分层结构。"""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import app as ui
import boxes


class _FakeUser32:
    PROGMAN = 100
    WORKERW = 200
    DEFVIEW = 300
    PANEL = 400
    TITLEBAR = 401

    def __init__(self, workerw):
        self.parent = {self.DEFVIEW: self.WORKERW if workerw else self.PROGMAN}
        self.children = {self.PROGMAN: [], self.WORKERW: []}
        self.children[self.parent[self.DEFVIEW]].append(self.DEFVIEW)
        self.set_parent_calls = []
        self.owner = {}

    def FindWindowW(self, cls, _title):
        return self.PROGMAN if cls == 'Progman' else 0

    def FindWindowExW(self, parent, after, cls, _title):
        candidates = [self.PROGMAN, self.WORKERW] if not parent \
            else self.children.get(parent, [])
        if after:
            candidates = candidates[candidates.index(after) + 1:]
        return next((h for h in candidates if
                     (cls == 'WorkerW' and h == self.WORKERW) or
                     (cls == 'SHELLDLL_DefView' and h == self.DEFVIEW)), 0)

    def GetParent(self, hwnd):
        # 与真实 WS_POPUP 窗口一致：SetParent 后 GetParent 仍返回 0，
        # 必须走 GetAncestor(GA_PARENT) 才能拿到桌面父窗。
        if hwnd in (self.PANEL, self.TITLEBAR):
            return self.owner.get(hwnd, 0)
        return self.parent.get(hwnd, 0)

    def GetAncestor(self, hwnd, kind):
        if kind == 1:   # GA_PARENT
            return self.parent.get(hwnd, 0)
        while self.parent.get(hwnd):
            hwnd = self.parent[hwnd]
        return hwnd

    def SetParent(self, hwnd, parent):
        self.set_parent_calls.append((hwnd, parent))
        self.parent[hwnd] = parent
        self.children.setdefault(parent, []).append(hwnd)
        return self.parent.get(hwnd, 0)

    def SetOwner(self, hwnd, _kind, parent):
        # 与真实 WS_POPUP 一致：直接写 owner 后 GetParent 可见，
        # 但 GetAncestor(GA_PARENT) 仍返回桌面，不会像 SetParent 一样建立父窗关系。
        self.set_parent_calls.append((hwnd, parent))
        self.owner[hwnd] = parent

    def IsWindowVisible(self, _hwnd):
        return True

    def ShowWindow(self, _hwnd, _command):
        return True


class _Win:
    def __init__(self, hwnd):
        self.hwnd = hwnd

    def winId(self):
        return self.hwnd


class DesktopBandTest(unittest.TestCase):
    def test_workerw_defview_is_used_and_repin_is_idempotent(self):
        fake = _FakeUser32(workerw=True)
        with patch.object(ui, '_u32', fake), \
                patch.object(ui, '_set_wnd_long_ptr', fake.SetOwner):
            self.assertTrue(ui.pin_to_desktop(_Win(fake.PANEL)))
            self.assertTrue(ui.pin_to_desktop(_Win(fake.PANEL)))
        self.assertEqual(fake.owner[fake.PANEL], fake.DEFVIEW)
        self.assertEqual(fake.set_parent_calls, [(fake.PANEL, fake.DEFVIEW)])

    def test_progman_defview_remains_supported(self):
        fake = _FakeUser32(workerw=False)
        with patch.object(ui, '_u32', fake), \
                patch.object(ui, '_set_wnd_long_ptr', fake.SetOwner):
            self.assertTrue(ui.pin_to_desktop(_Win(fake.PANEL)))
        self.assertEqual(fake.owner[fake.PANEL], fake.DEFVIEW)

    def test_unpin_changes_owner_without_toggling_visibility(self):
        fake = Mock()
        with patch.object(ui, '_u32', fake), \
                patch.object(ui, '_set_wnd_long_ptr', fake.SetOwner) as set_owner:
            ui.unpin_from_desktop(_Win(400))
        set_owner.assert_called_once_with(400, ui._GWLP_HWNDPARENT, None)
        fake.SetParent.assert_not_called()
        fake.ShowWindow.assert_not_called()

    def test_panel_watchdog_accepts_workerw_parent(self):
        fake = _FakeUser32(workerw=True)
        fake.parent[fake.PANEL] = fake.DEFVIEW
        fake.parent[fake.TITLEBAR] = fake.DEFVIEW
        panel = SimpleNamespace(
            _drag=None, _desk_pinned=True,
            winId=lambda: fake.PANEL,
            titlebar=_Win(fake.TITLEBAR))
        with patch.object(ui, '_u32', fake), \
                patch.object(ui, 'pin_to_desktop', Mock(return_value=True)) as pin:
            ui.FloatingPanel._ensure_band(panel)
        pin.assert_not_called()

    def test_box_watchdog_accepts_workerw_parent(self):
        fake = _FakeUser32(workerw=True)
        fake.parent[fake.PANEL] = fake.DEFVIEW
        box = SimpleNamespace(winId=lambda: fake.PANEL, _repin=Mock())
        with patch.object(boxes.ui, '_u32', fake):
            boxes.BoxWindow._ensure_band(box)
        box._repin.assert_not_called()


if __name__ == '__main__':
    unittest.main()
