# -*- coding: utf-8 -*-
"""PC 界面本地化覆盖：UI 文件里不得残留非 docstring 中文字面量。

用 AST 收集字符串常量（不用正则扫源码），模块/类/函数 docstring 不算文案。
白名单只放「数据不是文案」的少量值，并在下方注明理由。
"""
import ast
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UI_FILES = ('app.py', 'main.pyw', 'transfer_ui.py', 'video_ui.py',
            'boxes.py', 'screenshot.py', 'pinshot.py', 'sysutil.py', 'installer.py')

# 数据不是文案：解析字符与底层异常匹配关键词。
ALLOWED = {
    # parse_time_text / parse_noon_range 要认中文冒号、全角减号与波浪号。
    'app.py': {'：', '－', '～'},
    # _NET_ERROR_HINTS 拿底层异常原文做关键词匹配，不是界面文案。
    'transfer_ui.py': {'对方未及时确认', '积极拒绝', '强迫关闭', '超时', '不在线', '不可达'},
    # 旧版桌面快捷方式的文件名（.lnk 基名），不是界面文案；卸载时要按原名删掉。
    'installer.py': {'Zbox桌面格子'},
}

# 用户可见 API：直接传字符串字面量会绕过 i18n 词典。
VISIBLE_METHODS = {
    'setText': (0,),
    'setToolTip': (0,),
    'setPlaceholderText': (0,),
    'setWindowTitle': (0,),
    'getSaveFileName': (1, 3),
    'getOpenFileName': (1, 3),
    'getOpenFileNames': (1, 3),
    'getExistingDirectory': (1,),
    'critical': (1, 2),
    'information': (1, 2),
    'warning': (1, 2),
    'question': (1, 2),
}
VISIBLE_CTORS = {'QLabel', 'QPushButton', 'QToolButton', 'QCheckBox',
                 'QRadioButton', 'QGroupBox', 'QAction', 'QMessageBox'}


def _docstring_nodes(tree):
    """返回所有 docstring 常量节点的 id（模块/类/同步与异步函数）。"""
    nodes = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            nodes.add(id(first.value))
    return nodes


def _has_chinese(text):
    """汉字、CJK 标点、扩展 A 区或全角字符（全角标点同样需要迁移）。"""
    return any('　' <= ch <= '〿' or '㐀' <= ch <= '䶿'
               or '一' <= ch <= '鿿' or '＀' <= ch <= '￯'
               for ch in text)


def _has_latin_word(text):
    """含拉丁字母才可能是英文文案；纯数字、符号和格式串不算。"""
    return re.search(r'[A-Za-z]', text) is not None


def _call_name(node):
    """返回调用目标末级名称，兼容 QLabel(...) 与 widget.setText(...)。"""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ''


def _visible_text_arguments(node):
    """产出用户可见调用中的位置参数，供硬编码检查。"""
    name = _call_name(node)
    indexes = VISIBLE_METHODS.get(name)
    if indexes is None:
        indexes = (0,) if name in VISIBLE_CTORS else ()
    for index in indexes:
        if index < len(node.args):
            yield node.args[index]


class PcLocalizationCoverageTest(unittest.TestCase):
    def test_ui_files_have_no_chinese_literals(self):
        offenders = []
        for rel in UI_FILES:
            path = os.path.join(ROOT, rel)
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=rel)
            docstrings = _docstring_nodes(tree)
            allowed = ALLOWED.get(rel, set())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if id(node) in docstrings:
                    continue
                if not _has_chinese(node.value):
                    continue
                if node.value in allowed:
                    continue
                offenders.append('%s:%d: %r' % (rel, node.lineno, node.value))
        self.assertEqual(
            offenders, [],
            '发现未本地化的中文字符串（应改用 i18n.t）：\n' + '\n'.join(offenders))

    def test_user_visible_literals_use_i18n_in_both_languages(self):
        """用户可见 API 的英文原句同样必须走 i18n，不能只依赖中文扫描。"""
        offenders = []
        for rel in UI_FILES:
            path = os.path.join(ROOT, rel)
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=rel)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for arg in _visible_text_arguments(node):
                    if not (isinstance(arg, ast.Constant)
                            and isinstance(arg.value, str)):
                        continue
                    text = arg.value.strip()
                    if text and (_has_chinese(text) or _has_latin_word(text)):
                        offenders.append(
                            '%s:%d: %r' % (rel, arg.lineno, arg.value))
        self.assertEqual(
            offenders, [],
            '发现直接传给用户可见控件的文案（应改用 i18n.t）：\n'
            + '\n'.join(offenders))


if __name__ == '__main__':
    unittest.main()
