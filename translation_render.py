# -*- coding: utf-8 -*-
"""翻译渲染层：把「高斯模糊原文 + 译文」画成与选区同尺寸的透明图层。

图层独立存在（不落进 base），截图遮罩与导出图各自把它画在底图之上、
用户标注之下；再次点击翻译按钮切换显隐，复制/保存/钉图时压平。
坐标一律逻辑像素；模糊采样按 base 自身的 dpr 换算到像素空间。
"""

import math

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter

import translation_core as tc

BLUR_RADIUS = 8      # 高斯模糊半径（逻辑像素）
BLUR_EXPAND = 3      # 文字框外扩，防残留笔画
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
        # 越界坐标钳到边界（与原实现 min(xx, w-1) 一致：马赛克外扩的行框可能略微出界）
        row = min(yy, ih - 1) * stride
        for xx in range(x, x + w, 4):
            off = row + min(xx, iw - 1) * 4
            total += 0.299 * buf[off + 2] + 0.587 * buf[off + 1] + 0.114 * buf[off]
            count += 1
    return (total / count / 255.0) if count else 1.0


def _gaussian_kernel(radius):
    """生成整数化的对称高斯核；整数卷积避免引入额外图像依赖。"""
    sigma = max(0.1, radius / 2.0)
    raw = []
    for i in range(-radius, radius + 1):
        raw.append(math.exp(-(i * i) / (2.0 * sigma * sigma)))
    scale = 1024.0 / sum(raw)
    weights = [max(1, int(round(v * scale))) for v in raw]
    weights[radius] += 1024 - sum(weights)
    return tuple(weights)


def _gaussian_blur(base, rect_l, base_dpr, radius=BLUR_RADIUS):
    """只对逻辑矩形对应区域做可分离高斯模糊，区域外不采样、不回写。"""
    x, y, w, h = rect_l
    px = QRect(int(x * base_dpr), int(y * base_dpr),
               max(1, int(w * base_dpr)), max(1, int(h * base_dpr)))
    px = px.intersected(QRect(0, 0, base.width(), base.height()))
    if px.isEmpty():
        return None
    sub = base.copy(px)
    if sub.format() != QImage.Format_ARGB32:
        sub = sub.convertToFormat(QImage.Format_ARGB32)
    width, height = sub.width(), sub.height()
    radius = max(1, int(round(radius * base_dpr)))
    weights = _gaussian_kernel(radius)
    offsets = range(-radius, radius + 1)
    xsamples = [[(min(width - 1, max(0, xx + off)) * 4, weight)
                 for off, weight in zip(offsets, weights)] for xx in range(width)]
    ysamples = [[(min(height - 1, max(0, yy + off)) * width * 4, weight)
                 for off, weight in zip(offsets, weights)] for yy in range(height)]

    # 横向：源图可能带行对齐 stride；中间结果改为紧凑 width*4 行距。
    src = sub.constBits()
    stride = sub.bytesPerLine()
    tmp = bytearray(width * height * 4)
    for yy in range(height):
        row = yy * stride
        for xx, samples in enumerate(xsamples):
            b = g = r = a = 0
            for off, weight in samples:
                i = row + off
                b += src[i] * weight
                g += src[i + 1] * weight
                r += src[i + 2] * weight
                a += src[i + 3] * weight
            di = (yy * width + xx) * 4
            tmp[di] = (b + 512) >> 10
            tmp[di + 1] = (g + 512) >> 10
            tmp[di + 2] = (r + 512) >> 10
            tmp[di + 3] = (a + 512) >> 10

    # 纵向：与横向共用同一高斯核，边缘像素钳位，不借入区域外内容。
    out = bytearray(len(tmp))
    for yy, samples in enumerate(ysamples):
        row = yy * width * 4
        for xx in range(width):
            col = xx * 4
            b = g = r = a = 0
            for off, weight in samples:
                i = off + col
                b += tmp[i] * weight
                g += tmp[i + 1] * weight
                r += tmp[i + 2] * weight
                a += tmp[i + 3] * weight
            di = row + col
            out[di] = (b + 512) >> 10
            out[di + 1] = (g + 512) >> 10
            out[di + 2] = (r + 512) >> 10
            out[di + 3] = (a + 512) >> 10
    return QImage(bytes(out), width, height, width * 4, QImage.Format_ARGB32).copy()


def fit_font(paragraph, text, font_family):
    """段落字号：基准取行高 0.75 倍夹在 [10, 32]，再按译文长度收缩。"""
    line_h = paragraph.rect[3] / max(1, len(paragraph.lines))
    base = max(10, min(FONT_MAX, int(line_h * 0.75)))
    size, _lines = tc.fit_text(text, paragraph.rect[2], paragraph.rect[3],
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
            rect = tc.mosaic_rect(line.bbox, BLUR_EXPAND, bounds)
            blurred = _gaussian_blur(base, rect, base_dpr)
            if blurred is not None:
                p.drawImage(QRectF(*rect), blurred, QRectF(blurred.rect()))
        x, y, w, h = para.rect
        lum = _luminance(base, (int(x * base_dpr), int(y * base_dpr),
                                max(1, int(w * base_dpr)), max(1, int(h * base_dpr))))
        color = QColor('#1a1610') if lum > 0.55 else QColor('#ffffff')
        f = QFont(font_family)
        f.setPixelSize(fit_font(para, text, font_family))
        p.setFont(f)
        p.setPen(color)
        p.drawText(QRectF(x, y, w, h),
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