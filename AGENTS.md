# Repository Guidelines

## Project Structure & Module Organization

Zviber 是 Windows 桌面悬浮面板（日历 + 待办），PyQt5，Python 3.8+，Win7 / Win10 / Win11 通用。
平铺布局，一个模块一个职责：

- `main.pyw` — 入口：单实例 IPC（`QLocalServer`）、系统托盘、节假日后台更新、（frozen 时）安装/卸载流程
- `app.py` — 面板 UI（日历 / 待办 / 双栏 / 顶部栏滑出与拖动）、`SettingsDialog` 与节假日导入引导窗
- `calendar_data.py` — 内置国务院节假日数据、农历换算、三源联网回退与离线导入
- `themes.py` — 两套主题 QSS（深色 `nocturne` / 浅色 `mica`）加 `auto` 伪主题；`%CN%`/`%NUM%` 为字体占位符
- `version.py` — 版本号唯一来源：关于窗、设置窗左下角、安装向导、卸载注册表项共用 `APP_VERSION`，发版只改这一个文件
- `sysutil.py` — 注册表集成：开机自启、桌面右键菜单、应用列表卸载项（默认 HKCU，免管理员）
- `installer.py` — exe 安装向导与自安装/卸载（只在 frozen 时生效）
- `install.py` — 源码方式的系统集成（只装开机自启）
- `build.py` / `build.cmd` — 生成图标与 DPI 清单，PyInstaller 打包 `dist\ZviberPanel.exe`
- `run.cmd` — 双击启动面板；已在运行则切换显隐
- `designs/` — 两套主题的设计稿（HTML，浏览器可直接打开）
- `CLAUDE.md` — 架构细节、不显然的约定与坑位，动代码前先读

运行时数据在 `%APPDATA%\ZviberPanel\`（`config.json` / `todos.json` / `holidays.json` / `icons/`）——不要提交。

## Build, Test, and Development Commands

```bat
pip install PyQt5            :: 唯一依赖（Win7 需 Python 3.8 + "PyQt5==5.15.*"）
pythonw main.pyw             :: 源码方式运行（或双击 run.cmd）
python build.py              :: 打包 exe 安装包（或双击 build.cmd）
python install.py            :: 源码方式开启开机自启
python install.py --remove   :: 移除自启并清理旧的右键菜单
set ZVIBER_SHOT=designs\verify && python main.pyw   :: 截图自检
```

自检导出两主题 × 日历/待办/双栏截图后自动退出，改 UI / 主题 / 布局后必跑。
**跑之前先退出正在运行的实例**：否则单实例分支会把这次启动当成一次 `--toggle` 转发给已运行实例
（用户的面板被显隐一次），本进程直接退出，一张图都不会导出，而且没有任何报错。
截图目录与设计稿渲染图已 gitignore，不要提交。

## Coding Style & Naming Conventions

- 每个模块首行 `# -*- coding: utf-8 -*-`，4 空格缩进
- `snake_case` 函数、`UPPER_SNAKE` 常量、单引号字符串、`%` 格式化
- 模块 docstring 与行内注释一律中文——保持这个风格
- 无 linter / formatter；保持 diff 最小、与周围代码一致
- `run.cmd` / `build.cmd` 以 GBK 保存并自带 `chcp 936`，**改完不要另存为 UTF-8**，否则双击后中文提示乱码

## Testing Guidelines

没有单元测试框架。验证 = `ZVIBER_SHOT` 截图自检 + 手动检查托盘菜单、右键菜单开关、开机自启。
改布局代码时要在 125% / 150% 缩放下确认。

## Commit & Pull Request Guidelines

仓库 [github.com/evachxji/zviber](https://github.com/evachxji/zviber)（public，MIT）。
提交用 `feat:` / `fix:` / `refactor:` / `docs:` 前缀 + 简短中英文摘要。
PR 需说明改了什么与为什么；视觉改动附自检截图；注明验证过的 Windows / Python 版本。

## Security & Configuration Tips

- 注册表只写 HKCU（免管理员）；「此计算机」安装写 HKLM 才需要 UAC 提权
- 网络访问仅限 timor.tech 的节假日接口——该接口不带 User-Agent 会回 403；
  内网用户走离线 JSON 导入，这条路径必须一直可用
