# -*- coding: utf-8 -*-
"""桌面卡片的同边吸附求解与辅助线覆盖层。"""
from collections import namedtuple

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget


EDGE_LEFT = 1
EDGE_RIGHT = 2
EDGE_TOP = 4
EDGE_BOTTOM = 8
SNAP_ENGAGE = 8
SNAP_RELEASE = 12

SnapMatch = namedtuple('SnapMatch', 'coordinate target_index resolved_origin')


def _interval_gap(a0, a1, b0, b1):
    if a1 < b0:
        return b0 - a1
    if b1 < a0:
        return a0 - b1
    return 0


def _best_same_edge(source, targets, axis, engage):
    candidates = []
    if axis == 0:
        perpendicular_gap = lambda target: _interval_gap(
            source.y(), source.y() + source.height(),
            target.y(), target.y() + target.height())
        center_distance = lambda target: abs(
            source.y() + source.height() - target.y() - target.height())
        edges = (
            (source.x(), lambda target: target.x(), 0),
            (source.x() + source.width(),
             lambda target: target.x() + target.width(), 1),
        )
    else:
        perpendicular_gap = lambda target: _interval_gap(
            source.x(), source.x() + source.width(),
            target.x(), target.x() + target.width())
        center_distance = lambda target: abs(
            source.x() + source.width() - target.x() - target.width())
        edges = (
            (source.y(), lambda target: target.y(), 0),
            (source.y() + source.height(),
             lambda target: target.y() + target.height(), 1),
        )

    for target_index, target in enumerate(targets):
        if target.isNull():
            continue
        gap = perpendicular_gap(target)
        center = center_distance(target)
        for source_edge, target_edge, edge_index in edges:
            coordinate = target_edge(target)
            delta = abs(source_edge - coordinate)
            if delta <= engage:
                candidates.append((
                    delta, gap, center, coordinate, target_index, edge_index))
    if not candidates:
        return None
    delta, _gap, _center, coordinate, target_index, edge_index = min(candidates)
    if axis == 0:
        resolved = coordinate if edge_index == 0 else coordinate - source.width()
    else:
        resolved = coordinate if edge_index == 0 else coordinate - source.height()
    return SnapMatch(coordinate, target_index, resolved)


def snap_move(proposed, targets, engage=8, release=12, sticky=(None, None)):
    """返回同边吸附后的几何与横纵轴吸附状态。"""
    engage, release = max(0, engage), max(0, release)
    source = QRect(proposed)
    out = QRect(proposed)
    next_sticky = [None, None]

    for axis, previous in enumerate(sticky):
        origin = source.x() if axis == 0 else source.y()
        if previous is not None and \
                abs(origin - previous.resolved_origin) <= release:
            match = previous
        else:
            match = _best_same_edge(source, targets, axis, engage)
        next_sticky[axis] = match
        if match is not None:
            if axis == 0:
                out.moveLeft(match.resolved_origin)
            else:
                out.moveTop(match.resolved_origin)

    return out, tuple(next_sticky)


def snap_resize(proposed, edges, targets, engage=8, release=12,
                sticky=(None, None)):
    """缩放时只吸附正在移动的边缘，返回新几何与横纵轴吸附状态。"""
    engage, release = max(0, engage), max(0, release)
    source = QRect(proposed)
    out = QRect(proposed)
    next_sticky = [None, None]

    horizontal = EDGE_LEFT if edges & EDGE_LEFT else (
        EDGE_RIGHT if edges & EDGE_RIGHT else 0)
    vertical = EDGE_TOP if edges & EDGE_TOP else (
        EDGE_BOTTOM if edges & EDGE_BOTTOM else 0)

    for axis, edge, previous in ((0, horizontal, sticky[0]),
                                 (1, vertical, sticky[1])):
        if not edge:
            continue
        if axis == 0:
            current = source.x() if edge == EDGE_LEFT else \
                source.x() + source.width()
        else:
            current = source.y() if edge == EDGE_TOP else \
                source.y() + source.height()

        if previous is not None and abs(current - previous.coordinate) <= release:
            match = previous
        else:
            candidates = []
            for target_index, target in enumerate(targets):
                if target.isNull():
                    continue
                if edge == EDGE_LEFT:
                    coordinate = target.x()
                elif edge == EDGE_RIGHT:
                    coordinate = target.x() + target.width()
                elif edge == EDGE_TOP:
                    coordinate = target.y()
                else:
                    coordinate = target.y() + target.height()
                delta = abs(current - coordinate)
                if delta <= engage:
                    candidates.append((delta, coordinate, target_index))
            match = None
            if candidates:
                _delta, coordinate, target_index = min(candidates)
                match = SnapMatch(coordinate, target_index, coordinate)

        next_sticky[axis] = match
        if match is None:
            continue
        if edge == EDGE_LEFT:
            right = out.x() + out.width()
            out.setRect(match.coordinate, out.y(),
                        right - match.coordinate, out.height())
        elif edge == EDGE_RIGHT:
            out.setWidth(match.coordinate - out.x())
        elif edge == EDGE_TOP:
            bottom = out.y() + out.height()
            out.setRect(out.x(), match.coordinate,
                        out.width(), bottom - match.coordinate)
        else:
            out.setHeight(match.coordinate - out.y())

    return out, tuple(next_sticky)


def guide_segments(source, targets, matches, cap=8):
    """把同边吸附匹配转成覆盖两张卡片的全局辅助线段。"""
    segments = []

    def closest(axis, coordinate, end_edge):
        candidates = []
        for target in targets:
            if target.isNull():
                continue
            target_coordinate = (
                target.x() + target.width() if end_edge else target.x()
            ) if axis == 0 else (
                target.y() + target.height() if end_edge else target.y()
            )
            if target_coordinate != coordinate:
                continue
            if axis == 0:
                gap = _interval_gap(
                    source.y(), source.y() + source.height(),
                    target.y(), target.y() + target.height())
                center = abs(
                    source.y() + source.height() - target.y() - target.height())
            else:
                gap = _interval_gap(
                    source.x(), source.x() + source.width(),
                    target.x(), target.x() + target.width())
                center = abs(
                    source.x() + source.width() - target.x() - target.width())
            candidates.append((gap, center, target))
        return min(candidates, default=(None, None, None))[2]

    if matches[0] is not None:
        for coordinate, end_edge in ((source.x(), False),
                                     (source.x() + source.width(), True)):
            target = closest(0, coordinate, end_edge)
            if target is None:
                continue
            top = min(source.y(), target.y()) - cap
            bottom = max(source.y() + source.height(),
                         target.y() + target.height()) + cap
            segments.append((coordinate, top, coordinate, bottom))

    if matches[1] is not None:
        for coordinate, end_edge in ((source.y(), False),
                                     (source.y() + source.height(), True)):
            target = closest(1, coordinate, end_edge)
            if target is None:
                continue
            left = min(source.x(), target.x()) - cap
            right = max(source.x() + source.width(),
                        target.x() + target.width()) + cap
            segments.append((left, coordinate, right, coordinate))
    return segments


class SnapGuideOverlay(QWidget):
    """卡片移动或缩放吸附期间跨卡片绘制的无输入透明辅助线。"""

    def __init__(self, parent=None, scale=1.0):
        super(SnapGuideOverlay, self).__init__(
            parent, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint |
            Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self._scale = max(0.75, min(float(scale), 3.0))
        self._segments = []

    def show_segments(self, segments):
        self._segments = list(segments)
        if not self._segments:
            self.hide()
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        # 不能恰好占满整个虚拟屏幕：Win11 专注助手的「全屏应用」自动规则会把这种
        # 无边框全屏置顶窗识别成全屏应用并自动打开勿扰（任务栏出现铃铛图标），
        # 右/下各收 1px 避开判定，辅助线绘制不受影响
        geometry = screen.virtualGeometry().adjusted(0, 0, -1, -1)
        if self.geometry() != geometry:
            self.setGeometry(geometry)
        if not self.isVisible():
            self.show()
            self.raise_()
        self.update()

    def paintEvent(self, _e):
        if not self._segments:
            return
        origin = self.geometry().topLeft()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        glow = QPen(QColor(110, 168, 254, 58),
                    max(2.0, round(3.0 * self._scale)))
        glow.setCapStyle(Qt.RoundCap)
        core = QPen(QColor(142, 196, 255, 235),
                    max(1.0, round(1.0 * self._scale)))
        core.setCapStyle(Qt.RoundCap)
        for x1, y1, x2, y2 in self._segments:
            p1 = QPoint(x1, y1) - origin
            p2 = QPoint(x2, y2) - origin
            painter.setPen(glow)
            painter.drawLine(p1, p2)
            painter.setPen(core)
            painter.drawLine(p1, p2)
        painter.end()
