# -*- coding: utf-8 -*-
"""Zbox 崩溃诊断：纯标准库报告核心，不负责 Qt 界面。"""
import ctypes
import json
import msvcrt
import os
import platform
import re
import subprocess
import sys
import traceback
from ctypes import wintypes
from datetime import datetime
from urllib.parse import urlencode

from version import APP_VERSION, GITHUB_URL

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_native_callback = None
_previous_filter = None


class EXCEPTION_RECORD(ctypes.Structure):
    pass


EXCEPTION_RECORD._fields_ = [
    ('ExceptionCode', wintypes.DWORD),
    ('ExceptionFlags', wintypes.DWORD),
    ('ExceptionRecord', ctypes.POINTER(EXCEPTION_RECORD)),
    ('ExceptionAddress', ctypes.c_void_p),
    ('NumberParameters', wintypes.DWORD),
    ('ExceptionInformation', ctypes.c_size_t * 15),
]


class EXCEPTION_POINTERS(ctypes.Structure):
    _fields_ = [
        ('ExceptionRecord', ctypes.POINTER(EXCEPTION_RECORD)),
        ('ContextRecord', ctypes.c_void_p),
    ]


class MINIDUMP_EXCEPTION_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('ThreadId', wintypes.DWORD),
        ('ExceptionPointers', ctypes.POINTER(EXCEPTION_POINTERS)),
        ('ClientPointers', wintypes.BOOL),
    ]

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
    """用 DbgHelp 写 MiniDumpNormal；原生异常时带上系统给的异常上下文。"""
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    process = kernel32.GetCurrentProcess()
    pid = kernel32.GetCurrentProcessId()
    with open(path, 'wb') as output:
        info = None
        info_ref = None
        if exception_pointers is not None:
            pointers = ctypes.cast(exception_pointers, ctypes.POINTER(EXCEPTION_POINTERS))
            info = MINIDUMP_EXCEPTION_INFORMATION(
                ThreadId=kernel32.GetCurrentThreadId(),
                ExceptionPointers=pointers, ClientPointers=True)
            info_ref = ctypes.byref(info)
        dump = ctypes.windll.dbghelp.MiniDumpWriteDump
        dump.restype = wintypes.BOOL
        dump.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.HANDLE,
                         wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        ctypes.set_last_error(0)
        ok = dump(process, pid, wintypes.HANDLE(msvcrt.get_osfhandle(output.fileno())),
                  0x00000000, info_ref, None, None)
        if not ok:
            error = ctypes.WinError(ctypes.get_last_error())
    if not ok:
        try:
            os.remove(path)
        except OSError:
            pass
        raise error


def report_python_exception(exc_type, exc_value, tb, data_dir, launch=True,
                            native_log='', native_offset=0):
    """先落原始现场和转储，再视需要启动独立报告进程。"""
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



_FILTER_CALLBACK = ctypes.WINFUNCTYPE(wintypes.LONG, ctypes.c_void_p)


def _set_filter(callback):
    setter = ctypes.windll.kernel32.SetUnhandledExceptionFilter
    setter.restype = ctypes.c_void_p
    setter.argtypes = [ctypes.c_void_p]
    return setter(callback)


def install_native_handler(data_dir, native_log, native_offset):
    """链到 faulthandler 的原生过滤器前，随后保存转储并启动独立报告进程。"""
    global _native_callback, _previous_filter

    def on_native_exception(exception_pointers):
        if _previous_filter is not None:
            try:
                _previous_filter(exception_pointers)
            except Exception:
                pass
        try:
            native_log.flush()
        except Exception:
            pass
        try:
            report_dir = create_report_dir(data_dir)
            info = {'code': '', 'address': ''}
            try:
                record = ctypes.cast(exception_pointers, ctypes.POINTER(
                    EXCEPTION_POINTERS)).contents.ExceptionRecord.contents
                info = {'code': '0x%08X' % record.ExceptionCode,
                        'address': '0x%X' % (record.ExceptionAddress or 0)}
            except Exception:
                pass
            with open(os.path.join(report_dir, 'native.json'), 'w', encoding='utf-8') as f:
                json.dump(info, f)
            dump_error = ''
            dump_path = os.path.join(report_dir, 'zbox-crash.dmp')
            try:
                write_minidump(dump_path, exception_pointers)
            except Exception as exc:
                # DbgHelp 在部分 Python 原生回调里无法接受异常上下文；保留失败原因，
                # 立即在同一现场重试无上下文 MiniDumpNormal，避免只留下 0 字节文件。
                dump_error = str(exc)
                try:
                    write_minidump(dump_path)
                except Exception as fallback_exc:
                    dump_error += '\nFallback: ' + str(fallback_exc)
            with open(os.path.join(report_dir, 'dump_error.txt'), 'w', encoding='utf-8') as f:
                f.write(dump_error)
            try:
                launch_reporter(report_dir, native_log.name, native_offset)
            except Exception:
                pass
        except Exception:
            pass
        return 1  # EXCEPTION_EXECUTE_HANDLER：不再返回已损坏的事件循环

    _native_callback = _FILTER_CALLBACK(on_native_exception)
    previous = _set_filter(_native_callback)
    _previous_filter = _FILTER_CALLBACK(previous) if previous else None
