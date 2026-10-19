# 桌面卡片同边吸附实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 桌面格子在移动、缩放时只吸附同边；日历悬浮面板只在移动时吸附，缩放不吸附。左右或上下两条边同时对齐时逐条显示辅助线。

**架构：** `snapping.py` 提供 `snap_move`、`snap_resize`、`guide_segments` 与 `SnapGuideOverlay`。`boxes.py` 在格子拖拽和自定义缩放中调用；`app.py` 只在悬浮面板拖拽中调用。`guide_segments` 按最终几何逐边列出所有实际对齐线。

**技术栈：** Python 3.10+、PySide6 `QRect`、`unittest`。

---

### 任务 1：共享吸附求解器

**文件：**
- 创建：`snapping.py`
- 测试：`tests/test_box_snap.py`

- [x] **步骤 1：编写失败测试**

覆盖左对左、右对右、上对上、下对下、相对边不吸附、8px 进入、12px 迟滞释放、横纵轴同时吸附和辅助线端点。

- [x] **步骤 2：运行测试验证失败**

运行：`python -m unittest tests.test_box_snap -v`

预期：FAIL，提示 `snapping` 模块不存在。

- [x] **步骤 3：实现纯几何求解器**

`snap_move` 只比较同边候选；`snap_resize` 只处理正在移动的边；`guide_segments` 按最终几何逐条列出所有实际对齐边。

- [x] **步骤 4：运行测试验证通过**

运行：`python -m unittest tests.test_box_snap -v`

预期：全部通过。

### 任务 2：桌面格子接入

**文件：**
- 修改：`boxes.py`

- [x] **步骤 1：移动吸附**

`BoxWindow.mouseMoveEvent` 用当前格子、其他可见格子和悬浮面板几何调用 `snap_move`。

- [x] **步骤 2：缩放吸附**

`BoxWindow._apply_resize` 用当前移动边调用 `snap_resize`；缩放结果不得小于最小尺寸。

- [x] **步骤 3：辅助线生命周期**

吸附时调用 `SnapGuideOverlay`，释放吸附、结束拖拽、隐藏窗口时立即收起。

### 任务 3：日历悬浮面板接入

**文件：**
- 修改：`app.py`

- [x] **步骤 1：移动吸附**

顶部栏和日历拖拽把目标窗口几何传给 `snap_move`。

- [x] **步骤 2：原生缩放不吸附**

日历原生缩放保持系统默认行为，不调用吸附求解器；`WM_ENTERSIZEMOVE` / `WM_EXITSIZEMOVE` 只维护会话状态与辅助线清理。

- [x] **步骤 3：面板与格子互吸**

`BoxManager.snap_card_rects` 收集可见格子和面板几何；面板通过 `card_rects_provider` 取得可见格子。

### 任务 4：文档与回归

**文件：**
- 修改：`README.md`
- 修改：`README.zh-CN.md`
- 修改：`AGENTS.md`

- [x] **步骤 1：同步功能说明**

说明只吸附同边、相对边不吸附，并注明格子移动/缩放与日历面板移动共用同一规则，日历缩放不吸附。

- [x] **步骤 2：运行自动化回归**

运行：`python -m unittest discover -s tests -v`

预期：全部通过。

- [x] **步骤 3：运行截图自检**

运行：`$env:ZBOX_SHOT='designs\verify'; python main.pyw`

预期：截图场景生成完成并正常退出，布局无回归。
