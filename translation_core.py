# -*- coding: utf-8 -*-
"""截图翻译的纯逻辑核心：OCR 协议解析、语言判断、段落聚类、豆包译文解析、排版参数。

对照 transfer.py 的分层：纯标准库零 Qt，所有函数可脱离界面单测。
坐标一律用逻辑像素（界面坐标），OCR 位图像素经 scale 换算。
"""

import json
import re

OCR_PROTOCOL_VERSION = 1


class OcrProtocolError(ValueError):
    """OCR helper 输出不符合协议（版本不符 / 字段缺失 / 非 JSON）。"""


class TranslationParseError(ValueError):
    """豆包回复无法严格解析成编号译文（缺失 / 多余 / 非 JSON）。"""


class OcrRegion(object):
    """一条 OCR 识别行：文本 + 四角点 + 轴对齐外接框（逻辑像素）。"""

    __slots__ = ('text', 'confidence', 'quad', 'bbox')

    def __init__(self, text, confidence, quad, bbox):
        self.text = text
        self.confidence = confidence
        self.quad = quad      # ((x,y), x4)，浮点
        self.bbox = bbox      # (x, y, w, h)，整型

    def __repr__(self):
        return 'OcrRegion(%r, bbox=%r)' % (self.text, self.bbox)


class Paragraph(object):
    """聚类出的一段文字：外接矩形 + 按阅读顺序排列的 OCR 行。"""

    __slots__ = ('rect', 'lines')

    def __init__(self, rect, lines):
        self.rect = rect      # (x, y, w, h)
        self.lines = lines    # [OcrRegion]

    @property
    def text(self):
        return '\n'.join(l.text for l in self.lines)


# ---------------- OCR 协议 ----------------

def parse_ocr_payload(raw, scale=1.0):
    """解析 ocr_helper --stdio 的单行 JSON 输出；scale 把位图像素换算成逻辑像素。"""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('utf-8')
        except UnicodeDecodeError as e:
            raise OcrProtocolError('ocr output is not utf-8: %s' % e)
    try:
        payload = json.loads(raw.strip())
    except (ValueError, AttributeError) as e:
        raise OcrProtocolError('ocr output is not json: %s' % e)
    if not isinstance(payload, dict) or payload.get('version') != OCR_PROTOCOL_VERSION:
        raise OcrProtocolError('unsupported ocr protocol version: %r'
                               % (payload.get('version') if isinstance(payload, dict) else None))
    items = payload.get('regions')
    if not isinstance(items, list):
        raise OcrProtocolError('regions must be a list')
    regions = []
    for it in items:
        try:
            text = it['text']
            conf = float(it['confidence'])
            quad = [(float(p[0]) * scale, float(p[1]) * scale) for p in it['quad']]
            x, y, w, h = it['bbox']
        except (KeyError, TypeError, ValueError, IndexError) as e:
            raise OcrProtocolError('malformed region: %s' % e)
        if not isinstance(text, str) or len(quad) != 4:
            raise OcrProtocolError('malformed region text/quad')
        regions.append(OcrRegion(text, conf, quad,
                                 (int(round(x * scale)), int(round(y * scale)),
                                  int(round(w * scale)), int(round(h * scale)))))
    return regions


# ---------------- 语言判断 ----------------

_CJK = re.compile(r'[一-鿿　-〿＀-￯가-힯]')
_LATIN = re.compile(r'[A-Za-z]')


def detect_lang(text):
    """按字符占比判断主导语言：中文 / 英文 / 无法判断（数字、标点、空）。"""
    cjk = len(_CJK.findall(text))
    latin = len(_LATIN.findall(text))
    if cjk == 0 and latin == 0:
        return 'other'
    return 'zh' if cjk >= latin else 'en'


def target_language(ui_lang):
    """界面语言归一成翻译目标语言。"""
    return 'zh' if str(ui_lang).startswith('zh') else 'en'


def should_translate(source_lang, target_lang):
    """源文已是目标语言（或无法判断）时跳过翻译。"""
    if source_lang not in ('zh', 'en'):
        return False
    return source_lang != target_lang


# ---------------- 段落聚类 ----------------

def reading_order(regions):
    """阅读顺序：按行带（垂直重叠归并）从上到下，行内从左到右。"""
    bands = []
    for r in sorted(regions, key=lambda r: (r.bbox[1], r.bbox[0])):
        x, y, w, h = r.bbox
        for band in bands:
            by, bh = band[0]
            overlap = min(y + h, by + bh) - max(y, by)
            if overlap > 0.5 * min(h, bh):
                band[1].append(r)
                band[0] = (min(by, y), max(by + bh, y + h) - min(by, y))
                break
        else:
            bands.append([(y, h), [r]])
    out = []
    for (_y, _h), band_regions in sorted(bands, key=lambda b: b[0][0]):
        out.extend(sorted(band_regions, key=lambda r: r.bbox[0]))
    return out


def cluster_paragraphs(regions):
    """把 OCR 行按垂直间距聚成段落：行距 < 0.8 倍行高视为同段。"""
    ordered = reading_order(regions)
    paras = []
    for r in ordered:
        x, y, w, h = r.bbox
        if paras:
            px, py, pw, ph = paras[-1].rect
            gap = y - (py + ph)
            if gap < 0.8 * max(h, ph / len(paras[-1].lines)):
                paras[-1].lines.append(r)
                nx, ny = min(px, x), min(py, y)
                paras[-1].rect = (nx, ny,
                                  max(px + pw, x + w) - nx, max(py + ph, y + h) - ny)
                continue
        paras.append(Paragraph((x, y, w, h), [r]))
    return paras


# ---------------- 豆包提示词与回复解析 ----------------

_TARGET_NAMES = {'zh': '简体中文', 'en': 'English'}


def build_prompt(texts, target_lang):
    """编号 JSON 请求：要求豆包仅返回 JSON 数组，编号与输入一一对应。"""
    items = [{'id': i + 1, 'text': t} for i, t in enumerate(texts)]
    return (
        '把下面 JSON 数组里每条的 "text" 翻译成{name}。'
        '只返回 JSON 数组，不要任何解释、不要用代码块以外的文字；'
        '每条保留原 "id"，翻译结果放 "text"，不许增删条目、不许合并。\n'
        '{payload}'
    ).format(name=_TARGET_NAMES.get(target_lang, target_lang),
             payload=json.dumps(items, ensure_ascii=False))


def parse_translations(reply, expected_count):
    """严格解析豆包回复：编号必须恰好 1..expected_count，缺失/多余/空译文都算失败。"""
    if not isinstance(reply, str):
        raise TranslationParseError('reply is not text')
    text = reply.strip()
    fence = re.search(r'```(?:json)?\s*(.*?)```', text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except ValueError as e:
        raise TranslationParseError('reply is not json: %s' % e)
    if isinstance(data, dict):
        data = data.get('translations')
    if not isinstance(data, list):
        raise TranslationParseError('reply is not a json array')
    by_id = {}
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get('id'), int):
            raise TranslationParseError('malformed translation item')
        val = item.get('text')
        if not isinstance(val, str) or not val.strip():
            raise TranslationParseError('empty translation for id %r' % item.get('id'))
        by_id[item['id']] = val
    expected = set(range(1, expected_count + 1))
    if set(by_id) != expected:
        raise TranslationParseError('id set mismatch: got %r, expected %r'
                                    % (sorted(by_id), sorted(expected)))
    return [by_id[i] for i in range(1, expected_count + 1)]


# ---------------- 排版与马赛克 ----------------

def fit_text(text, width, height, base, minimum, measure):
    """从 base 往 minimum 逐档缩字号直到 measure 报告放得下；返回 (字号, 行数)。
    measure(text, size, width) -> (行数, 总高)，由调用方注入（Qt 字体度量或测试桩）。"""
    size = base
    while size > minimum:
        lines, total = measure(text, size, width)
        if total <= height:
            return size, lines
        size -= 1
    lines, _total = measure(text, minimum, width)
    return minimum, lines


def mosaic_rect(bbox, expand, bounds):
    """文字框外扩 expand 像素（防残留笔画），裁剪到图像 bounds 内。"""
    x, y, w, h = bbox
    bx, by, bw, bh = bounds
    nx = max(bx, x - expand)
    ny = max(by, y - expand)
    nx2 = min(bx + bw, x + w + expand)
    ny2 = min(by + bh, y + h + expand)
    return (nx, ny, max(0, nx2 - nx), max(0, ny2 - ny))