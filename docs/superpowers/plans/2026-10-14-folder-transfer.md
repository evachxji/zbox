# 局域网传输支持文件夹（PC 端）

> 状态：已实现（2026-10-14）

## Summary

让 PC 端传输页可以发送文件夹（拖拽或点选，可与普通文件混选），PC 端接收时在保存目录下还原目录树。协议元数据做向后兼容的可选扩展：每个文件增加 `path` 相对路径字段（posix 分隔、含顶层文件夹名），`fileName` 保持 basename 不变——旧版 PC/Android/鸿蒙端忽略该字段，文件夹内容退化为扁平收文件，不报错。空文件夹不传输（展开后无文件即忽略）。

## Key Changes

### 协议层（`transfer.py`）

- `send_files` 的 `files` 参数扩展为接受 `str` 或 `(本地路径, 相对路径)` 二元组；str 时相对路径 = basename。元数据仅在相对路径含目录时携带 `path` 字段；逐文件 upload 流程、token、cancel 语义不变。
- 接收端 `_handle_upload`：读取 `meta['path']`，按 `/` 分段，每段过 `_sanitize_filename`，剔除 `''`/`'.'`/`'..'` 段，清洗后为空的段用 `'_'` 兜底；无有效段退回现有 basename 扁平逻辑。有目录段时 `os.makedirs(save_dir/各级目录, exist_ok=True)`（目录冲突=合并），文件名仍走 `_create_unique`（冲突加 ` (2)`），半成品删除与 sha256 校验逻辑不变。
- `_handle_prepare` 无需改校验（未知字段原样透传进 session）。

### 发送 UI（`transfer_ui.py`）

- `self._files` 元素改为 `(本地路径, 相对路径)` 元组，去重按本地路径。
- 新增 `_expand_paths(paths)` 辅助：文件 → `(p, basename)`；文件夹 → `os.walk`（不跟随符号链接、跳过不可读项）递归展开，相对路径含顶层文件夹名并转成 posix 分隔。空文件夹展开为 0 项，自然被忽略。
- `dropEvent` 不再用 `os.path.isfile` 过滤，改收文件+文件夹统一走 `_expand_paths`；`pick_btn` 点击改为弹两选一小菜单「选择文件」（原多选框）/「选择文件夹」（`getExistingDirectory`），可重复添加累积。
- 按钮文案/大小统计/记录 names 均基于展开后的文件清单，names 用相对路径（记录与 tooltip 里可见 `照片/a.jpg` 结构）；`_send_worker` 进度汇总逻辑不变（本来就是逐文件尺寸求和）。

### 接收 UI（`transfer_ui.py`）

- `_cb_receive_request` 的显示名：`meta['path']` 是非空字符串时用它，否则维持 basename——接收确认弹窗与记录区能看到目录结构；落盘完全由协议层负责，UI 无其他改动（记录行的 saved_path 交互不受影响）。

### 文档同步

- `AGENTS.md` 的 `transfer.py` / `transfer_ui.py` 两行各补一句文件夹支持（`path` 字段语义、接收端分段消毒、空文件夹不传）。

## Test Plan

`transfer_selftest.py` 新增 3 个用例（沿用 Ctx 双服务端 + 临时目录模式）：

1. **文件夹往返**：源目录含嵌套子目录与中文目录名，`send_files` 传 `(path, rel)` 条目 → 接收端还原出 `recv/顶层/子目录/文件`，逐文件 sha256 一致，会话正常 done。
2. **目录穿越防御**：手工 prepare-upload 携带 `../evil/x.txt`、全非法字符段、反斜杠段 → 上传落盘后 `os.path.realpath` 校验所有产物都在 save_dir 之内，无逃逸文件。
3. **兼容性回归**：不带 `path` 的元数据仍扁平落盘（现有 `case_transfer` 已覆盖，新用例只需确认带 `path` 与不带 `path` 的文件可在同一会话混传且各自落到正确位置）。

验收：`python transfer_selftest.py` 全绿打印 `SELFTEST OK`；`python -m py_compile transfer.py transfer_ui.py transfer_selftest.py` 通过；`set ZBOX_SHOT=designs\verify && python main.pyw` 截图自检确认传输页布局无回归（跑前先退出运行中的实例）。

## Assumptions

- 范围：只改 PC 端（发送文件夹 + PC 接收还原目录）；Android/鸿蒙端本次不动，旧手机端收到文件夹内容为扁平文件，属可接受降级，后续可单独给移动端加 `path` 支持。
- 追加（2026-10-14）：移动端 `path` 支持已实现——Android（`Protocol.kt` FileMeta 增 `path` 可选字段，`Receiver.kt` `safeRelParts` 分段消毒 + SAF `ensureSubdir` / MediaStore `RELATIVE_PATH` 还原目录树）与鸿蒙（`Protocol.ets` FileMeta 增 `path?`，`Receiver.ets` `safeRelParts` + 递归 `mkdirSync` 还原目录树）均按 PC 同语义消毒落盘，两端记录显示名优先 `path`。验证：`gradlew assembleDebug` 与 `hvigorw assembleHap` 均 BUILD SUCCESSFUL。
- 追加 2（2026-10-14）：移动端接收记录由「每文件一条」改为「整会话一条」（对齐 PC 端）——文件夹/多文件接收在记录页只占 1 行，显示名取顶层文件夹名或「x 等 N 个文件」，大小为会话总和、进度按累计字节聚合；鸿蒙「导出」按 `savedRels` 相对路径逐文件导出并还原目录结构。发送方记录未动（仍每文件一条）。
- 发送形态：逐文件 + 相对路径，不打 zip。
- 空文件夹不传输、不提示；只选空文件夹时选择列表为空、按钮恢复默认文案。
- 发送期间源文件被删/不可读：按现有失败路径报错并 cancel 会话，不做快照。
- 目录名冲突采取合并（Explorer 复制语义），不做文件夹级重命名。

## 现状备忘（实现前已核实的代码事实）

- 发送侧过滤点：`transfer_ui.py` `dropEvent` 与 `_pick_files` 均用 `os.path.isfile` 过滤，`self._files` 为路径列表；`_send_clicked`/`_send_worker` 逐文件 `getsize` 求和做总进度。
- 接收侧拍平点：`transfer.py` `_handle_upload` 刻意 `os.path.basename(meta['fileName'])` 防目录穿越；`_sanitize_filename` 已处理 Windows 非法字符（`:` 不写会进 NTFS 备用数据流）。
- 确认弹窗显示名来源：`transfer_ui.py` `_cb_receive_request` 从 `session['files']` 组 `view['names']`。
- 移动端接收端拍平点：Android `Receiver.kt` `sanitizeName(meta.fileName)`；鸿蒙 `Receiver.ets` 取 `fileName` 落沙箱 `received/`。JSON 新增字段对旧端透明忽略。
- 自检结构：`transfer_selftest.py` `Ctx` 起两台动态端口 `TransferServer`，`box_a/box_b['dir']` 控制接受/拒绝，`CASES` 列表追加即用例。