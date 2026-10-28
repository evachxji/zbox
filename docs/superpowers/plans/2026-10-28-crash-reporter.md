# Zbox 崩溃报告与诊断日志实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为 Python 与 Windows 原生崩溃保存脱敏文本日志和 MiniDump，并通过独立、双主题的 Zbox 弹窗引导用户提交 GitHub Issue。

**架构：** `crash_report.py` 用纯标准库负责诊断文件、脱敏与转储；`crash_reporter.py` 是独立 Qt 报告进程，负责报告整理和弹窗。`main.pyw` 在面板与 IPC 初始化前分派报告进程，并在正常实例中安装两级异常捕获。

**技术栈：** Python 3.10+ 标准库、ctypes / DbgHelp MiniDumpWriteDump、PySide6、unittest、现有 themes.py QSS。

---

## 文件结构

- 创建 `crash_report.py`：诊断目录、系统信息、脱敏、报告文本、Issue URL、MiniDump 和原生异常过滤器。
- 创建 `crash_reporter.py`：独立报告进程入口、主题/语言恢复、崩溃弹窗与三个用户动作。
- 修改 `main.pyw`：早期报告进程分派，替换调试 excepthook，接入原生异常过滤器并记录 faulthandler 偏移。
- 修改 `i18n_zh.py`、`i18n_en.py`：崩溃弹窗和 Issue 模板文案。
- 创建 `tests/test_crash_report.py`：纯逻辑、文件与真实 MiniDump 测试。
- 创建 `tests/test_crash_reporter.py`：弹窗、主题、图标、按钮和入口隔离测试。
- 修改 `tests/test_pc_localization_coverage.py`：把 `crash_reporter.py` 纳入用户可见硬编码扫描。

### 任务 1：诊断目录、脱敏、文本报告与 Issue URL

**文件：**
- 创建：`crash_report.py`
- 创建：`tests/test_crash_report.py`

- [ ] **步骤 1：编写失败的纯逻辑测试**

```python
# tests/test_crash_report.py
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import crash_report


class CrashReportTest(unittest.TestCase):
    def test_sanitize_text_removes_home_and_username(self):
        text = r'Traceback C:\Users\alice\demo\main.py: alice failed'
        with patch.dict(os.environ, {'USERPROFILE': r'C:\Users\alice', 'USERNAME': 'alice'}):
            result = crash_report.sanitize_text(text)
        self.assertNotIn(r'C:\Users\alice', result)
        self.assertNotIn('alice', result)
        self.assertIn('<UserProfile>', result)
        self.assertIn('<User>', result)

    def test_report_dirs_never_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime(2026, 10, 28, 12, 0, 0)
            one = crash_report.create_report_dir(tmp, now=now, pid=42)
            two = crash_report.create_report_dir(tmp, now=now, pid=42)
            self.assertNotEqual(one, two)
            self.assertTrue(os.path.isdir(one))
            self.assertTrue(os.path.isdir(two))

    def test_system_info_has_only_approved_fields(self):
        info = crash_report.system_info()
        self.assertEqual(set(info), {
            'Zbox', 'Runtime', 'Architecture', 'Python',
            'Windows', 'Windows build', 'System architecture',
        })
        self.assertNotIn('Computer name', info)
        self.assertNotIn('Username', info)

    def test_python_report_contains_trace_and_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = crash_report.create_report_dir(tmp)
            path = crash_report.write_report(
                report_dir, python_trace='ValueError: bad\nTraceback line',
                native_trace='', native_error='', dump_error='',
                qt_version='6.8.3', pyside_version='6.8.3')
            with open(path, encoding='utf-8') as f:
                text = f.read()
            self.assertIn('ValueError: bad', text)
            self.assertIn('Traceback line', text)
            self.assertIn('Qt: 6.8.3', text)
            self.assertIn('PySide6: 6.8.3', text)

    def test_issue_url_prefills_metadata_but_not_trace(self):
        url = crash_report.build_issue_url('ValueError: bad', True, True)
        query = parse_qs(urlparse(url).query)
        self.assertEqual(urlparse(url).path, '/evachxji/zbox/issues/new')
        self.assertIn('ValueError', query['title'][0])
        self.assertIn('Reproduction steps', query['body'][0])
        self.assertIn('memory', query['body'][0])
        self.assertNotIn('Traceback', url)
```

- [ ] **步骤 2：运行测试确认因模块缺失而失败**

运行：`python -m unittest tests.test_crash_report -v`

预期：FAIL，`ModuleNotFoundError: No module named 'crash_report'`。

- [ ] **步骤 3：实现最小纯标准库模块**

```python
# crash_report.py 的公开接口与关键实现
import os
import platform
import re
import sys
from datetime import datetime
from urllib.parse import urlencode
from version import APP_VERSION, GITHUB_URL


def sanitize_text(text, home=None, username=None):
    home = home if home is not None else os.path.expanduser('~')
    username = username if username is not None else os.environ.get('USERNAME', '')
    if home:
        text = re.sub(re.escape(home), '<UserProfile>', text, flags=re.IGNORECASE)
    if username:
        text = re.sub(r'(?<![\w])' + re.escape(username) + r'(?![\w])',
                      '<User>', text, flags=re.IGNORECASE)
    return text


def create_report_dir(base_dir, now=None, pid=None):
    now = now or datetime.now()
    stem = '%s_%d' % (now.strftime('%Y%m%d_%H%M%S'), pid or os.getpid())
    for index in range(1000):
        suffix = '' if index == 0 else '_%d' % index
        path = os.path.join(base_dir, 'crash', stem + suffix)
        try:
            os.makedirs(path)
            return path
        except FileExistsError:
            pass
    raise OSError('Cannot allocate a unique crash report directory')


def system_info():
    return {
        'Zbox': APP_VERSION,
        'Runtime': 'frozen' if getattr(sys, 'frozen', False) else 'source',
        'Architecture': platform.architecture()[0],
        'Python': platform.python_version(),
        'Windows': platform.system() + ' ' + platform.release(),
        'Windows build': platform.version(),
        'System architecture': platform.machine(),
    }


def write_report(report_dir, python_trace='', native_trace='', native_error='',
                 dump_error='', qt_version='unknown', pyside_version='unknown'):
    # 以固定字段顺序写 UTF-8 文本；异常文本先经 sanitize_text。
    # 文件名为 report_dir/zbox-crash.log，函数返回该路径。
    sections = ['Zbox crash report', 'Time: ' + datetime.now().astimezone().isoformat()]
    sections += ['%s: %s' % item for item in system_info().items()]
    sections += ['PySide6: ' + pyside_version, 'Qt: ' + qt_version]
    sections += ['Python exception:', sanitize_text(python_trace or '(none)'),
                 'Native exception:', sanitize_text(native_error or '(none)'),
                 'Native stack:', sanitize_text(native_trace or '(none)'),
                 'Dump error:', sanitize_text(dump_error or '(none)')]
    path = os.path.join(report_dir, 'zbox-crash.log')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(sections) + '\n')
    return path


def build_issue_url(summary, log_ready, dump_ready):
    title = '[Crash] Zbox %s %s' % (APP_VERSION, sanitize_text(summary)[:100])
    body = ('## Reproduction steps\n\n1. \n\n## Environment\n\n'
            'Zbox: %s\n\n## Attachments\n\n- [ ] zbox-crash.log (%s)\n'
            '- [ ] zbox-crash.dmp (%s; may contain process memory)\n' %
            (APP_VERSION, 'available' if log_ready else 'not generated',
             'available' if dump_ready else 'not generated'))
    return GITHUB_URL + '/issues/new?' + urlencode({'title': title, 'body': body})
```

- [ ] **步骤 4：运行测试确认通过**

运行：`python -m unittest tests.test_crash_report -v`

预期：5 个用例全部 PASS，且没有未处理警告。

- [ ] **步骤 5：提交本任务**

```powershell
git add crash_report.py tests/test_crash_report.py
git commit -m "feat: 添加崩溃诊断报告核心"
```

### 任务 2：真实 MiniDump、Python 异常现场与原生过滤器

**文件：**
- 修改：`crash_report.py`
- 修改：`tests/test_crash_report.py`

- [ ] **步骤 1：追加失败的 MiniDump 与异常现场测试**

```python
    def test_write_real_minidump(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'zbox-crash.dmp')
            crash_report.write_minidump(path)
            with open(path, 'rb') as f:
                self.assertEqual(f.read(4), b'MDMP')
            self.assertGreater(os.path.getsize(path), 1024)

    def test_python_exception_writes_raw_trace_and_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                raise ValueError('bad value')
            except ValueError:
                import sys
                report_dir = crash_report.report_python_exception(
                    *sys.exc_info(), data_dir=tmp, launch=False)
            with open(os.path.join(report_dir, 'python.txt'), encoding='utf-8') as f:
                self.assertIn('ValueError: bad value', f.read())
            with open(os.path.join(report_dir, 'zbox-crash.dmp'), 'rb') as f:
                self.assertEqual(f.read(4), b'MDMP')

    def test_reporter_command_uses_current_executable_and_early_mode(self):
        with patch.object(crash_report.sys, 'argv', ['main.pyw']), \
                patch.object(crash_report.sys, 'executable', r'C:\Python\pythonw.exe'), \
                patch.object(crash_report, 'BASE_DIR', r'D:\zbox'):
            cmd = crash_report.reporter_command(r'C:\report', 'native.log', 12)
        self.assertEqual(cmd[1:3], [r'D:\zbox\main.pyw', '--crash-reporter'])
        self.assertIn('--native-offset', cmd)
```

- [ ] **步骤 2：运行新增测试确认失败**

运行：`python -m unittest tests.test_crash_report.CrashReportTest.test_write_real_minidump tests.test_crash_report.CrashReportTest.test_python_exception_writes_raw_trace_and_dump tests.test_crash_report.CrashReportTest.test_reporter_command_uses_current_executable_and_early_mode -v`

预期：FAIL，提示缺少 `write_minidump`、`report_python_exception` 和 `reporter_command`。

- [ ] **步骤 3：实现 MiniDump 和 Python 异常报告**

```python
import ctypes
import json
import subprocess
import traceback
from ctypes import wintypes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_native_callback = None
_previous_filter = None


def reporter_command(report_dir, native_log='', native_offset=0):
    if getattr(sys, 'frozen', False):
        cmd = [sys.executable]
    else:
        cmd = [sys.executable, os.path.join(BASE_DIR, 'main.pyw')]
    return cmd + ['--crash-reporter', report_dir,
                  '--native-log', native_log, '--native-offset', str(native_offset)]


def launch_reporter(report_dir, native_log='', native_offset=0):
    return subprocess.Popen(reporter_command(report_dir, native_log, native_offset),
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                            close_fds=True)


def write_minidump(path, exception_pointers=None):
    # Windows 以外仅用于源码静态检查；真实测试只在 Windows 运行。
    process = ctypes.windll.kernel32.GetCurrentProcess()
    pid = ctypes.windll.kernel32.GetCurrentProcessId()
    flags = 0x00000000  # MiniDumpNormal
    with open(path, 'wb') as output:
        info = None
        if exception_pointers is not None:
            info = MINIDUMP_EXCEPTION_INFORMATION(
                exception_pointers, ctypes.windll.kernel32.GetCurrentThreadId(), False)
        ok = ctypes.windll.dbghelp.MiniDumpWriteDump(
            wintypes.HANDLE(process), wintypes.DWORD(pid),
            wintypes.HANDLE(ctypes.c_void_p(output.fileno())), flags,
            ctypes.byref(info) if info is not None else None, None, None)
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())


def report_python_exception(exc_type, exc_value, tb, data_dir, launch=True,
                            native_log='', native_offset=0):
    report_dir = create_report_dir(data_dir)
    trace = ''.join(traceback.format_exception(exc_type, exc_value, tb))
    with open(os.path.join(report_dir, 'python.txt'), 'w', encoding='utf-8') as f:
        f.write(sanitize_text(trace))
    dump_error = ''
    try:
        write_minidump(os.path.join(report_dir, 'zbox-crash.dmp'))
    except Exception as exc:
        dump_error = str(exc)
    with open(os.path.join(report_dir, 'dump_error.txt'), 'w', encoding='utf-8') as f:
        f.write(dump_error)
    if launch:
        launch_reporter(report_dir, native_log, native_offset)
    return report_dir
```

同时定义 Windows `EXCEPTION_RECORD`、`EXCEPTION_POINTERS` 和 `MINIDUMP_EXCEPTION_INFORMATION` ctypes 结构，确保 `ExceptionPointers` 可直接传给 DbgHelp。`write_minidump` 的文件句柄通过 `msvcrt.get_osfhandle(output.fileno())` 取得，而不是直接传 `fileno()`。

- [ ] **步骤 4：实现并测试原生过滤器**

```python
def install_native_handler(data_dir, native_log, native_offset):
    # 必须在 faulthandler.enable 后调用，以保存并链式调用它安装的 previous filter。
    # 回调内依次：调用 previous、flush native_log、create_report_dir、
    # write_minidump(exception_pointers)、写 native.json、launch_reporter。
    # 所有异常都捕获，最终返回 EXCEPTION_EXECUTE_HANDLER (1)。
    global _native_callback, _previous_filter
    # 具体实现使用 kernel32.SetUnhandledExceptionFilter；回调保存在模块全局防止 GC。
```

追加测试：用 `unittest.mock.patch` 替换 `write_minidump` 和 `launch_reporter`，直接调用已保存回调并断言收到原始 `EXCEPTION_POINTERS`、生成 `native.json` 且始终返回 `1`；验证 `write_minidump` 抛错时仍启动报告进程。

运行：`python -m unittest tests.test_crash_report -v`

预期：全部 PASS；真实 `.dmp` 文件头为 `MDMP`。

- [ ] **步骤 5：提交本任务**

```powershell
git add crash_report.py tests/test_crash_report.py
git commit -m "feat: 保存 Python 与原生崩溃转储"
```

### 任务 3：双主题报告弹窗与独立入口

**文件：**
- 创建：`crash_reporter.py`
- 修改：`i18n_zh.py`
- 修改：`i18n_en.py`
- 修改：`tests/test_pc_localization_coverage.py`
- 创建：`tests/test_crash_reporter.py`

- [ ] **步骤 1：编写失败的弹窗测试**

```python
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
import crash_reporter


class CrashReporterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        for name in ('zbox-crash.log', 'zbox-crash.dmp'):
            with open(os.path.join(self.tmp.name, name), 'wb') as f:
                f.write(b'x')
        self.dialog = crash_reporter.CrashDialog(self.tmp.name, 'nocturne')
        self.addCleanup(self.dialog.close)

    def test_window_uses_real_zbox_icon_and_file_status(self):
        self.assertFalse(self.dialog.windowIcon().isNull())
        self.assertTrue(self.dialog.log_status.isVisible())
        self.assertTrue(self.dialog.dump_status.isVisible())

    def test_copy_button_copies_full_report_directory(self):
        self.dialog.copy_btn.click()
        self.assertEqual(self.qapp.clipboard().text(), self.tmp.name)

    def test_open_directory_uses_local_file_url(self):
        with patch.object(crash_reporter.QDesktopServices, 'openUrl') as open_url:
            self.dialog.open_btn.click()
        self.assertTrue(open_url.call_args[0][0].isLocalFile())

    def test_issue_button_does_not_put_log_contents_in_url(self):
        with patch.object(crash_reporter.QDesktopServices, 'openUrl') as open_url:
            self.dialog.issue_btn.click()
        url = open_url.call_args[0][0].url()
        self.assertIn('/issues/new?', url)
        self.assertNotIn('Traceback', url)
```

把 `crash_reporter.py` 加入 `UI_FILES`，运行现有词典一致性测试，确保新增中英文键完全对齐。

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m unittest tests.test_crash_reporter -v`

预期：FAIL，`ModuleNotFoundError: No module named 'crash_reporter'`。

- [ ] **步骤 3：添加中英文文案**

在两份词典中加入相同键：

```python
'crash.window': 'Zbox',
'crash.title': '程序已崩溃',
'crash.message': '抱歉给你带来不便。诊断文件已保存，提交日志可以帮助我们定位并修复问题。',
'crash.saved_at': '诊断文件保存在',
'crash.open_dir': '打开日志目录',
'crash.issue': '去 GitHub 提交 Issue',
'crash.log_ready': '文本日志：已生成',
'crash.log_missing': '文本日志：生成失败',
'crash.dump_ready': '崩溃转储：已生成',
'crash.dump_missing': '崩溃转储：生成失败',
'crash.privacy': '文本日志已脱敏；.dmp 可能包含进程内存，公开提交前请自行确认。',
```

英文使用对应自然翻译，不改其他键。

- [ ] **步骤 4：实现弹窗与报告整理**

```python
# crash_reporter.py 的关键接口
class CrashDialog(QDialog):
    def __init__(self, report_dir, theme_key='nocturne'):
        super().__init__()
        self.report_dir = report_dir
        self.setObjectName('settingsDlg')
        self.setWindowTitle(t('crash.window'))
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        # 复用 settingsPanel/setTitle/setBtn/setSave/closeBtn QSS；
        # 创建 copy_btn/open_btn/issue_btn/log_status/dump_status 供测试和交互使用。
```

实现约束：

- `app_icon()`：frozen 时使用 `QIcon(sys.executable)`，源码时使用 `assets/icon.png`，不得导入重量级 `app.py`。
- 复制按钮把完整 `report_dir` 写入剪贴板；打开目录使用 `QUrl.fromLocalFile`；Issue URL 由 `crash_report.build_issue_url` 生成。
- `_read_config()` 只读 `%APPDATA%\zbox\config.json` 的 `language` 和 `theme`，不写回配置；`auto` 用 `sysutil.system_uses_light_theme()` 解析。
- `main(argv)` 解析报告目录、`--native-log` 和 `--native-offset`，读取 `python.txt`、本次偏移后的原生堆栈及 `native.json` / `dump_error.txt`，调用 `write_report` 后再实例化弹窗。
- `main(argv)` 创建独立 `QApplication`，用 `themes.build_qss` 设置当前主题；不传重量级面板参数，不启动 IPC、热键、菜单、传输或下载任务。
- 报告整理即使缺少某个输入文件也继续，弹窗根据 `.log` / `.dmp` 实际存在状态显示结果。

- [ ] **步骤 5：运行界面与词典测试确认通过**

运行：`python -m unittest tests.test_crash_reporter tests.test_i18n tests.test_pc_localization_coverage -v`

预期：全部 PASS；弹窗图标非空，三个按钮动作符合断言，无用户可见中文硬编码遗漏。

- [ ] **步骤 6：提交本任务**

```powershell
git add crash_reporter.py i18n_zh.py i18n_en.py tests/test_crash_reporter.py tests/test_pc_localization_coverage.py
git commit -m "feat: 添加双主题崩溃报告弹窗"
```

### 任务 4：接入 main.pyw 并保持正常生命周期

**文件：**
- 修改：`main.pyw`
- 修改：`tests/test_crash_reporter.py`

- [ ] **步骤 1：编写入口顺序与异常钩子失败测试**

```python
from pathlib import Path


def test_reporter_dispatch_precedes_panel_import_and_ipc():
    source = Path('main.pyw').read_text(encoding='utf-8')
    dispatch = source.index("if sys.argv[1:2] == ['--crash-reporter']:")
    self.assertLess(dispatch, source.index('import app as ui'))
    self.assertLess(dispatch, source.index('def notify_existing'))


def test_python_hook_reports_then_exits():
    with patch.object(main.crash_report, 'report_python_exception') as report, \
            patch.object(main.os, '_exit') as exit_process:
        main._crash_excepthook(ValueError, ValueError('bad'), None)
    report.assert_called_once()
    exit_process.assert_called_once_with(1)
```

导入 `main` 的测试使用 `QT_QPA_PLATFORM=offscreen`，只调用钩子，不执行 `main.main()`。

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m unittest tests.test_crash_reporter.CrashMainIntegrationTest -v`

预期：FAIL，找不到早期分派和 `_crash_excepthook`。

- [ ] **步骤 3：接入早期分派、Python 钩子和原生过滤器**

```python
# main.pyw：位于 import app as ui 之前
if sys.argv[1:2] == ['--crash-reporter']:
    import crash_reporter
    sys.exit(crash_reporter.main(sys.argv[2:]))
```

```python
def _crash_excepthook(exc_type, exc_value, tb):
    try:
        crash_report.report_python_exception(
            exc_type, exc_value, tb, sysutil.appdata_dir(),
            native_log=_crash_log[0].name if _crash_log[0] else '',
            native_offset=_native_log_offset[0])
    except Exception:
        pass
    os._exit(1)
```

在 `main()` 中用 `_crash_excepthook` 替换 `_debug_excepthook`，删除因此失效的旧调试函数；保留 `faulthandler.enable` 并在其后立即记录：

```python
_native_log_offset = [0]\n_native_log_offset[0] = _crash_log[0].tell()
crash_report.install_native_handler(
    sysutil.appdata_dir(), _crash_log[0], _native_log_offset[0])
```

确保安装顺序为 `faulthandler.enable` → 记录偏移 → `install_native_handler`，以便链式调用 faulthandler 的过滤器。正常 `aboutToQuit` 清理逻辑不改。

- [ ] **步骤 4：运行集成和现有入口测试**

运行：`python -m unittest tests.test_crash_reporter tests.test_dpi_scaling -v`

预期：全部 PASS；报告模式分派位于 `import app as ui` 与 IPC 之前，正常 DPI 初始化顺序不变。

- [ ] **步骤 5：提交本任务**

```powershell
git add main.pyw tests/test_crash_reporter.py
git commit -m "feat: 在应用入口接入崩溃报告"
```

### 任务 5：受控崩溃、视觉检查与全量回归

**文件：**
- 修改：`crash_report.py`、`crash_reporter.py`（仅用于修复验证发现的问题）
- 修改：`tests/test_crash_report.py`、`tests/test_crash_reporter.py`（先增加能复现问题的失败测试）

- [ ] **步骤 1：验证 Python 崩溃的真实进程接管**

在开发终端启动一个会进入 Qt 事件循环并抛出异常的独立测试实例：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -c "import main; main.QTimer.singleShot(0, lambda: (_ for _ in ()).throw(ValueError('controlled crash'))); main.main()"
```

预期：测试实例退出码为 `1`；独立报告进程生成新的 `%APPDATA%\zbox\crash\日期_时间_PID` 目录；`.log` 可读、`.dmp` 以 `MDMP` 开头；弹窗显示并能在 offscreen 验证后由测试进程关闭。正常用户实例不参与 IPC。

- [ ] **步骤 2：验证原生访问冲突的真实转储**

在独立测试实例中触发：

```powershell
python -c "import ctypes, main; main.QTimer.singleShot(0, lambda: ctypes.string_at(0)); main.main()"
```

预期：原进程终止，不卡死；`faulthandler` 追加本次堆栈；报告进程生成 `.log` 和有效 `.dmp`，`native.json` 的异常代码/地址进入文本报告。若验证失败，先添加可复现单元测试再修复，不通过跳过异常来伪造成功。

- [ ] **步骤 3：检查双主题视觉与交互**

用 `crash_reporter.main` 分别设置 `nocturne` / `mica` 和中英文渲染弹窗，执行 `QWidget.grab()` 保存开发截图；检查真实 Zbox 图标、长路径换行、按钮不裁切、文件状态及隐私提示。点击或自动化触发复制、打开目录和 Issue，确认不会自动上传文件。

- [ ] **步骤 4：验证正常生命周期无副作用**

```powershell
python -c "import main; main.QTimer.singleShot(1000, main.QApplication.instance().quit); main.main()"
```

预期：正常退出，不创建新的 `.dmp`，不启动报告进程，不弹出崩溃窗口；已有单实例、菜单和热键清理保持原行为。

- [ ] **步骤 5：运行完整测试集与静态检查**

```powershell
python -m unittest discover -s tests -v
git diff --check
git status --short
```

预期：所有现有及新增用例 PASS；`git diff --check` 无输出；工作区只包含本功能文件。

- [ ] **步骤 6：提交验证修复**

```powershell
git add crash_report.py crash_reporter.py tests/test_crash_report.py tests/test_crash_reporter.py
git commit -m "test: 完善崩溃报告回归验证"
```

若没有验证修复需要提交，不创建空提交；直接报告测试结果和生成的诊断样例位置。

