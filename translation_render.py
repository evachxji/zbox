# -*- coding: utf-8 -*-
"""翻译渲染层：把「马赛克原文 + 译文」画成与选区同尺寸的透明图层。

图层独立存在（不落进 base），截图遮罩与导出图各自把它画在底图之上、
用户标注之下；再次点击翻译按钮切换显隐，复制/保存/钉图时压平。
坐标一律逻辑像素；马赛克采样按 base 自身的 dpr 换算到像素空间。
"""

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter

import translation_core as tc

MOSAIC_BLOCK = 8     # 马赛克块边长（逻辑像素）
MOSAIC_EXPAND = 3    # 文字框外扩，防残留笔画
FONT_MIN = 8
FONT_MAX = 32


def _wrap_lines(text, fm, width):
    """按字符贪心换行（CJK 无空格也能断），与 fit_text 度量共用。"""
    out = []
    for para in text.split('\n'):
        line = ''
        for ch in para:
            if line and fm.horizontalAdvance(line + ch) > width:
                out.append(line)
                line = ch
            else:
                line += ch
        out.append(line)
    return out or ['']


def _make_measure(font_family):
    def measure(text, size, width):
        f = QFont(font_family)
        f.setPixelSize(size)
        fm = QFontMetricsF(f)
        lines = _wrap_lines(text, fm, width)
        return len(lines), fm.height() * len(lines)
    return measure


def _luminance(img, px_rect):
    """区域平均亮度（0..1），采样步长 4px 够用。

    2026-10 性能审计 P1-12：原先逐像素调 img.pixel() 再构造 QColor 取分量 ——
    纯 Python 层的双重循环 + 对象构造（单段落 1 万次、20 段落 20 万次），
    是翻译出图时 GUI 线程冻结 0.2~1s 的主因之一。改成一次性把像素读成字节
    再按步长取（ARGB32 下每像素 4 字节，B=偏移0 G=1 R=2）。
    """
    x, y, w, h = px_rect
    if w <= 0 or h <= 0:
        return 1.0
    im = img.convertToFormat(QImage.Format_ARGB32) if img.format() != QImage.Format_ARGB32 else img
    iw, ih = im.width(), im.height()
    stride = im.bytesPerLine()
    buf = im.constBits()
    total = count = 0
    for yy in range(y, y + h, 4):
        if yy >= ih:
            break
        row = yy * stride
        for xx in range(x, x + w, 4):
            if xx >= iw:
                break
            off = row + xx * 4
            total += 0.299 * buf[off + 2] + 0.587 * buf[off + 1] + 0.114 * buf[off]
            count += 1
    return (total / count / 255.0) if count else 1.0


def _pixelate(base, rect_l, base_dpr, block=MOSAIC_BLOCK):
    """取逻辑矩形对应的像素区域，缩小再放大成块状马赛克。"""
    x, y, w, h = rect_l
    px = QRect(int(x * base_dpr), int(y * base_dpr),
               max(1, int(w * base_dpr)), max(1, int(h * base_dpr)))
    px = px.intersected(QRect(0, 0, base.width(), base.height()))
    if px.isEmpty():
        return None
    sub = base.copy(px)
    bw = max(1, int(px.width() / (block * base_dpr)))
    bh = max(1, int(px.height() / (block * base_dpr)))
    small = sub.scaled(bw, bh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small.scaled(px.width(), px.height(),
                        Qt.IgnoreAspectRatio, Qt.FastTransformation)


def fit_font(paragraph, text, font_family):
    """段落字号：基准取行高 0.75 倍夹在 [10, 32]，再按译文长度收缩。"""
    line_h = paragraph.rect[3] / max(1, len(paragraph.lines))
    base = max(10, min(FONT_MAX, int(line_h * 0.75)))
    size, _lines = tc.fit_text(text, paragraph.rect[2], max(paragraph.rect[3], line_h * 3),
                               base, FONT_MIN, _make_measure(font_family))
    return size


def build_layer(base, paragraphs, translations, dpr=1.0, font_family='Microsoft YaHei'):
    """生成翻译图层：逻辑尺寸同 base，像素尺寸 *dpr，透明底。
    paragraphs 的坐标是 base 逻辑空间内的偏移。"""
    base_dpr = base.devicePixelRatio() or 1.0
    logical_w = base.width() / base_dpr
    logical_h = base.height() / base_dpr
    layer = QImage(max(1, int(logical_w * dpr + 0.5)),
                   max(1, int(logical_h * dpr + 0.5)), QImage.Format_ARGB32)
    layer.setDevicePixelRatio(dpr)
    layer.fill(Qt.transparent)
    p = QPainter(layer)
    p.setRenderHint(QPainter.Antialiasing)
    bounds = (0, 0, int(logical_w), int(logical_h))
    for para, text in zip(paragraphs, translations):
        for line in para.lines:
            rect = tc.mosaic_rect(line.bbox, MOSAIC_EXPAND, bounds)
            mosaic = _pixelate(base, rect, base_dpr)
            if mosaic is not None:
                p.drawImage(QRectF(*rect), mosaic, QRectF(mosaic.rect()))
        x, y, w, h = para.rect
        lum = _luminance(base, (int(x * base_dpr), int(y * base_dpr),
                                max(1, int(w * base_dpr)), max(1, int(h * base_dpr))))
        color = QColor('#1a1610') if lum > 0.55 else QColor('#ffffff')
        f = QFont(font_family)
        f.setPixelSize(fit_font(para, text, font_family))
        p.setFont(f)
        p.setPen(color)
        p.drawText(QRectF(x, y, w, max(h, h * 3)),
                   Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, text)
    p.end()
    return layer


def render(base, paragraphs, translations, translated=True,
           font_family='Microsoft YaHei'):
    """压平导出：translated=True 把图层画到 base 副本上；False 原样返回副本。"""
    out = base.copy()
    if not translated or not paragraphs:
        return out
    layer = build_layer(base, paragraphs, translations,
                        dpr=base.devicePixelRatio() or 1.0, font_family=font_family)
    p = QPainter(out)
    p.drawImage(0, 0, layer)
    p.end()
    return out