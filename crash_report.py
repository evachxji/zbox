# -*- coding: utf-8 -*-
"""Zbox 崩溃诊断：纯标准库报告核心，不负责 Qt 界面。"""
import os
import platform
import re
import sys
from datetime import datetime
from urllib.parse import urlencode

from version import APP_VERSION, GITHUB_URL


def sanitize_text(text, home=None, username=None):
    """脱敏用户主目录与用户名；系统信息本身不读取这些身份字段。"""
    home = home if home is not None else os.path.expanduser('~')
    username = username if username is not None else os.environ.get('USERNAME', '')
    if home:
        text = re.sub(re.escape(home), '<UserProfile>', text, flags=re.IGNORECASE)
    if username:
        text = re.sub(r'(?<![\w])' + re.escape(username) + r'(?![\w])',
                      '<User>', text, flags=re.IGNORECASE)
    return text


def create_report_dir(base_dir, now=None, pid=None):
    """分配一次崩溃独享的目录，同名时追加序号，绝不覆盖历史现场。"""
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
    """只收集排查兼容性所需的基础字段，不含机器或用户身份信息。"""
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
    """把各类现场整理成一份 UTF-8 文本报告。"""
    sections = ['Zbox crash report', 'Time: ' + datetime.now().astimezone().isoformat()]
    sections += ['%s: %s' % item for item in system_info().items()]
    sections += ['PySide6: ' + pyside_version, 'Qt: ' + qt_version]
    sections += [
        'Python exception:', sanitize_text(python_trace or '(none)'),
        'Native exception:', sanitize_text(native_error or '(none)'),
        'Native stack:', sanitize_text(native_trace or '(none)'),
        'Dump error:', sanitize_text(dump_error or '(none)'),
    ]
    path = os.path.join(report_dir, 'zbox-crash.log')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(sections) + '\n')
    return path


def build_issue_url(summary, log_ready, dump_ready):
    """只预填元数据和附件清单，不把日志正文放进 URL。"""
    title = '[Crash] Zbox %s %s' % (APP_VERSION, sanitize_text(summary)[:100])
    body = ('## Reproduction steps\n\n1. \n\n## Environment\n\n'
            'Zbox: %s\n\n## Attachments\n\n- [ ] zbox-crash.log (%s)\n'
            '- [ ] zbox-crash.dmp (%s; may contain process memory)\n' %
            (APP_VERSION, 'available' if log_ready else 'not generated',
             'available' if dump_ready else 'not generated'))
    return GITHUB_URL + '/issues/new?' + urlencode({'title': title, 'body': body})
