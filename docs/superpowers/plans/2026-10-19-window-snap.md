# 截图窗口套选实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 截图空闲态悬浮程序窗口时显示轮廓，单击套选完整窗口，双击复制并退出，同时保留自由拖拽框选。

**架构：** 在 `screenshot.py` 中增加 Win32 顶层窗口探测，使用 DWM 可见外框并回退 `GetWindowRect`；`ShotOverlay` 缓存悬浮外框，在松开时用按下窗口完成短点击套选，继续复用现有 `ready` 标注态与 `_finish_copy()`。

**技术栈：** Python 3.10+、PySide6、ctypes/Win32、DWM、unittest/QTest

---

## 文件结构

- 修改 `screenshot.py`：Win32 窗口探测、DWM 外框、悬浮轮廓和点击套选状态。
- 创建 `tests/test_screenshot_window_snap.py`：窗口命中、短点击、拖拽兼容和双击完成。
- 修改 `AGENTS.md`：记录截图窗口套选行为。
- 修改 `README.md`、`README.zh-CN.md`：用户功能说明。

## 任务 1：窗口悬浮与短点击套选

**文件：**
- 创建：`tests/test_screenshot_window_snap.py`
- 修改：`screenshot.py`

- [ ] **步骤 1：编写失败测试**

```python
# tests/test_screenshot_window_snap.py
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import screenshot


class _Cfg:
    def __init__(self):
        self.data = {'theme': 'nocturne'}

    def save(self):
        pass


class ScreenshotWindowSnapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def _overlay(self):
        win = screenshot.ShotOverlay(_Cfg())
        win.setGeometry(0, 0, 800, 600)
        win._tl = QPoint(0, 0)
        win.show()
        self.qapp.processEvents()
        self.addCleanup(win._close)
        return win

    def test_hover_shows_and_clears_window_frame(self):
        win = self._overlay()
        frame = QRect(100, 80, 320, 240)
        with patch.object(screenshot, '_window_frame_at',
                          return_value=(123, frame)):
            win._refresh_window_hover(QPoint(140, 120))
        self.assertEqual(win._hover_frame, frame)

        with patch.object(screenshot, '_window_frame_at', return_value=None):
            win._refresh_window_hover(QPoint(500, 500))
        self.assertIsNone(win._hover_frame)

    def test_short_click_selects_whole_window(self):
        win = self._overlay()
        frame = QRect(100, 80, 320, 240)
        with patch.object(screenshot, '_window_frame_at',
                          return_value=(123, frame)):
            QTest.mouseClick(win, Qt.LeftButton, pos=QPoint(140, 120))
            self.qapp.processEvents()
        self.assertEqual(win._mode, 'ready')
        self.assertEqual(win._sel, frame)

    def test_dragging_still_creates_manual_selection(self):
        win = self._overlay()
        frame = QRect(100, 80, 320, 240)
        with patch.object(screenshot, '_window_frame_at',
                          return_value=(123, frame)):
            QTest.mousePress(win, Qt.LeftButton, pos=QPoint(140, 120))
            QTest.mouseMove(win, QPoint(300, 260))
            QTest.mouseRelease(win, Qt.LeftButton, pos=QPoint(300, 260))
            self.qapp.processEvents()
        self.assertEqual(win._mode, 'ready')
        self.assertNotEqual(win._sel, frame)
        self.assertGreater(win._sel.width(), screenshot.MIN_SEL)

    def test_short_click_without_window_stays_idle(self):
        win = self._overlay()
        with patch.object(screenshot, '_window_frame_at', return_value=None):
            QTest.mouseClick(win, Qt.LeftButton, pos=QPoint(140, 120))
            self.qapp.processEvents()
        self.assertEqual(win._mode, 'idle')
        self.assertFalse(win._sel.isValid())


if __name__ == '__main__':
    unittest.main()
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```text
python -m unittest discover -s tests -p "test_screenshot_window_snap.py" -v
```

预期：FAIL，报错包含 `_window_frame_at` 不存在或 `_hover_frame` 未定义。

- [ ] **步骤 3：实现 Win32 外框探测**

在 `screenshot.py` 现有 Win32 声明之后加入：

```python
_u32.GetAncestor.restype = wintypes.HWND
_u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_u32.GetClassNameW.restype = ctypes.c_int
_u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.c_wchar_p, ctypes.c_int]

_dwm = ctypes.windll.dwmapi
_dwm.DwmGetWindowAttribute.restype = ctypes.c_long
_dwm.DwmGetWindowAttribute.argtypes = [
    wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

_GA_ROOT = 2
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_DWMWA_CLOAKED = 14
_SHELL_WINDOW_CLASSES = frozenset((
    'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd',
))


def _window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    _u32.GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def _window_is_cloaked(hwnd):
    value = wintypes.DWORD()
    try:
        return (_dwm.DwmGetWindowAttribute(
            hwnd, _DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)) == 0
            and bool(value.value))
    except Exception:
        return False


def _window_frame(hwnd):
    """返回不含系统投影的顶层窗口屏幕矩形；DWM 失败时回退 GetWindowRect。"""
    rc = wintypes.RECT()
    ok = False
    try:
        ok = _dwm.DwmGetWindowAttribute(
            hwnd, _DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rc), ctypes.sizeof(rc)) == 0
    except Exception:
        ok = False
    if not ok and not _u32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return None
    if rc.right <= rc.left or rc.bottom <= rc.top:
        return None
    return QRect(rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)


def _window_frame_at(pt):
    """返回屏幕坐标 pt 下最上层的非本进程程序窗口 (hwnd, 可见外框)。"""
    hwnd = _u32.GetTopWindow(None)
    while hwnd:
        pid = wintypes.DWORD()
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        styles = _u32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
        frame = _window_frame(hwnd)
        if (pid.value != os.getpid() and _u32.IsWindowVisible(hwnd)
                and _u32.IsWindowEnabled(hwnd)
                and (styles & _WS_EX_PASS_THROUGH) != _WS_EX_PASS_THROUGH
                and _window_class(hwnd) not in _SHELL_WINDOW_CLASSES
                and not _window_is_cloaked(hwnd)
                and frame is not None and frame.contains(pt)):
            root = _u32.GetAncestor(hwnd, _GA_ROOT) or hwnd
            return root, _window_frame(root) or frame
        hwnd = _u32.GetWindow(hwnd, 2)
    return None
```

在 `ShotOverlay.__init__` 的 `_eat_press` 旁增加状态：

```python
self._hover_frame = None
self._press_window = None
```

- [ ] **步骤 4：实现悬浮和短点击状态**

在 `ShotOverlay` 鼠标处理区加入：

```python
def _window_rect_at(self, gpos):
    try:
        hit = _window_frame_at(gpos)
    except Exception:
        return None
    if hit is None:
        return None
    _hwnd, frame = hit
    frame = QRect(frame.topLeft() - self._tl, frame.size()).intersected(self.rect())
    if frame.width() < MIN_SEL or frame.height() < MIN_SEL:
        return None
    return frame

def _refresh_window_hover(self, gpos):
    if self._pin_mode or self._mode != 'idle' or self._drag is not None:
        frame = None
    else:
        frame = self._window_rect_at(gpos)
    if frame != self._hover_frame:
        self._hover_frame = frame
        self.update()
```

空闲左键按下时，在创建零尺寸选区前记录候选窗口：

```python
self._press_window = self._window_rect_at(e.globalPosition().toPoint())
self._hover_frame = None
```

`mouseReleaseEvent` 的 `kind == 'create'` 分支改为：

```python
manual = self._sel.width() >= MIN_SEL or self._sel.height() >= MIN_SEL
if manual:
    self._mode = 'ready'
elif (self._press_window is not None
      and self._press_window.contains(e.pos())):
    self._sel = QRect(self._press_window)
    self._mode = 'ready'
else:
    self._sel = QRect()
    self._mode = 'idle'
self._press_window = None
```

在拖动结束、方向键之外没有活动拖拽时，`mouseMoveEvent` 更新悬浮：

```python
if self._drag is None:
    self._refresh_window_hover(e.globalPosition().toPoint())
    self._update_cursor(e.globalPosition().toPoint())
    return
```

- [ ] **步骤 5：绘制轮廓并清理状态**

在 `paintEvent` 填充灰罩后加入：

```python
if self._mode == 'idle' and self._drag is None and self._hover_frame is not None:
    p.setPen(QPen(QColor(self.pal['sel']), 2))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(self._hover_frame).adjusted(1, 1, -1, -1))
```

`showEvent` 末尾主动刷新一次：

```python
QTimer.singleShot(0, lambda: self._refresh_window_hover(QCursor.pos()))
```

`hideEvent` 和 `_reset_sel` 清空 `_hover_frame`；`_reset_sel` 回到 idle 后再按当前光标刷新。

- [ ] **步骤 6：运行任务测试验证通过**

运行：

```text
python -m unittest discover -s tests -p "test_screenshot_window_snap.py" -v
```

预期：4 个测试全部 PASS。

- [ ] **步骤 7：Commit**

```text
git add screenshot.py tests/test_screenshot_window_snap.py
git commit -m "feat: 截图支持窗口悬浮套选"
```

## 任务 2：双击复制集成测试

**文件：**
- 修改：`tests/test_screenshot_window_snap.py`

- [ ] **步骤 1：编写失败测试**

追加：

```python
def test_double_click_on_window_finishes_copy(self):
    win = self._overlay()
    frame = QRect(100, 80, 320, 240)
    with patch.object(screenshot, '_window_frame_at',
                      return_value=(123, frame)), \
            patch.object(win, '_finish_copy') as finish:
        QTest.mouseDClick(win, Qt.LeftButton, pos=QPoint(140, 120))
        self.qapp.processEvents()
    finish.assert_called_once_with()
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```text
python -m unittest discover -s tests -p "test_screenshot_window_snap.py" -v
```

预期：FAIL，第一次点击尚未套选窗口，`mouseDoubleClickEvent` 因 `_mode` 不是
`ready` 而没有调用 `_finish_copy()`。

- [ ] **步骤 3：确认第一次点击套选与双击完成衔接**

第一次单击由任务 1 的 `create` 分支进入 `ready`，第二次点击由既有
`mouseDoubleClickEvent` 完成。确认 `create` 松开分支保留以下逻辑：

```python
elif kind == 'create':
    manual = self._sel.width() >= MIN_SEL or self._sel.height() >= MIN_SEL
    if manual:
        self._mode = 'ready'
    elif self._press_window is not None and self._press_window.contains(e.pos()):
        self._sel = QRect(self._press_window)
        self._mode = 'ready'
    else:
        self._sel = QRect()
        self._mode = 'idle'
    self._press_window = None
```

保持 `mouseDoubleClickEvent` 的完成条件：

```python
if (not self._pin_mode and e.button() == Qt.LeftButton and self._long is None
        and self._mode == 'ready' and self._sel.contains(e.pos())):
    self._finish_copy()
```

本步骤不新增生产代码；测试用于锁定两个既有状态机之间的集成契约。

- [ ] **步骤 4：运行测试验证通过**

运行：

```text
python -m unittest discover -s tests -p "test_screenshot_window_snap.py" -v
```

预期：5 个测试全部 PASS。

- [ ] **步骤 5：Commit**

```text
git add tests/test_screenshot_window_snap.py
git commit -m "test: 覆盖截图窗口双击复制"
```

## 任务 3：文档与完整验证

**文件：**
- 修改：`AGENTS.md`
- 修改：`README.md`
- 修改：`README.zh-CN.md`

- [ ] **步骤 1：更新截图文档**

在 `AGENTS.md` 的截图会话段落加入：

```markdown
- **窗口套选**：空闲态沿 Win32 Z 序探测鼠标下最上层的非本进程程序窗口，
  用 DWM `DWMWA_EXTENDED_FRAME_BOUNDS` 取不含系统投影的可见外框（失败回退
  `GetWindowRect`）；悬浮画 2px 主题色轮廓，原地单击套选完整窗口并进入 ready，
  拖动仍走自由框选。窗口候选在按下时记录，松开位置必须仍在外框内；
  双击由现有 `mouseDoubleClickEvent` 调用 `_finish_copy()` 复制并退出。
  桌面壳层、任务栏、透明穿透层、DWM cloaked 与失败外框均跳过。
```

`README.md` 的 Screenshot 功能列表增加：

```markdown
- Hover an app window to outline it; click to select the full window, or double-click to copy and exit.
```

`README.zh-CN.md` 的截图功能列表增加：

```markdown
- 鼠标悬浮程序窗口时显示轮廓；单击套选完整窗口，双击复制并退出。
```

- [ ] **步骤 2：运行 Python 回归测试**

运行：

```text
python -m unittest discover -s tests -v
```

预期：全部测试 PASS，无新增失败。

- [ ] **步骤 3：运行中英文截图自检**

运行：

```text
set ZBOX_SHOT=designs\verify-zh && set ZBOX_SHOT_LANG=zh-CN && python main.pyw
```

预期：生成中文两主题截图后正常退出。

运行：

```text
set ZBOX_SHOT=designs\verify-en && set ZBOX_SHOT_LANG=en-US && python main.pyw
```

预期：生成英文两主题截图后正常退出，无截断。

- [ ] **步骤 4：检查工作区差异**

运行：

```text
git diff --check
git status --short
git diff -- screenshot.py tests/test_screenshot_window_snap.py AGENTS.md README.md README.zh-CN.md
```

预期：只有本功能文件和文档变化，且无空白错误。

- [ ] **步骤 5：Commit**

```text
git add AGENTS.md README.md README.zh-CN.md
git commit -m "docs: 说明截图窗口套选"
```

## 自检

- 规格覆盖：悬浮轮廓、DWM 外框、单击套选、拖拽兼容、双击复制、错误回退、
  中英文文档、自动测试与截图自检均有对应任务。
- 占位符扫描：计划中没有待定项、TODO 或未定义类型。
- 类型一致性：`_window_frame_at(pt)` 始终返回 `(hwnd, QRect)` 或 `None`；
  `_window_rect_at(gpos)` 始终返回本地 `QRect` 或 `None`；`_hover_frame` 与
  `_press_window` 均为本地坐标 `QRect`。
