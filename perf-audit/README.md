# perf-audit —— 性能审计工作区

本目录是 zbox 性能审计任务的**独立工作区**：所有临时脚本、测量数据、中间产物都放这里，
不污染仓库原有结构（`tools/`、`tests/`、`docs/superpowers/` 等原有内容保持不动）。

## 目录内容

| 路径 | 说明 |
|---|---|
| `probe.py` | 性能基线探针（零侵入，不改业务代码）。测冷/热启动耗时、内存、CPU、句柄/线程/GDI-User 对象数、长跑内存曲线、import 开销分解 |
| `stage_probe.py` | 启动分阶段打点（进程内插桩，**不改 `main.pyw` 一行代码**）：import → QApplication → 各对象构造 → show → 事件循环首拍，并累计计时 boxes/app/transfer 的内部函数 |
| `flame.py` | py-spy 采样启动期 CPU 热点，聚合栈帧占比 |
| `microbench.py` | 文件操作微基准：100 / 1000 / 10000 条目下的 scandir、stat、图标提取耗时 |
| `icon_bench.py` | 图标提取耗时归因：`.txt` vs 真实目录（`.lnk` 为主），定位**秒级长尾**条目 |
| `dbg_io.py` | 精确测量 `_dbg` 的写盘频率与吞吐（行/秒、字节/秒） |
| `results/` | 测量结果原始 JSON（优化前 / 优化后各一份，便于 diff 对比） |
| `tmp/` | 探针运行时的临时目录（隔离 APPDATA 用），可随时清空 |

## 用法

```bat
:: 确认没有 zbox 实例在跑（否则启动会被 IPC 转发、测量失真）
python perf-audit\probe.py info

:: 冷启动耗时（每次都用空的 APPDATA，模拟首次运行）
python perf-audit\probe.py startup --runs 5

:: 稳态空闲 CPU / 内存
python perf-audit\probe.py idle --seconds 60

:: 长跑内存曲线（查泄漏）
python perf-audit\probe.py longrun --seconds 600 --interval 15

:: import 开销分解
python perf-audit\probe.py imports

:: 启动分阶段归因（最关键的一张表）
python perf-audit\stage_probe.py --out perf-audit\results\stage.json

:: CPU 热点采样
python perf-audit\flame.py --tag baseline

;; 图标提取归因（找秒级长尾条目）
python perf-audit\icon_bench.py --dir "D:\Document\桌面快捷方式"

:: _dbg 写盘频率
python perf-audit\dbg_io.py --seconds 60
```

## 隔离说明

探针给子进程设 `APPDATA=<临时目录>`，让 zbox 的配置 / 盒子数据写到临时处，
**不碰用户的 `%APPDATA%\zbox`，也不改变桌面图标状态**。

⚠️ Windows 上 Python 的用户级 site-packages 默认在 `%APPDATA%\Python\Python312\site-packages`，
改 `APPDATA` 会一并屏蔽它（PySide6 就装在那里）——探针因此显式把原 site-packages 路径
写进子进程的 `PYTHONPATH`。

## 术语

- **进程冷启动**：进程从创建到主面板窗口可见且消息循环可响应（`WM_NULL` 往返成功）。
- Windows 层面的「清空文件缓存后冷启动」需管理员 + 第三方工具，本探针不做，
  所有数字均为**进程冷启动**。
