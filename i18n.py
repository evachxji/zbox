# -*- coding: utf-8 -*-
"""PC 语言核心：语言归一、系统语言探测与词典翻译，零 Qt 依赖。

安装器与测试可以直接 import 本模块；词典放在 i18n_zh / i18n_en，
两边的键必须保持一致。
"""
import ctypes
import locale

ZH = 'zh-CN'
EN = 'en-US'
DEFAULT_LANGUAGE = ZH
LANGUAGES = (ZH, EN)
LANGUAGE_NAMES = {ZH: '简体中文', EN: 'English'}

_language = DEFAULT_LANGUAGE


def normalize_language(value):
    """把语言标签归一为受支持的语言代码，无法识别时返回 None。"""
    raw = str(value or '').strip().lower().replace('_', '-')
    if raw.startswith('zh'):
        return ZH
    if raw and len(raw.split('-', 1)[0]) in (2, 3):
        return EN
    return None


def _windows_ui_language():
    """读取 Windows 用户界面语言，失败时回落到 locale 设置。"""
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return locale.windows_locale.get(lang_id, '')
    except Exception:
        try:
            return locale.getlocale()[0] or ''
        except Exception:
            return ''


def detect_system_language():
    """探测系统语言，无法识别时使用默认语言。"""
    return normalize_language(_windows_ui_language()) or DEFAULT_LANGUAGE


def resolve_language(*candidates):
    """按顺序取第一个可识别的语言候选，全都无效时返回默认语言。"""
    for value in candidates:
        normalized = normalize_language(value)
        if normalized:
            return normalized
    return DEFAULT_LANGUAGE


def set_language(value):
    """设置当前语言并返回归一后的代码。"""
    global _language
    _language = normalize_language(value) or DEFAULT_LANGUAGE
    return _language


def get_language():
    """返回当前语言代码。"""
    return _language


def t(key, **kwargs):
    """按当前语言取词典文案；缺失时回落到中文，再缺失则返回键名。"""
    from i18n_zh import CATALOG as ZH_CATALOG
    from i18n_en import CATALOG as EN_CATALOG
    catalog = EN_CATALOG if _language == EN else ZH_CATALOG
    text = catalog.get(key) or ZH_CATALOG.get(key) or key
    return text.format(**kwargs) if kwargs else text
