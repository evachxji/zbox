<p align="center">
  <img src="assets/icon.png" width="96" alt="Zviber">
</p>

# Zviber 桌面日历面板

「格子」风格的 Windows 桌面日历面板：**日历 + 待办** 一体的悬浮小面板，Win7 / Win10 / Win11 通用。

## 功能

- **悬浮面板**：无边框半透明、置顶、可拖动，默认停靠桌面右下角，位置自动记忆
- **日历 tab**（默认）：周一起始月视图，双休着色、法定节假日「休」/调休「班」角标、农历与节日副标题、滚轮翻月、「今日」一键回当月
- **待办 tab**：双击空白处（或点底部提示条）新建待办；左侧 checkbox 勾选即完成，置灰 + 删除线并沉到列表底部，取消勾选回到顶部；右键条目可编辑/删除
- **双栏模式**：设置窗口或托盘菜单开启，左日历右待办同屏显示
- **设置窗口**：标题栏 ⚙ 弹出无边框设置窗口（主题/双栏/下班倒计时/自启/节假日数据），改动即时生效
- **两套主题**：设置窗口或托盘菜单切换 —— 深色（默认）/ 浅色，自动记忆
- **节假日数据**：内置 2025/2026 国务院官方调休安排；托盘菜单「节假日数据」支持联网更新（timor.tech API）或离线导入 jiejiariapi.com 下载的 JSON（内网可用）
- **系统集成**：开机无感自启（pythonw 静默运行）；桌面右键菜单「悬浮日历待办」一键开关

## 运行

```bat
pip install PyQt5
python install.py        :: 一次性安装（右键菜单 + 开机自启，HKCU 免管理员）
pythonw main.pyw         :: 或直接启动
```

卸载：`python install.py --remove`

## 兼容性说明

- 基于 PyQt5（Qt 5.15）：Win7 / Win10 / Win11 均支持
- Win7 部署：安装 Python 3.8.x（最后一个支持 Win7 的版本）+ `pip install "PyQt5==5.15.*"`
- 数据存放 `%APPDATA%\ZviberPanel\`：`config.json`（主题/位置/模式）、`todos.json`（待办）、`holidays.json`（导入的节假日）
- 其余年份无官方调休数据时，仍显示双休与农历节日，仅不标「休/班」角标

## 自检

```bat
set ZVIBER_SHOT=designs\verify && python main.pyw
```
导出两主题 × 日历/待办/双栏截图到指定目录后自动退出。

## License

[MIT](LICENSE)
