# -*- coding: utf-8 -*-
"""PC 界面本地化覆盖：UI 文件里不得残留非 docstring 中文字面量。

用 AST 收集字符串常量（不用正则扫源码），模块/类/函数 docstring 不算文案。
白名单只放「数据不是文案」的少量值，并在下方注明理由。
"""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UI_FILES = ('app.py', 'main.pyw', 'transfer_ui.py', 'video_ui.py',
            'boxes.py', 'screenshot.py', 'pinshot.py', 'sysutil.py')

# 数据不是文案：解析字符与底层异常匹配关键词。
ALLOWED = {
    # parse_time_text / parse_noon_range 要认中文冒号、全角减号与波浪号。
    'app.py': {'：', '－', '～'},
    # _NET_ERROR_HINTS 拿底层异常原文做关键词匹配，不是界面文案。
    'transfer_ui.py': {'对方未及时确认', '积极拒绝', '强迫关闭', '超时', '不在线', '不可达'},
}


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


if __name__ == '__main__':
    unittest.main()
