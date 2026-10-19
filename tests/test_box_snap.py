# -*- coding: utf-8 -*-
"""桌面卡片移动、缩放吸附的几何回归测试。"""
import unittest
from types import SimpleNamespace

from PySide6.QtCore import QRect

from boxes import BoxManager
from snapping import (EDGE_BOTTOM, EDGE_LEFT, EDGE_RIGHT, EDGE_TOP,
                      guide_segments, snap_move, snap_resize)


class CardSnapTest(unittest.TestCase):
    target = QRect(202, 202, 100, 100)

    def test_same_edges_align_on_both_axes(self):
        snapped, sticky = snap_move(QRect(207, 205, 80, 60), [self.target])

        self.assertEqual(snapped.topLeft().toTuple(), (202, 202))
        self.assertIsNotNone(sticky[0])
        self.assertIsNotNone(sticky[1])

    def test_right_and_bottom_edges_align_to_same_edges(self):
        snapped, sticky = snap_move(QRect(215, 195, 80, 100), [self.target])

        self.assertEqual(snapped.topLeft().toTuple(), (222, 202))
        self.assertIsNotNone(sticky[0])
        self.assertIsNotNone(sticky[1])

    def test_left_edge_may_snap_rightward_to_target_left(self):
        snapped, sticky = snap_move(QRect(198, 220, 80, 60), [self.target])

        self.assertEqual(snapped.x(), 202)
        self.assertIsNotNone(sticky[0])

    def test_opposite_horizontal_edges_do_not_snap(self):
        snapped, sticky = snap_move(QRect(96, 220, 100, 60), [self.target])

        self.assertEqual(snapped.topLeft().toTuple(), (96, 220))
        self.assertIsNone(sticky[0])

    def test_opposite_vertical_edges_do_not_snap(self):
        snapped, sticky = snap_move(QRect(220, 96, 60, 100), [self.target])

        self.assertEqual(snapped.topLeft().toTuple(), (220, 96))
        self.assertIsNone(sticky[1])

    def test_sticky_match_holds_past_engage_threshold(self):
        _, sticky = snap_move(QRect(205, 220, 100, 60), [self.target])

        held, held_sticky = snap_move(
            QRect(214, 220, 100, 60), [self.target], sticky=sticky)

        self.assertEqual(held.x(), 202)
        self.assertIsNotNone(held_sticky[0])

    def test_sticky_match_releases_past_release_threshold(self):
        _, sticky = snap_move(QRect(205, 220, 100, 60), [self.target])

        released, released_sticky = snap_move(
            QRect(215, 220, 100, 60), [self.target], sticky=sticky)

        self.assertEqual(released.x(), 215)
        self.assertIsNone(released_sticky[0])

    def test_axis_outside_engage_threshold_does_not_snap(self):
        snapped, _ = snap_move(QRect(120, 120, 60, 60), [self.target])

        self.assertEqual(snapped.topLeft().toTuple(), (120, 120))

    def test_guide_segments_span_source_and_target_on_both_axes(self):
        source = QRect(207, 205, 80, 60)
        snapped, sticky = snap_move(source, [self.target])

        segments = guide_segments(snapped, [self.target], sticky)

        self.assertEqual(segments, [
            (202, 194, 202, 310),
            (194, 202, 310, 202),
        ])

    def test_equal_width_move_shows_both_vertical_guides(self):
        source = QRect(207, 220, 100, 60)
        snapped, sticky = snap_move(source, [self.target])

        segments = guide_segments(snapped, [self.target], sticky)

        self.assertEqual(segments, [
            (202, 194, 202, 310),
            (302, 194, 302, 310),
        ])

    def test_equal_height_move_shows_both_horizontal_guides(self):
        source = QRect(220, 205, 60, 100)
        snapped, sticky = snap_move(source, [self.target])

        segments = guide_segments(snapped, [self.target], sticky)

        self.assertEqual(segments, [
            (194, 202, 310, 202),
            (194, 302, 310, 302),
        ])

    def test_no_guide_segments_without_snap(self):
        snapped, sticky = snap_move(QRect(96, 220, 100, 60), [self.target])

        self.assertEqual(guide_segments(snapped, [self.target], sticky), [])

    def test_resize_right_edge_aligns_to_target_right(self):
        snapped, sticky = snap_resize(
            QRect(96, 220, 200, 60), EDGE_RIGHT, [self.target])

        self.assertEqual(snapped, QRect(96, 220, 206, 60))
        self.assertEqual(sticky[0].coordinate, 302)

    def test_resize_left_edge_aligns_to_target_left(self):
        snapped, sticky = snap_resize(
            QRect(207, 220, 95, 60), EDGE_LEFT, [self.target])

        self.assertEqual(snapped, QRect(202, 220, 100, 60))
        self.assertEqual(sticky[0].coordinate, 202)

    def test_resize_top_edge_aligns_to_target_top(self):
        snapped, sticky = snap_resize(
            QRect(220, 207, 60, 95), EDGE_TOP, [self.target])

        self.assertEqual(snapped, QRect(220, 202, 60, 100))
        self.assertEqual(sticky[1].coordinate, 202)

    def test_resize_bottom_edge_aligns_to_target_bottom(self):
        snapped, sticky = snap_resize(
            QRect(220, 96, 60, 200), EDGE_BOTTOM, [self.target])

        self.assertEqual(snapped, QRect(220, 96, 60, 206))
        self.assertEqual(sticky[1].coordinate, 302)

    def test_resize_opposite_edges_do_not_snap(self):
        snapped, sticky = snap_resize(
            QRect(96, 220, 100, 60), EDGE_RIGHT, [self.target])

        self.assertEqual(snapped, QRect(96, 220, 100, 60))
        self.assertIsNone(sticky[0])

    def test_resize_sticky_match_holds_then_releases(self):
        _, sticky = snap_resize(
            QRect(96, 220, 200, 60), EDGE_RIGHT, [self.target])

        held, held_sticky = snap_resize(
            QRect(96, 220, 212, 60), EDGE_RIGHT, [self.target], sticky=sticky)
        released, released_sticky = snap_resize(
            QRect(96, 220, 219, 60), EDGE_RIGHT, [self.target], sticky=held_sticky)

        self.assertEqual(held.right() + 1, 302)
        self.assertEqual(held_sticky[0].coordinate, 302)
        self.assertEqual(released.right() + 1, 315)
        self.assertIsNone(released_sticky[0])

    def test_shared_targets_exclude_source_and_include_panel(self):
        first = SimpleNamespace(
            geometry=lambda: QRect(0, 0, 100, 100), isVisible=lambda: True)
        second = SimpleNamespace(
            geometry=lambda: QRect(120, 0, 100, 100), isVisible=lambda: True)
        hidden = SimpleNamespace(
            geometry=lambda: QRect(240, 0, 100, 100), isVisible=lambda: False)
        panel = SimpleNamespace(
            geometry=lambda: QRect(360, 0, 120, 100), isVisible=lambda: True)
        manager = SimpleNamespace(windows=[first, second, hidden], panel=panel)

        rects = BoxManager.snap_card_rects(manager, exclude=first)

        self.assertEqual(rects, [QRect(120, 0, 100, 100),
                                 QRect(360, 0, 120, 100)])


if __name__ == '__main__':
    unittest.main()
