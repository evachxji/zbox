# -*- coding: utf-8 -*-
"""截图前后对比工具：
    python tools/compare_shots.py <before_dir> <after_dir> <report_dir>

逐场景（同名 PNG）逐像素对比，生成 report.md：
  全场景一致 → exit 0；任何场景有差异/缺失 → exit 1。
报告里全同的场景标 ✅，有差异的场景附 前/后/差异高亮 三张图供人工目检。
验收口径（feat-drop-win7）：目标零差异；残差场景要求 ≥99.95% 像素一致
且差异仅沿字形边缘（由人工看差异高亮图确认）。
"""
import os
import sys

from PIL import Image, ImageChops

PASS_RESIDUAL_PCT = 0.05   # 残差上限：差异像素占比 ≤0.05%（即 ≥99.95% 一致）


def _diff_stats(before, after):
    """返回 (差异像素数, 占比%, 最大通道差, 差异高亮图)。尺寸不同返回 None。"""
    if before.size != after.size:
        return None
    diff = ImageChops.difference(before, after)
    masks = [c.point(lambda v: 255 if v else 0) for c in diff.split()]
    mask = masks[0]
    for m in masks[1:]:
        mask = ImageChops.lighter(mask, m)
    n_diff = mask.histogram()[255]
    max_delta = max(band.getextrema()[1] for band in diff.split())
    total = before.size[0] * before.size[1]
    # 差异高亮：以后图（RGBA 合成到白底）为底，差异像素涂红
    hi = Image.new('RGB', after.size, (255, 255, 255))
    hi.paste(after.convert('RGB'), (0, 0), after.split()[3])
    red = Image.new('RGB', after.size, (255, 0, 0))
    hi.paste(red, (0, 0), mask)
    return n_diff, n_diff * 100.0 / total, max_delta, hi


def main(before_dir, after_dir, report_dir):
    names = sorted(f for f in os.listdir(before_dir) if f.lower().endswith('.png'))
    if not names:
        print('before 目录里没有 PNG：%s' % before_dir)
        return 1
    os.makedirs(report_dir, exist_ok=True)
    rows = []
    sections = []
    n_bad = 0
    for name in names:
        bp = os.path.join(before_dir, name)
        ap = os.path.join(after_dir, name)
        scene = os.path.splitext(name)[0]
        if not os.path.exists(ap):
            rows.append('| %s | ❌ 缺失 | — | — | — |' % scene)
            n_bad += 1
            continue
        before = Image.open(bp).convert('RGBA')
        after = Image.open(ap).convert('RGBA')
        stats = _diff_stats(before, after)
        if stats is None:
            rows.append('| %s | ❌ 尺寸不同 %sx%s → %sx%s | — | — | — |'
                        % (scene, before.width, before.height, after.width, after.height))
            n_bad += 1
            verdict_icon = '❌'
        else:
            n_diff, pct, max_delta, hi = stats
            if n_diff == 0:
                rows.append('| %s | ✅ 完全一致 | 0 | 0%% | 0 |' % scene)
                continue
            residual = pct <= PASS_RESIDUAL_PCT
            verdict_icon = '⚠️ 残差' if residual else '❌ 有差异'
            rows.append('| %s | %s | %d | %.4f%% | %d |'
                        % (scene, verdict_icon, n_diff, pct, max_delta))
            n_bad += 1
        # 有差异/异常的场景：三图落盘 + 报告嵌入
        before.convert('RGB').save(os.path.join(report_dir, '%s_before.png' % scene))
        after.convert('RGB').save(os.path.join(report_dir, '%s_after.png' % scene))
        if stats is not None:
            stats[3].save(os.path.join(report_dir, '%s_diff.png' % scene))
        sections.append(
            '### %s\n\n| 前（PyQt5） | 后（PySide6） | 差异高亮 |\n'
            '| --- | --- | --- |\n| ![前](%s_before.png) | ![后](%s_after.png) | ![差](%s_diff.png) |\n'
            % (scene, scene, scene, scene))
    extra = sorted(f for f in os.listdir(after_dir)
                   if f.lower().endswith('.png') and f not in names)
    lines = ['# 截图前后对比报告', '',
             '- before：`%s`' % os.path.abspath(before_dir),
             '- after：`%s`' % os.path.abspath(after_dir),
             '- 场景数：%d；完全一致：%d；有差异/异常：%d'
             % (len(names), len(names) - n_bad, n_bad),
             '- 残差口径：差异像素占比 ≤%.2f%% 且仅沿字形边缘（看差异高亮图确认）'
             % PASS_RESIDUAL_PCT, '',
             '| 场景 | 结果 | 差异像素 | 占比 | 最大通道差 |',
             '| --- | --- | --- | --- | --- |']
    lines += rows
    if extra:
        lines += ['', '## after 中多出的场景', ''] + ['- %s' % f for f in extra]
    if sections:
        lines += ['', '## 差异场景明细', ''] + sections
    with open(os.path.join(report_dir, 'report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('场景 %d 个，完全一致 %d，有差异 %d。报告：%s'
          % (len(names), len(names) - n_bad, n_bad,
             os.path.join(report_dir, 'report.md')))
    return 0 if n_bad == 0 else 1


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
