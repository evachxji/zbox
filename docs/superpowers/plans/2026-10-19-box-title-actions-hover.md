# 桌面格子顶部操作图标悬停显隐实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 桌面格子顶部栏右侧的收起、锁定、菜单图标默认隐藏，鼠标移入顶部栏时淡入、移出时淡出。

**架构：** 在 `BoxWindow` 中把三个按钮放进独立操作区，用单个 `QGraphicsOpacityEffect` 和 `QVariantAnimation` 控制整组透明度。顶部栏及其子按钮的进入/离开事件经过短暂延迟复核，兼容标题区与按钮区之间移动；菜单打开期间冻结隐藏。

**技术栈：** Python 3.10+、PySide6 6.8、`unittest`、Qt offscreen 测试。

---

### 任务 1：用回归测试锁定显隐与布局

**文件：**
- 创建：`tests/test_box_title_actions.py`
- 修改：`boxes.py` 中的 `BoxWindow` 顶部栏

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_box_title_actions.py
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QCursor, QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect

from boxes import BoxWindow


class _BoxManagerStub:
    def save_rec(self, _win):
        pass

    def remove(self, _win):
        pass

    def ungroup_paths(self, _paths):
        pass


class BoxTitleActionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        rec = {
            'id': 'title-actions-test', 'kind': 'blank', 'path': '',
            'name': '示例格子', 'x': 0, 'y': 0, 'w': 320, 'h': 240,
            'collapsed': False, 'locked': False, 'sort': 'name', 'view': 'list',
        }
        self.box = BoxWindow(_BoxManagerStub(), rec)
        self.box.move(200, 200)
        self.box.show()
        self.qapp.processEvents()
        self.addCleanup(self.box.deleteLater)

    def test_actions_start_hidden_and_keep_layout_width(self):
        effect = self.box.title_actions.graphicsEffect()
        before = self.box.btn_menu.mapTo(self.box, QPoint(0, 0))

        self.assertIsInstance(effect, QGraphicsOpacityEffect)
        self.assertEqual(effect.opacity(), 0.0)
        self.assertTrue(self.box.title_actions.testAttribute(
            Qt.WA_TransparentForMouseEvents))

        self.box._show_title_actions()
        QTest.qWait(170)

        self.assertAlmostEqual(effect.opacity(), 1.0)
        self.assertEqual(self.box.btn_menu.mapTo(self.box, QPoint(0, 0)), before)

    def test_title_enter_fades_in_and_leave_fades_out(self):
        self.box._show_title_actions()
        QTest.qWait(170)
        self.assertAlmostEqual(
            self.box.title_actions.graphicsEffect().opacity(), 1.0)

        center = self.box.title.rect().center()
        QApplication.sendEvent(
            self.box.title,
            QEnterEvent(QPointF(center), QPointF(center), QPointF(center)))
        self.assertEqual(self.box._title_actions_target, 1.0)

        QCursor.setPos(self.box.mapToGlobal(QPoint(-10, -10)))
        QApplication.sendEvent(self.box.title, QEvent(QEvent.Leave))
        self.box._title_actions_tick()
        QTest.qWait(210)

        self.assertEqual(
            self.box.title_actions.graphicsEffect().opacity(), 0.0)
        self.assertTrue(self.box.title_actions.testAttribute(
            Qt.WA_TransparentForMouseEvents))

    def test_open_menu_holds_actions_visible(self):
        seen = []

        class _MenuStub:
            def exec(self, _pos):
                seen.append(box._title_actions_hold)

        box = self.box
        box._build_menu = lambda: _MenuStub()

        box._show_menu()

        self.assertEqual(seen, [True])
        self.assertFalse(box._title_actions_hold)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```powershell
python -m unittest tests.test_box_title_actions -v
```

预期：FAIL；测试无法从 `QtWidgets` 导入 `QGraphicsOpacityEffect`，并且 `BoxWindow` 尚无 `title_actions` 和动画接口。

### 任务 2：实现共享透明度操作区

**文件：**
- 修改：`boxes.py:47-51`（QtWidgets 导入）
- 修改：`boxes.py:1086-1098`（三个按钮的布局）
- 修改：`boxes.py:1987-2050`（事件过滤与隐藏清理）

- [ ] **步骤 1：导入透明度效果**

```python
from PySide6.QtWidgets import (QWidget, QDialog, QListWidget, QListWidgetItem,
                             QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                             QToolButton, QPushButton, QStackedLayout, QMenu,
                             QFileDialog, QLineEdit, QAbstractItemView,
                             QApplication, QStyle, QGraphicsOpacityEffect)
```

- [ ] **步骤 2：把三个按钮移入共享操作区**

```python
self.title_actions = QWidget()
ta = QHBoxLayout(self.title_actions)
ta.setContentsMargins(0, 0, 0, 0)
ta.setSpacing(ui.sc(4))
self.btn_collapse = QToolButton()
self.btn_collapse.setFixedSize(ui.sc(22), ui.sc(20))
self.btn_collapse.clicked.connect(
    lambda: self.set_collapsed(not self.rec['collapsed']))
ta.addWidget(self.btn_collapse)
self.btn_lock = QToolButton()
self.btn_lock.setFixedSize(ui.sc(22), ui.sc(20))
self.btn_lock.clicked.connect(
    lambda: self.set_locked(not self.rec['locked']))
ta.addWidget(self.btn_lock)
self.btn_menu = QToolButton()
self.btn_menu.setText('≡')
self.btn_menu.setFixedSize(ui.sc(22), ui.sc(20))
self.btn_menu.clicked.connect(self._show_menu)
ta.addWidget(self.btn_menu)
tb.addWidget(self.title_actions)

self._title_actions_effect = QGraphicsOpacityEffect(self.title_actions)
self._title_actions_effect.setOpacity(0.0)
self.title_actions.setGraphicsEffect(self._title_actions_effect)
self.title_actions.setAttribute(Qt.WA_TransparentForMouseEvents, True)
self._title_actions_target = 0.0
self._title_actions_hold = False
self._title_actions_timer = QTimer(self)
self._title_actions_timer.setSingleShot(True)
self._title_actions_timer.setInterval(30)
self._title_actions_timer.timeout.connect(self._title_actions_tick)
self._title_actions_anim = QVariantAnimation(self)
self._title_actions_anim.setEasingCurve(QEasingCurve.InOutQuad)
self._title_actions_anim.valueChanged.connect(
    self._set_title_actions_opacity)
self._title_actions_anim.finished.connect(
    self._finish_title_actions_fade)
self._title_hover_widgets = (
    self.title, self.title_actions, self.btn_collapse,
    self.btn_lock, self.btn_menu)
```

- [ ] **步骤 3：实现动画与悬停复核**

```python
def _set_title_actions_opacity(self, value):
    self._title_actions_effect.setOpacity(float(value))

def _finish_title_actions_fade(self):
    value = 0.0 if self._title_actions_target <= 0 else 1.0
    self._set_title_actions_opacity(value)
    self.title_actions.setAttribute(
        Qt.WA_TransparentForMouseEvents, value <= 0)

def _show_title_actions(self):
    self._title_actions_timer.stop()
    if self._title_actions_target == 1.0 and \
            self._title_actions_anim.state() == QVariantAnimation.Running:
        return
    self._fade_title_actions(1.0)

def _hide_title_actions(self, immediate=False):
    if self._title_actions_hold and not immediate:
        return
    self._title_actions_timer.stop()
    if immediate:
        self._title_actions_anim.stop()
        self._title_actions_target = 0.0
        self._finish_title_actions_fade()
        return
    self._fade_title_actions(0.0)

def _fade_title_actions(self, target):
    self._title_actions_anim.stop()
    self._title_actions_target = target
    self.title_actions.setAttribute(
        Qt.WA_TransparentForMouseEvents, target <= 0)
    self._title_actions_anim.setDuration(140 if target > 0 else 180)
    self._title_actions_anim.setStartValue(
        self._title_actions_effect.opacity())
    self._title_actions_anim.setEndValue(target)
    self._title_actions_anim.start()

def _schedule_title_actions_hide(self):
    if not self._title_actions_hold:
        self._title_actions_timer.start()

def _title_actions_tick(self):
    if self._title_actions_hold or \
            QApplication.activePopupWidget() is not None or \
            QApplication.activeModalWidget() is not None:
        return
    pos = self.title.mapFromGlobal(QCursor.pos())
    if self.title.rect().contains(pos):
        return
    self._hide_title_actions()
```

- [ ] **步骤 4：把进入/离开事件接到顶部栏**

在 `eventFilter` 最前面加入：

```python
if obj in self._title_hover_widgets:
    if e.type() == QEvent.Enter:
        self._show_title_actions()
    elif e.type() == QEvent.Leave:
        self._schedule_title_actions_hide()
```

在 `hideEvent` 中调用立即隐藏：

```python
self._hide_title_actions(immediate=True)
```

- [ ] **步骤 5：菜单打开期间冻结隐藏**

```python
def _show_menu(self):
    self._title_actions_hold = True
    try:
        self._build_menu().exec(QCursor.pos())
    finally:
        self._title_actions_hold = False
        self._schedule_title_actions_hide()
```

- [ ] **步骤 6：运行新增测试**

运行：

```powershell
python -m unittest tests.test_box_title_actions -v
```

预期：PASS，3 个测试通过。

### 任务 3：全量验证与文档同步

**文件：**
- 修改：`AGENTS.md` 的桌面格子章节
- 修改：`README.md` 桌面整理功能列表
- 修改：`README.zh-CN.md` 桌面整理功能列表

- [ ] **步骤 1：运行 Python 回归测试**

```powershell
python -m unittest discover -s tests -v
```

预期：全部测试 PASS。

- [ ] **步骤 2：运行传输自检**

```powershell
python transfer_selftest.py
```

预期：输出 `SELFTEST OK`。

- [ ] **步骤 3：运行截图自检**

```powershell
$env:ZBOX_SHOT='designs\verify-title-actions'; python main.pyw
```

预期：正常导出深色/浅色全部场景截图后自动退出；普通格子标题布局不跳位，收起态截图仍正常。

- [ ] **步骤 4：同步文档**

在 README 两种语言的桌面整理功能列表中加入：

```text
顶部栏右侧的收起、锁定、菜单图标默认隐藏，鼠标移入顶部栏时淡入、移出后淡出
```

在 `AGENTS.md` 桌面格子章节加入：

```markdown
顶部栏右侧收起/锁定/菜单三个按钮放在共享操作区：默认 opacity=0 且整组鼠标穿透，
顶部栏或其子按钮 Enter 后 140ms 淡入，Leave 后延迟 30ms 复核光标仍在顶部栏外，
再以 180ms 淡出；菜单 exec 期间冻结隐藏。按钮始终保留布局宽度，淡入不会推挤标题。
```

- [ ] **步骤 5：检查并提交本功能文件**

```powershell
git diff -- boxes.py tests/test_box_title_actions.py AGENTS.md README.md README.zh-CN.md
git add boxes.py tests/test_box_title_actions.py AGENTS.md README.md README.zh-CN.md
git commit -m "feat: 桌面格子顶部操作悬停显隐"
```

预期：只提交本功能相关改动，工作区既有传输/移动端改动保持不变。
