# PC 与 Android 中英双语实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** PC 与 Android 全界面支持简体中文和英文，PC 安装器改为所有用户安装并清理旧 Zbox 后重装。

**架构：** PC 新增无 Qt 依赖的 `i18n.py` 与两份词典，启动时按用户设置、机器安装语言、系统语言顺序解析。Android 新增统一的 `AppStrings` 与可观察语言设置，底部导航增加设置页。安装器复用同一 PC 词典，始终以管理员权限安装到 Program Files。

**技术栈：** Python 3.10、PySide6、Windows Registry、unittest、Kotlin、Jetpack Compose、SharedPreferences、Gradle。

---

## 文件结构

创建：

- `i18n.py`：PC 语言状态、检测、优先级解析和 `t()`。
- `i18n_zh.py`：PC 简体中文词典。
- `i18n_en.py`：PC 英文词典。
- `tests/test_i18n.py`：PC 语言核心测试。
- `tests/test_pc_localization_coverage.py`：PC UI 字面量覆盖检查。
- `tests/test_settings_language.py`：设置页语言项与重启提示测试。
- `tests/test_installer_language.py`：安装器所有用户模式、语言和清理测试。
- `android/app/src/main/java/com/zbox/transfer/AppStrings.kt`：Android 两套文案和语言状态。
- `android/app/src/main/java/com/zbox/transfer/ui/SettingsScreen.kt`：安卓设置页。
- `android/app/src/test/java/com/zbox/transfer/AppStringsTest.kt`：Android 语言规则测试。

修改：

- `main.pyw`：启动时解析语言、加载 Qt 标准控件翻译、翻译命令行目录框和通知。
- `app.py`：面板、设置、日历、待办、关于及所有弹窗文案；设置页语言下拉框和重启提示。
- `transfer_ui.py`、`video_ui.py`、`boxes.py`、`screenshot.py`、`pinshot.py`：用户可见文案。
- `sysutil.py`：PC 动态右键菜单文案和机器默认语言读取。
- `installer.py`：安装器文案、语言选择、所有用户安装、旧 Zbox 清理。
- `setup.pyw`：安装包启动时选择安装器语言并加载 Qt 翻译。
- `main.pyw`、`selfshot.py`：`ZBOX_SHOT_LANG` 截图语言测试钩子。
- `android/app/src/main/java/com/zbox/transfer/MainActivity.kt`：语言初始化与底部导航。
- `android/app/src/main/java/com/zbox/transfer/Protocol.kt`：错误码化、状态文案动态翻译。
- `android/app/src/main/java/com/zbox/transfer/Sender.kt`、`Receiver.kt`：错误码写入。
- `android/app/src/main/java/com/zbox/transfer/ui/DevicesScreen.kt`、`TransfersScreen.kt`、`ReceiveDialog.kt`：安卓文案。
- `android/app/build.gradle.kts`：Android JVM 单元测试依赖。
- `README.md`、`README.zh-CN.md`、`AGENTS.md`：功能和构建说明同步。

---

### 任务 1：PC 语言核心

**文件：**

- 创建：`i18n.py`
- 创建：`i18n_zh.py`
- 创建：`i18n_en.py`
- 测试：`tests/test_i18n.py`

- [ ] **步骤 1：编写失败测试**

```python
# tests/test_i18n.py
import unittest
from unittest.mock import patch

import i18n


class I18nCoreTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_normalize_language(self):
        self.assertEqual(i18n.normalize_language('zh_CN'), 'zh-CN')
        self.assertEqual(i18n.normalize_language('en-GB'), 'en-US')
        self.assertEqual(i18n.normalize_language('ja'), 'en-US')
        self.assertIsNone(i18n.normalize_language(''))

    def test_resolution_prefers_first_valid_candidate(self):
        self.assertEqual(i18n.resolve_language('en-US', 'zh-CN', 'en-US'), 'en-US')
        self.assertEqual(i18n.resolve_language('', 'zh-CN', 'en-US'), 'zh-CN')
        self.assertEqual(i18n.resolve_language('', '', ''), 'zh-CN')

    def test_translation_formats_and_falls_back(self):
        i18n.set_language('en-US')
        self.assertEqual(i18n.t('settings.version', version='1.2.3'), 'Version 1.2.3')
        i18n.set_language('zh-CN')
        self.assertEqual(i18n.t('settings.version', version='1.2.3'), '版本 v1.2.3')

    @patch('i18n._windows_ui_language', return_value='zh-HK')
    def test_detection_maps_chinese_variants_to_simplified(self, _ui_lang):
        self.assertEqual(i18n.detect_system_language(), 'zh-CN')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m unittest tests.test_i18n -v`

预期：FAIL，出现 `ModuleNotFoundError: No module named 'i18n'`。

- [ ] **步骤 3：实现最小语言核心**

```python
# i18n.py
import ctypes
import locale

ZH = 'zh-CN'
EN = 'en-US'
DEFAULT_LANGUAGE = ZH
LANGUAGES = (ZH, EN)
LANGUAGE_NAMES = {ZH: '简体中文', EN: 'English'}

_language = DEFAULT_LANGUAGE


def normalize_language(value):
    raw = str(value or '').strip().lower().replace('_', '-')
    if raw.startswith('zh'):
        return ZH
    if raw and len(raw.split('-', 1)[0]) in (2, 3):
        return EN
    return None


def _windows_ui_language():
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return locale.windows_locale.get(lang_id, '')
    except Exception:
        try:
            return locale.getlocale()[0] or ''
        except Exception:
            return ''


def detect_system_language():
    return normalize_language(_windows_ui_language()) or DEFAULT_LANGUAGE


def resolve_language(*candidates):
    for value in candidates:
        normalized = normalize_language(value)
        if normalized:
            return normalized
    return DEFAULT_LANGUAGE


def set_language(value):
    global _language
    _language = normalize_language(value) or DEFAULT_LANGUAGE
    return _language


def get_language():
    return _language


def t(key, **kwargs):
    from i18n_zh import CATALOG as ZH_CATALOG
    from i18n_en import CATALOG as EN_CATALOG
    catalog = EN_CATALOG if _language == EN else ZH_CATALOG
    text = catalog.get(key) or ZH_CATALOG.get(key) or key
    return text.format(**kwargs) if kwargs else text
```

```python
# i18n_zh.py
CATALOG = {
    'settings.version': '版本 v{version}',
}
```

```python
# i18n_en.py
CATALOG = {
    'settings.version': 'Version {version}',
}
```

- [ ] **步骤 4：运行测试确认通过**

运行：`python -m unittest tests.test_i18n -v`

预期：4 个测试全部 PASS。

- [ ] **步骤 5：提交**

```powershell
git add i18n.py i18n_zh.py i18n_en.py tests/test_i18n.py
git commit -m "feat: 增加 PC 双语语言核心"
```

---

### 任务 2：PC 词典与全部界面文案迁移

**文件：**

- 修改：`i18n_zh.py`
- 修改：`i18n_en.py`
- 修改：`app.py`
- 修改：`main.pyw`
- 修改：`transfer_ui.py`
- 修改：`video_ui.py`
- 修改：`boxes.py`
- 修改：`screenshot.py`
- 修改：`pinshot.py`
- 修改：`sysutil.py`
- 创建：`tests/test_pc_localization_coverage.py`

- [ ] **步骤 1：编写覆盖检查测试**

```python
# tests/test_pc_localization_coverage.py
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
UI_FILES = (
    'app.py', 'main.pyw', 'transfer_ui.py', 'video_ui.py',
    'boxes.py', 'screenshot.py', 'pinshot.py', 'sysutil.py',
)


def _docstring_nodes(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, 'body', [])
            if body and isinstance(body[0], ast.Expr):
                found.add(id(body[0].value))
    return found


class PcLocalizationCoverageTest(unittest.TestCase):
    def test_ui_files_have_no_unapproved_chinese_literals(self):
        offenders = []
        for rel in UI_FILES:
            tree = ast.parse((ROOT / rel).read_text(encoding='utf-8'))
            docstrings = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if id(node) in docstrings:
                    continue
                if any('\u4e00' <= ch <= '\u9fff' for ch in node.value):
                    offenders.append((rel, node.lineno, node.value))
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m unittest tests.test_pc_localization_coverage -v`

预期：FAIL，输出当前 UI 文件中全部中文文案字面量。

- [ ] **步骤 3：建立完整 PC 词典**

词典按域分组；所有键必须同时存在于中英文件：

```python
# i18n_zh.py
CATALOG = {
    'common.cancel': '取消',
    'common.close': '关闭',
    'common.retry': '重试',
    'common.later': '稍后',
    'app.title': 'Zbox桌面格子',
    'panel.calendar': '日历',
    'panel.todos': '待办',
    'panel.transfer': '传输',
    'panel.video': '视频解析',
    'settings.title': '设置',
    'settings.language': '语言',
    'settings.restart_required': '语言更改将在重启后生效',
    'settings.restart_now': '立即重启',
    'calendar.today': '今天',
    'calendar.off': '休',
    'calendar.work': '班',
    'todo.placeholder': '添加待办…',
    'transfer.nearby_empty': '未发现设备',
    'video.parse': '解析',
    'installer.install': '安装',
    'installer.cleaning': '正在清理旧版本…',
}
```

```python
# i18n_en.py
CATALOG = {
    'common.cancel': 'Cancel',
    'common.close': 'Close',
    'common.retry': 'Retry',
    'common.later': 'Later',
    'app.title': 'Zbox Desktop Grid',
    'panel.calendar': 'Calendar',
    'panel.todos': 'To-dos',
    'panel.transfer': 'Transfer',
    'panel.video': 'Video',
    'settings.title': 'Settings',
    'settings.language': 'Language',
    'settings.restart_required': 'The language change will take effect after restart.',
    'settings.restart_now': 'Restart now',
    'calendar.today': 'Today',
    'calendar.off': 'Off',
    'calendar.work': 'Work',
    'todo.placeholder': 'Add a to-do…',
    'transfer.nearby_empty': 'No devices found',
    'video.parse': 'Parse',
    'installer.install': 'Install',
    'installer.cleaning': 'Removing the previous version…',
}
```

完成时词典必须包含覆盖检查暴露的每个界面字符串、错误、tooltip、菜单项、窗口标题和辅助文本；中文与英文键集合保持完全一致。

- [ ] **步骤 4：迁移 UI 调用点**

每个文件顶部统一导入：

```python
from i18n import t
```

构造控件和动态状态时改用 key：

```python
self.setWindowTitle(t('settings.title'))
label = QLabel(t('settings.language'))
self.btn_parse.setText(t('video.parse'))
```

日期、数量和大小使用 kwargs：

```python
text = t('transfer.eta', value=format_duration(seconds))
```

系统右键菜单改为运行时生成，避免 import 期冻结语言：

```python
def menu_items():
    return [
        ('A_NewBox', t('menu.new_box'), '--new-box'),
        ('B_NewFolderBox', t('menu.new_folder_box'), '--pick-folder'),
        ('C_Toggle', t('menu.toggle'), '--toggle'),
        ('D_Settings', t('menu.settings'), '--settings'),
        ('E_About', t('menu.about'), '--about'),
        ('F_Quit', t('menu.quit'), '--quit'),
    ]
```

日历中的节日名和农历文本保留中文规范数据，在显示层通过 `t_data()` 翻译：

```python
def t_data(value):
    return t('data.' + value) if value else value

sub.setText(t_data(cd.day_label(d)))
```

- [ ] **步骤 5：运行覆盖与现有测试**

运行：`python -m unittest tests.test_pc_localization_coverage -v`

预期：PASS，输出 `OK`。

运行：`python -m unittest discover -s tests -v`

预期：现有测试全部 PASS。

- [ ] **步骤 6：提交**

```powershell
git add i18n_zh.py i18n_en.py app.py main.pyw transfer_ui.py video_ui.py boxes.py screenshot.py pinshot.py sysutil.py tests/test_pc_localization_coverage.py
git commit -m "feat: 完成 PC 全界面中英文案"
```

---

### 任务 3：PC 启动语言解析与设置页切换

**文件：**

- 修改：`main.pyw`
- 修改：`app.py`
- 修改：`sysutil.py`
- 测试：`tests/test_settings_language.py`

- [ ] **步骤 1：编写失败测试**

```python
# tests/test_settings_language.py
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QComboBox

from app import Config, SettingsDialog
from i18n import ZH


class _PanelStub:
    class Transfer:
        def service_enabled(self):
            return False

        def set_enabled(self, value):
            return value

        enabled_changed = type('Sig', (), {'connect': lambda *args: None})()

    class Video:
        def service_enabled(self):
            return False

        def set_enabled(self, value):
            return value

        enabled_changed = type('Sig', (), {'connect': lambda *args: None})()

    _theme = 'nocturne'
    transfer = Transfer()
    video = Video()

    def apply_theme(self, _key):
        pass

    def frameGeometry(self):
        return QApplication.primaryScreen().availableGeometry()


class SettingsLanguageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([])

    def test_language_combo_is_last_and_persists(self):
        with patch('app.sysutil.autostart_get', return_value=False):
            panel = _PanelStub()
            panel.cfg = Config(os.devnull)
            dlg = SettingsDialog(panel, lambda *a, **k: None, lambda: None)
        combo = dlg.findChild(QComboBox, 'languageCombo')
        self.assertIsNotNone(combo)
        self.assertEqual(combo.currentData(), ZH)
        with patch.object(dlg, '_confirm_language_restart', return_value=False):
            combo.setCurrentIndex(1)
        self.assertEqual(panel.cfg.data['language'], 'en-US')
        self.assertEqual(combo, dlg.findChildren(QComboBox)[-1])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m unittest tests.test_settings_language -v`

预期：FAIL，`languageCombo` 为 `None`。

- [ ] **步骤 3：实现机器语言读取和启动解析**

```python
# sysutil.py
def installed_language(all_users=None):
    roots = (all_users,) if all_users is not None else (False, True)
    for root_all_users in roots:
        value = uninstall_reg_get('Language', root_all_users)
        if value:
            return value
    return None
```

在 `main.pyw` 创建 `QApplication` 后、创建面板前：

```python
data_dir = sysutil.appdata_dir()
cfg = ui.Config(os.path.join(data_dir, 'config.json'))
language = i18n.resolve_language(
    os.environ.get('ZBOX_SHOT_LANG') if shot_dir else None,
    cfg.data.get('language'),
    sysutil.installed_language(),
    i18n.detect_system_language(),
)
i18n.set_language(language)
_tr = QTranslator(qapp)
if language == i18n.ZH and _tr.load(
        'qtbase_zh_CN', QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
    qapp.installTranslator(_tr)
```

- [ ] **步骤 4：实现设置页语言下拉框**

```python
from PySide6.QtWidgets import QComboBox, QMessageBox

sep_lang = QFrame()
sep_lang.setObjectName('setSep')
sep_lang.setFixedHeight(1)
form.addRow(sep_lang)

self.lang_combo = QComboBox()
self.lang_combo.setObjectName('languageCombo')
for code, name in i18n.LANGUAGE_NAMES.items():
    self.lang_combo.addItem(name, code)
self.lang_combo.setCurrentIndex(
    max(0, self.lang_combo.findData(cfg.data.get('language') or i18n.get_language())))
self.lang_combo.currentIndexChanged.connect(self._language_changed)
form.addRow(row_label(t('settings.language')), self.lang_combo)
```

```python
def _language_changed(self, _index):
    code = self.lang_combo.currentData()
    old = self._cfg.data.get('language') or i18n.get_language()
    if not code or code == old:
        return
    self._cfg.set('language', code)
    if self._confirm_language_restart():
        restart_application()

def _confirm_language_restart(self):
    box = QMessageBox(self)
    box.setWindowTitle(t('settings.restart_title'))
    box.setText(t('settings.restart_required'))
    restart = box.addButton(t('settings.restart_now'), QMessageBox.AcceptRole)
    box.addButton(t('common.later'), QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() is restart
```

```python
def restart_application():
    if getattr(sys, 'frozen', False):
        program, args = sys.executable, []
    else:
        program = sys.executable
        args = [os.path.abspath(sys.argv[0])]
    QProcess.startDetached(program, args)
    QApplication.instance().quit()
```

- [ ] **步骤 5：运行测试**

运行：`python -m unittest tests.test_settings_language tests.test_i18n -v`

预期：全部 PASS。

- [ ] **步骤 6：提交**

```powershell
git add main.pyw app.py sysutil.py tests/test_settings_language.py
git commit -m "feat: 增加 PC 语言设置与重启提示"
```

---

### 任务 4：PC 安装器语言、所有用户安装和旧 Zbox 清理

**文件：**

- 修改：`installer.py`
- 修改：`setup.pyw`
- 修改：`sysutil.py`
- 测试：`tests/test_installer_language.py`

- [ ] **步骤 1：编写失败测试**

```python
# tests/test_installer_language.py
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import installer


class InstallerLanguageTest(unittest.TestCase):
    def test_all_user_install_directory_is_program_files(self):
        with patch.dict(os.environ, {'ProgramFiles': r'C:\Program Files'}):
            self.assertEqual(installer.install_dir(True), r'C:\Program Files\zbox')

    def test_cleanup_removes_only_directories_containing_zbox_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / 'old-zbox'
            bad = Path(tmp) / 'not-zbox'
            good.mkdir()
            bad.mkdir()
            (good / 'zbox.exe').write_bytes(b'exe')
            (bad / 'keep.txt').write_text('keep', encoding='utf-8')
            with patch.object(installer, '_registered_zbox_dirs', return_value={str(good), str(bad)}), \
                    patch.object(installer, 'request_quit', return_value=True), \
                    patch.object(installer.sysutil, 'autostart_remove'), \
                    patch.object(installer.sysutil, 'context_menu_remove_zbox'), \
                    patch.object(installer.sysutil, 'uninstall_reg_remove_zbox'):
                installer.cleanup_existing_zbox()
            self.assertFalse(good.exists())
            self.assertTrue((bad / 'keep.txt').exists())


if __name__ == '__main__':
    unittest.main()
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m unittest tests.test_installer_language -v`

预期：FAIL，缺少 `cleanup_existing_zbox`、`_registered_zbox_dirs`。

- [ ] **步骤 3：实现 Zbox 专用注册表清理**

```python
# sysutil.py
def context_menu_remove_zbox():
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        _delete_shell_tree(root)


def uninstall_reg_remove_zbox():
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            winreg.DeleteKey(root, UNINSTALL_KEY)
        except OSError:
            pass
```

`uninstall_reg_install` 增加 `language` 参数并写入 `('Language', winreg.REG_SZ, language)`。

- [ ] **步骤 4：实现旧 Zbox 检测与清理**

```python
def _registered_zbox_dirs():
    candidates = {
        sysutil.uninstall_reg_get('InstallLocation', False),
        sysutil.uninstall_reg_get('InstallLocation', True),
        install_dir(False),
        install_dir(True),
    }
    return {os.path.normpath(p) for p in candidates if p}


def _is_zbox_program_dir(path):
    return os.path.isfile(os.path.join(path, APP_EXE))


def cleanup_existing_zbox():
    request_quit()
    time.sleep(1.0)
    errors = []
    for path in _registered_zbox_dirs():
        if not os.path.isdir(path) or not _is_zbox_program_dir(path):
            continue
        try:
            shutil.rmtree(path)
        except OSError as exc:
            errors.append('%s: %s' % (path, exc))
    if errors:
        raise RuntimeError('\n'.join(errors))
    sysutil.autostart_remove()
    sysutil.context_menu_remove_zbox()
    sysutil.uninstall_reg_remove_zbox()
```

`install()` 在复制 payload 前调用 `cleanup_existing_zbox()`，并记录当前语言：

```python
cleanup_existing_zbox()
report(4, t('installer.cleaning'))
...
sysutil.uninstall_reg_install(
    dst, all_users=all_users, size_kb=_dir_size(path_dir) // 1024,
    language=i18n.get_language(),
)
```

- [ ] **步骤 5：安装器增加语言选择并强制所有用户**

```python
self._language = QComboBox()
self._language.setObjectName('installLanguage')
for code, label in i18n.LANGUAGE_NAMES.items():
    self._language.addItem(label, code)
self._language.setCurrentIndex(self._language.findData(i18n.get_language()))
self._language.currentIndexChanged.connect(self._select_language)
lay.addWidget(self._section(t('installer.language')))
lay.addWidget(self._language)
```

```python
def _on_install(self):
    path = self._path.text().strip()
    if not is_admin():
        args = ['--install-elevated', '"%s"' % path, '--lang', i18n.get_language()]
        if not self._shortcut.isChecked():
            args.append('--no-shortcut')
        if not self._auto.isChecked():
            args.append('--no-autostart')
        if relaunch_elevated(args):
            self.accept()
        return
    self.start_install(path, True, self._shortcut.isChecked(), self._auto.isChecked())
```

删除安装范围 radio 与 `_on_scope_changed`，路径默认改为 `install_dir(True)`。`setup_main()` 的提权分支解析 `--lang`，先 `i18n.set_language(value)`，再构造向导。

- [ ] **步骤 6：迁移安装/卸载向导全部文案并运行测试**

所有标题、说明、按钮、错误、进度文本改为 `t()`。`setup.pyw` 根据系统检测结果设置初始语言，中文时安装 `qtbase_zh_CN`。

运行：`python -m unittest tests.test_installer_language tests.test_i18n -v`

预期：全部 PASS。

- [ ] **步骤 7：提交**

```powershell
git add installer.py setup.pyw sysutil.py tests/test_installer_language.py
git commit -m "feat: 安装器支持双语并清理旧 Zbox"
```

---

### 任务 5：PC 截图双语言验收与文档

**文件：**

- 修改：`main.pyw`
- 修改：`selfshot.py`
- 修改：`README.md`
- 修改：`README.zh-CN.md`
- 修改：`AGENTS.md`

- [ ] **步骤 1：加入截图语言测试钩子**

```python
shot_language = os.environ.get('ZBOX_SHOT_LANG') if shot_dir else None
language = i18n.resolve_language(
    shot_language,
    cfg.data.get('language'),
    sysutil.installed_language(),
    i18n.detect_system_language(),
)
```

自检模式下不把该值写回 `config.json`。

- [ ] **步骤 2：运行中文与英文截图**

```powershell
$env:ZBOX_SHOT='designs\verify-zh'
$env:ZBOX_SHOT_LANG='zh-CN'
python main.pyw
$env:ZBOX_SHOT='designs\verify-en'
$env:ZBOX_SHOT_LANG='en-US'
python main.pyw
Remove-Item Env:ZBOX_SHOT
Remove-Item Env:ZBOX_SHOT_LANG
```

预期：两套目录各生成当前 harness 的全部场景截图，无空白窗口、异常退出或主线程异常。

- [ ] **步骤 3：检查英文布局并修复截断**

逐张查看英文截图。按钮文字截断时优先调整固定宽度或使用现有 `_ElideLabel`，不得缩到不可读字号；英文文案不得溢出设置、传输、视频和安装向导卡片。

- [ ] **步骤 4：同步文档**

README 与 AGENTS 增加：

```markdown
- PC 与 Android 支持简体中文 / English；PC 设置页和 Android 设置 tab 可切换。
- PC 安装器默认检测系统语言，并固定按所有用户安装；安装前会清理旧 Zbox，保留个人数据。
- 截图自检可用 `ZBOX_SHOT_LANG=en-US` 生成英文场景。
```

- [ ] **步骤 5：运行完整 PC 验证**

```powershell
python -m unittest discover -s tests -v
python transfer_selftest.py
python -m py_compile i18n.py i18n_zh.py i18n_en.py app.py installer.py main.pyw
```

预期：单元测试全部 PASS；传输自检打印 `SELFTEST OK`；编译无输出。

- [ ] **步骤 6：提交**

```powershell
git add main.pyw selfshot.py README.md README.zh-CN.md AGENTS.md
git commit -m "test: 增加 PC 双语截图验收并同步文档"
```

---

### 任务 6：Android 语言核心与错误码

**文件：**

- 创建：`android/app/src/main/java/com/zbox/transfer/AppStrings.kt`
- 创建：`android/app/src/test/java/com/zbox/transfer/AppStringsTest.kt`
- 修改：`android/app/build.gradle.kts`
- 修改：`android/app/src/main/java/com/zbox/transfer/MainActivity.kt`
- 修改：`android/app/src/main/java/com/zbox/transfer/Protocol.kt`
- 修改：`android/app/src/main/java/com/zbox/transfer/Sender.kt`
- 修改：`android/app/src/main/java/com/zbox/transfer/Receiver.kt`

- [ ] **步骤 1：加入测试依赖并编写失败测试**

```kotlin
// android/app/build.gradle.kts
dependencies {
    testImplementation("junit:junit:4.13.2")
}
```

```kotlin
// android/app/src/test/java/com/zbox/transfer/AppStringsTest.kt
package com.zbox.transfer

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AppStringsTest {
    @Test fun normalizesSupportedLocales() {
        assertEquals(AppLanguage.ZH, AppLanguage.fromLocaleTag("zh_CN"))
        assertEquals(AppLanguage.EN, AppLanguage.fromLocaleTag("en-GB"))
        assertEquals(AppLanguage.EN, AppLanguage.fromLocaleTag("ja-JP"))
        assertNull(AppLanguage.fromLocaleTag(""))
    }

    @Test fun unresolvedLocaleFallsBackToChinese() {
        assertEquals(AppLanguage.ZH, AppLanguage.detect(""))
    }
}
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd android; .\gradlew.bat testDebugUnitTest --tests com.zbox.transfer.AppStringsTest`

预期：FAIL，`AppLanguage` 未定义。

- [ ] **步骤 3：实现语言状态与双语文案接口**

```kotlin
package com.zbox.transfer

import java.util.Locale

enum class AppLanguage(val code: String, val displayName: String) {
    ZH("zh-CN", "简体中文"),
    EN("en-US", "English");

    companion object {
        fun fromLocaleTag(tag: String): AppLanguage? {
            val normalized = tag.trim().lowercase().replace('_', '-')
            return when {
                normalized.startsWith("zh") -> ZH
                normalized.substringBefore('-').length in 2..3 -> EN
                else -> null
            }
        }

        fun detect(tag: String = Locale.getDefault().toLanguageTag()): AppLanguage =
            fromLocaleTag(tag) ?: ZH
    }
}

interface AppStrings {
    val transferTab: String
    val settingsTab: String
    val language: String
    val nearbyDevices: String
    fun status(status: TransferStatus): String
    fun error(error: AppError): String
}

object AppLocale {
    fun strings(language: AppLanguage): AppStrings =
        if (language == AppLanguage.EN) EnglishStrings else ChineseStrings
}

object AppStrings {
    val current: AppStrings
        get() = AppLocale.strings(Settings.language)
}
```

`Settings.init()` 读取 `prefs.getString("language", null)`，首次为空时调用 `AppLanguage.detect()` 并写回；`Settings.language` 使用 Compose `mutableStateOf` 暴露 setter。`AppStrings.current` 读取 `Settings.language`。

- [ ] **步骤 4：将持久化错误改为错误码**

```kotlin
enum class AppError {
    FILE_SIZE_UNAVAILABLE,
    CONNECT_FAILED,
    TIMEOUT,
    CONNECTION_INTERRUPTED,
    HOST_NOT_FOUND,
    PROTOCOL_MISMATCH,
    NO_SPACE,
    NO_PERMISSION,
    SOURCE_UNREADABLE,
    PEER_BUSY,
    NEGOTIATION_FAILED,
    PEER_REJECTED_FILE,
    SESSION_CONFLICT,
    INCOMPLETE_BODY,
    HASH_MISMATCH,
    UNKNOWN,
}
```

`TransferRecord.error` 改为 `AppError?`；`friendlyNetError()` 返回 `AppError`。UI 通过 `AppStrings.current.error(record.error!!)` 展示。协议响应中的底层英文错误不翻译，用户可见记录只保存错误码。

- [ ] **步骤 5：运行单元测试与编译**

```powershell
cd android
.\gradlew.bat testDebugUnitTest --tests com.zbox.transfer.AppStringsTest
.\gradlew.bat assembleDebug
```

预期：测试 PASS，APK 构建成功。

- [ ] **步骤 6：提交**

```powershell
git add android/app/build.gradle.kts android/app/src/main/java/com/zbox/transfer/AppStrings.kt android/app/src/main/java/com/zbox/transfer/MainActivity.kt android/app/src/main/java/com/zbox/transfer/Protocol.kt android/app/src/main/java/com/zbox/transfer/Sender.kt android/app/src/main/java/com/zbox/transfer/Receiver.kt android/app/src/test/java/com/zbox/transfer/AppStringsTest.kt
git commit -m "feat: 增加 Android 双语状态与错误码"
```

---

### 任务 7：Android 中文英文案迁移与底部导航

**文件：**

- 修改：`android/app/src/main/java/com/zbox/transfer/AppStrings.kt`
- 修改：`android/app/src/main/java/com/zbox/transfer/MainActivity.kt`
- 修改：`android/app/src/main/java/com/zbox/transfer/ui/DevicesScreen.kt`
- 修改：`android/app/src/main/java/com/zbox/transfer/ui/TransfersScreen.kt`
- 修改：`android/app/src/main/java/com/zbox/transfer/ui/ReceiveDialog.kt`
- 创建：`android/app/src/main/java/com/zbox/transfer/ui/SettingsScreen.kt`
- 修改：`android/app/src/main/AndroidManifest.xml`

- [ ] **步骤 1：实现设置页**

```kotlin
@Composable
fun SettingsScreen() {
    val strings = AppStrings.current
    val selected = Settings.language
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text(strings.settingsTitle, style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(16.dp))
        Text(strings.language, style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(8.dp))
        AppLanguage.entries.forEach { language ->
            Row(
                modifier = Modifier.fillMaxWidth().clickable { Settings.language = language }.padding(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                RadioButton(selected = selected == language, onClick = { Settings.language = language })
                Text(language.displayName)
            }
        }
    }
}
```

- [ ] **步骤 2：增加底部 NavigationBar**

```kotlin
var currentTab by rememberSaveable { mutableIntStateOf(0) }
val strings = AppStrings.current
Scaffold(
    bottomBar = {
        NavigationBar {
            NavigationBarItem(
                selected = currentTab == 0,
                onClick = { currentTab = 0 },
                icon = { Icon(Icons.Filled.SwapHoriz, null) },
                label = { Text(strings.transferTab) },
            )
            NavigationBarItem(
                selected = currentTab == 1,
                onClick = { currentTab = 1 },
                icon = { Icon(Icons.Filled.Settings, null) },
                label = { Text(strings.settingsTab) },
            )
        }
    },
) { padding ->
    Box(Modifier.padding(padding)) {
        if (currentTab == 0) HomeScreen(discovery) else SettingsScreen()
        ReceiveDialogHost()
    }
}
```

- [ ] **步骤 3：迁移 Android 全部可见文案**

`AppStrings` 提供首页、传输记录、弹窗、设备类型、保存路径、状态、错误和 contentDescription 对应字段与函数。调用点改为：

```kotlin
val s = AppStrings.current
Text(s.nearbyDevices)
Text(s.pendingFiles(shareUris.size))
Text(s.sendTo(device.info.alias))
Text(if (record.outgoing) s.sent else s.received)
Text(record.error?.let(s::error) ?: "")
```

枚举状态不再持有固定文案：

```kotlin
enum class TransferStatus { WAITING, TRANSFERRING, DONE, FAILED, REJECTED, CANCELED }

val statusText = AppStrings.current.status(record.status)
```

- [ ] **步骤 4：应用名改为品牌名**

```xml
<application
    android:label="Zbox"
    ...>
```

- [ ] **步骤 5：扫描遗漏并构建**

```powershell
rg -n 'Text\("[^"]*[\u4e00-\u9fff]|contentDescription\s*=\s*"[^"]*[\u4e00-\u9fff]' android/app/src/main/java -g '*.kt'
cd android
.\gradlew.bat testDebugUnitTest
.\gradlew.bat assembleDebug
```

预期：扫描无输出；JVM 测试 PASS；APK 构建成功。

- [ ] **步骤 6：手工验收**

分别把 SharedPreferences 清空并在中文、英文系统模拟器启动。检查：

- 首次语言符合系统语言规则。
- 底部“传输 / 设置”可切换。
- 设置页切语言后首页、记录、弹窗立即更新。
- 横竖屏和窄屏下英文 tab 与设置项不截断。

- [ ] **步骤 7：提交**

```powershell
git add android/app/src/main/java/com/zbox/transfer/AppStrings.kt android/app/src/main/java/com/zbox/transfer/MainActivity.kt android/app/src/main/java/com/zbox/transfer/ui/DevicesScreen.kt android/app/src/main/java/com/zbox/transfer/ui/TransfersScreen.kt android/app/src/main/java/com/zbox/transfer/ui/ReceiveDialog.kt android/app/src/main/java/com/zbox/transfer/ui/SettingsScreen.kt android/app/src/main/AndroidManifest.xml
git commit -m "feat: 完成 Android 双语界面与设置 tab"
```

---

### 任务 8：最终验证与文档

**文件：**

- 修改：`README.md`
- 修改：`README.zh-CN.md`
- 修改：`AGENTS.md`

- [ ] **步骤 1：同步最终用户与开发文档**

README 记录语言切换、PC 安装器行为和安卓设置 tab。AGENTS 更新：

- `i18n.py` / `i18n_zh.py` / `i18n_en.py` 的职责与新增文案规则。
- `installer.py` 强制所有用户、安装前清理 Zbox、保留个人数据。
- Android `AppStrings`、底部导航、错误码化要求。
- 新增测试和截图命令。

- [ ] **步骤 2：运行全部自动验证**

```powershell
python -m unittest discover -s tests -v
python transfer_selftest.py
python -m py_compile i18n.py i18n_zh.py i18n_en.py main.pyw app.py installer.py sysutil.py transfer_ui.py video_ui.py boxes.py
cd android
.\gradlew.bat testDebugUnitTest
.\gradlew.bat assembleDebug
```

预期：Python 测试全部 PASS；`SELFTEST OK`；`py_compile` 无输出；Gradle 测试与 APK 构建 `BUILD SUCCESSFUL`。

- [ ] **步骤 3：运行中文和英文截图自检**

```powershell
$env:ZBOX_SHOT='designs\verify-final-zh'
$env:ZBOX_SHOT_LANG='zh-CN'
python main.pyw
$env:ZBOX_SHOT='designs\verify-final-en'
$env:ZBOX_SHOT_LANG='en-US'
python main.pyw
Remove-Item Env:ZBOX_SHOT
Remove-Item Env:ZBOX_SHOT_LANG
```

预期：两套截图全部生成；抽查面板、设置、传输、视频、弹窗、格子和安装/卸载向导无漏翻、重叠或截断。

- [ ] **步骤 4：检查工作区**

```powershell
git diff --check
git status --short
```

预期：`git diff --check` 无输出；除用户原有改动外，只出现本计划涉及文件。

- [ ] **步骤 5：提交文档**

```powershell
git add README.md README.zh-CN.md AGENTS.md
git commit -m "docs: 同步中英双语功能说明"
```
