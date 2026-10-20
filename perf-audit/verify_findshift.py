# -*- coding: utf-8 -*-
"""验证 P1-11：_find_shift 向量化前后结果完全一致 + 加速比。

做法：造随机行签名，用「原实现」与「新实现」分别算位移与差值，逐组比对。

用法：python perf-audit\\verify_findshift.py
"""
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import screenshot as S   # noqa: E402


def old_find_shift(prev, cur):
    """原实现（纯 Python 索引循环）的等价副本。"""
    n = min(len(prev), len(cur))
    cands = []
    for s in range(0, min(n - 2, n // 2) + 1):
        d, cnt = 0, 0
        for i in range(0, n - s, 2):
            d += abs(prev[s + i][0] - cur[i][0])
            cnt += 1
        if cnt:
            cands.append((d / cnt, s))
    scores = []
    for _m, s in sorted(cands)[:5]:
        d, cnt = 0, 0
        for i in range(0, n - s, 2):
            pa, ca = prev[s + i][1], cur[i][1]
            for x in range(S._SIG_BUCKETS):
                d += abs(pa[x] - ca[x])
                cnt += 1
        if cnt:
            scores.append((d / cnt, s))
    if not scores:
        return 0, 1e9
    best_d = min(d for d, _s in scores)
    best_s = min(s for d, s in scores if d <= best_d * 1.1 + 0.5)
    return best_s, best_d


def make_sig(n, seed):
    rnd = random.Random(seed)
    sig = []
    for _ in range(n):
        buckets = tuple(rnd.randrange(256) for _ in range(S._SIG_BUCKETS))
        sig.append((sum(buckets) // len(buckets), buckets))
    return sig


def main():
    bad = 0
    cases = 0
    t_old = t_new = 0.0
    for n in (200, 540, 1080):
        for seed in range(6):
            prev = make_sig(n, seed)
            # cur = prev 往下滚 shift 行（模拟滚动）
            shift = random.Random(seed * 7 + 1).randrange(1, max(2, n // 3))
            cur = prev[shift:] + make_sig(n - shift, seed + 999)
            a = old_find_shift(prev, cur)
            t0 = time.perf_counter()
            b = S._find_shift(prev, cur)
            t1 = time.perf_counter()
            # 旧实现也测一次时间
            t0b = time.perf_counter()
            old_find_shift(prev, cur)
            t1b = time.perf_counter()
            t_old += t1b - t0b
            t_new += t1 - t0
            cases += 1
            same = (a[0] == b[0]) and abs(a[1] - b[1]) < 1e-9
            if not same:
                bad += 1
                print('不一致 n=%d seed=%d: old=%s new=%s' % (n, seed, a, b))
    print('\n%d 组比对：%s' % (cases, '全部一致 ✓' if bad == 0 else '有 %d 组不一致 ✗' % bad))
    print('旧实现 %.1f ms  新实现 %.1f ms  加速 %.2fx'
          % (t_old * 1000, t_new * 1000, t_old / max(t_new, 1e-9)))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
