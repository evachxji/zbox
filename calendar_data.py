# -*- coding: utf-8 -*-
"""节假日数据（内置官方调休 + 联网更新 + 离线导入）与农历计算。兼容 Python 3.8 / Win7。"""
import json
import os
import urllib.request
from datetime import date, timedelta


def _span(y, m1, d1, m2, d2, names=None):
    """生成 [y-m1-d1, y-m2-d2] 区间映射 {iso: name or None}，names 按偏移命名特殊日。"""
    out = {}
    cur, end, i = date(y, m1, d1), date(y, m2, d2), 0
    while cur <= end:
        out[cur.isoformat()] = (names or {}).get(i)
        cur += timedelta(days=1)
        i += 1
    return out


# ---------- 内置：国务院公布的官方放假调休安排 ----------
EMBEDDED_OFF = {}   # iso -> 节日名(仅关键日) 或 None
EMBEDDED_WORK = set()  # 调休上班日

# 2025 年（2024-11 发布）
EMBEDDED_OFF.update(_span(2025, 1, 1, 1, 1, {0: '元旦'}))
EMBEDDED_OFF.update(_span(2025, 1, 28, 2, 4, {0: '除夕', 1: '春节'}))
EMBEDDED_OFF.update(_span(2025, 4, 4, 4, 6, {0: '清明'}))
EMBEDDED_OFF.update(_span(2025, 5, 1, 5, 5, {0: '劳动节'}))
EMBEDDED_OFF.update(_span(2025, 5, 31, 6, 2, {0: '端午'}))
EMBEDDED_OFF.update(_span(2025, 10, 1, 10, 8, {0: '国庆', 5: '中秋'}))
EMBEDDED_WORK.update(['2025-01-26', '2025-02-08', '2025-04-27', '2025-09-28', '2025-10-11'])

# 2026 年（2025-11 发布）
EMBEDDED_OFF.update(_span(2026, 1, 1, 1, 3, {0: '元旦'}))
EMBEDDED_OFF.update(_span(2026, 2, 15, 2, 23, {1: '除夕', 2: '春节'}))
EMBEDDED_OFF.update(_span(2026, 4, 4, 4, 6, {1: '清明'}))
EMBEDDED_OFF.update(_span(2026, 5, 1, 5, 5, {0: '劳动节'}))
EMBEDDED_OFF.update(_span(2026, 6, 19, 6, 21, {0: '端午'}))
EMBEDDED_OFF.update(_span(2026, 9, 25, 9, 27, {0: '中秋'}))
EMBEDDED_OFF.update(_span(2026, 10, 1, 10, 7, {0: '国庆'}))
EMBEDDED_WORK.update(['2026-01-04', '2026-02-14', '2026-02-28', '2026-05-09', '2026-09-20', '2026-10-10'])

API_URL = 'https://timor.tech/api/holiday/year/%d'  # jiejiariapi.com 同源接口


class HolidayStore(object):
    """节假日数据：自定义（联网/导入）优先，内置官方数据兜底，其余年份只标节日不标休班。"""

    def __init__(self, path):
        self.path = path
        self.off = {}    # iso -> name
        self.work = set()
        self.load()

    def load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            self.off = dict(d.get('off', {}))
            self.work = set(d.get('work', []))
        except Exception:
            self.off, self.work = {}, set()

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({'off': self.off, 'work': sorted(self.work)}, f, ensure_ascii=False, indent=1)

    def info(self, d):
        """返回 (名称, 类型)：类型 'off'=休 / 'work'=班 / None=普通日。"""
        iso = d.isoformat()
        if iso in self.off:
            return self.off[iso], 'off'
        if iso in self.work:
            return '班', 'work'
        if iso in EMBEDDED_OFF:
            return EMBEDDED_OFF[iso], 'off'
        if iso in EMBEDDED_WORK:
            return '班', 'work'
        return None, None

    @staticmethod
    def _short_name(name):
        name = (name or '').strip()
        if len(name) > 2 and name.endswith('节'):
            name = name[:-1]
        return name or None

    def import_api_json(self, text):
        """导入 jiejiariapi.com / timor.tech 的年份 JSON，返回条目数。"""
        data = json.loads(text)
        hol = data.get('holiday')
        if hol is None and isinstance(data.get('data'), dict):
            hol = data['data'].get('holiday')
        if not isinstance(hol, dict):
            raise ValueError('无法识别的节假日 JSON 格式')
        n = 0
        for key, v in hol.items():
            if not isinstance(v, dict) or 'holiday' not in v:
                continue
            d = v.get('date')
            if not d:  # key 形如 "10-01"，补年份
                y = str(data.get('year') or '')
                if not y and '-' in key and len(key) == 5:
                    continue
                d = '%s-%s' % (y, key)
            if v['holiday']:
                self.off[d] = self._short_name(v.get('name'))
                self.work.discard(d)
            else:
                self.work.add(d)
                self.off.pop(d, None)
            n += 1
        self.save()
        return n

    def fetch_year(self, year, timeout=10):
        with urllib.request.urlopen(API_URL % year, timeout=timeout) as r:
            return self.import_api_json(r.read().decode('utf-8'))

    def reset(self):
        self.off, self.work = {}, set()
        self.save()


# ---------- 农历（1900-2100 通用查表法） ----------
LUNAR_INFO = [
    0x04bd8, 0x04ae0, 0x0a570, 0x054d5, 0x0d260, 0x0d950, 0x16554, 0x056a0, 0x09ad0, 0x055d2,  # 1900-1909
    0x04ae0, 0x0a5b6, 0x0a4d0, 0x0d250, 0x1d255, 0x0b540, 0x0d6a0, 0x0ada2, 0x095b0, 0x14977,  # 1910-1919
    0x04970, 0x0a4b0, 0x0b4b5, 0x06a50, 0x06d40, 0x1ab54, 0x02b60, 0x09570, 0x052f2, 0x04970,  # 1920-1929
    0x06566, 0x0d4a0, 0x0ea50, 0x06e95, 0x05ad0, 0x02b60, 0x186e3, 0x092e0, 0x1c8d7, 0x0c950,  # 1930-1939
    0x0d4a0, 0x1d8a6, 0x0b550, 0x056a0, 0x1a5b4, 0x025d0, 0x092d0, 0x0d2b2, 0x0a950, 0x0b557,  # 1940-1949
    0x06ca0, 0x0b550, 0x15355, 0x04da0, 0x0a5b0, 0x14573, 0x052b0, 0x0a9a8, 0x0e950, 0x06aa0,  # 1950-1959
    0x0aea6, 0x0ab50, 0x04b60, 0x0aae4, 0x0a570, 0x05260, 0x0f263, 0x0d950, 0x05b57, 0x056a0,  # 1960-1969
    0x096d0, 0x04dd5, 0x04ad0, 0x0a4d0, 0x0d4d4, 0x0d250, 0x0d558, 0x0b540, 0x0b5a0, 0x195a6,  # 1970-1979
    0x095b0, 0x049b0, 0x0a974, 0x0a4b0, 0x0b27a, 0x06a50, 0x06d40, 0x0af46, 0x0ab60, 0x09570,  # 1980-1989
    0x04af5, 0x04970, 0x064b0, 0x074a3, 0x0ea50, 0x06b58, 0x055c0, 0x0ab60, 0x096d5, 0x092e0,  # 1990-1999
    0x0c960, 0x0d954, 0x0d4a0, 0x0da50, 0x07552, 0x056a0, 0x0abb7, 0x025d0, 0x092d0, 0x0cab5,  # 2000-2009
    0x0a950, 0x0b4a0, 0x0baa4, 0x0ad50, 0x055d9, 0x04ba0, 0x0a5b0, 0x15176, 0x052b0, 0x0a930,  # 2010-2019
    0x07954, 0x06aa0, 0x0ad50, 0x05b52, 0x04b60, 0x0a6e6, 0x0a4e0, 0x0d260, 0x0ea65, 0x0d530,  # 2020-2029
    0x05aa0, 0x076a3, 0x096d0, 0x04afb, 0x04ad0, 0x0a4d0, 0x1d0b6, 0x0d250, 0x0d520, 0x0dd45,  # 2030-2039
    0x0b5a0, 0x056d0, 0x055b2, 0x049b0, 0x0a577, 0x0a4b0, 0x0aa50, 0x1b255, 0x06d20, 0x0ada0,  # 2040-2049
    0x14b63, 0x09370, 0x049f8, 0x04970, 0x064b0, 0x168a6, 0x0ea50, 0x06b20, 0x1a6c4, 0x0aae0,  # 2050-2059
    0x0a2e0, 0x0d2e3, 0x0c960, 0x0d557, 0x0d4a0, 0x0da50, 0x05d55, 0x056a0, 0x0a6d0, 0x055d4,  # 2060-2069
    0x052d0, 0x0a9b8, 0x0a950, 0x0b4a0, 0x0b6a6, 0x0ad50, 0x055a0, 0x0aba4, 0x0a5b0, 0x052b0,  # 2070-2079
    0x0b273, 0x06930, 0x07337, 0x06aa0, 0x0ad50, 0x14b55, 0x04b60, 0x0a570, 0x054e4, 0x0d160,  # 2080-2089
    0x0e968, 0x0d520, 0x0daa0, 0x16aa6, 0x056d0, 0x04ae0, 0x0a9d4, 0x0a2d0, 0x0d150, 0x0f252,  # 2090-2099
    0x0d520,                                                                              # 2100
]

MONTH_NAMES = ['正', '二', '三', '四', '五', '六', '七', '八', '九', '十', '冬', '腊']
DAY_PREFIX = ['初', '十', '廿', '卅']
DAY_NUM = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
GAN = '甲乙丙丁戊己庚辛壬癸'
ZHI = '子丑寅卯辰巳午未申酉戌亥'
LUNAR_FESTIVALS = {(1, 1): '春节', (1, 15): '元宵', (5, 5): '端午', (7, 7): '七夕',
                   (8, 15): '中秋', (9, 9): '重阳', (12, 8): '腊八'}
SOLAR_FESTIVALS = {(1, 1): '元旦', (5, 1): '劳动节', (10, 1): '国庆'}


def _leap_month(y):
    return LUNAR_INFO[y - 1900] & 0xF


def _leap_days(y):
    return 30 if (LUNAR_INFO[y - 1900] & 0x10000) else 29


def _month_days(y, m):
    return 30 if (LUNAR_INFO[y - 1900] & (0x10000 >> m)) else 29


def _year_days(y):
    total = 348
    info = LUNAR_INFO[y - 1900]
    m = 0x8000
    while m > 0x8:
        if info & m:
            total += 1
        m >>= 1
    return total + (_leap_days(y) if _leap_month(y) else 0)


def solar_to_lunar(y, m, d):
    """公历 -> (农历年, 月, 日, 是否闰月)；超出 1900-2100 返回 None。"""
    offset = (date(y, m, d) - date(1900, 1, 31)).days
    if offset < 0 or offset > 73514:
        return None
    ly = 1900
    while True:
        yd = _year_days(ly)
        if offset < yd:
            break
        offset -= yd
        ly += 1
    leap = _leap_month(ly)
    is_leap = False
    i = 1
    days = 0
    while i < 13 and offset > 0:
        if leap > 0 and i == leap + 1 and not is_leap:
            i -= 1
            is_leap = True
            days = _leap_days(ly)
        else:
            days = _month_days(ly, i)
        if is_leap and i == leap + 1:
            is_leap = False
        offset -= days
        i += 1
    if offset == 0 and leap > 0 and i == leap + 1:
        if is_leap:
            is_leap = False
        else:
            is_leap = True
            i -= 1
    if offset < 0:
        offset += days
        i -= 1
    return ly, i, offset + 1, is_leap


def lunar_day_text(m, d, is_leap):
    """农历日期显示：初一显示月份名（如‘八月’），其余显示‘廿三’等。"""
    if d == 1:
        return ('闰' if is_leap else '') + MONTH_NAMES[m - 1] + '月'
    if d == 10:
        return '初十'
    if d == 20:
        return '二十'
    if d == 30:
        return '三十'
    return DAY_PREFIX[(d - 1) // 10] + DAY_NUM[(d - 1) % 10]


def qingming_day(y):
    """清明节气日（4月4或5日），21/20 世纪经验公式。"""
    c = 4.81 if y >= 2000 else 5.59
    yy = y % 100
    return int(yy * 0.2422 + c) - int((yy - 1) // 4)


def festival_name(d):
    """公历 date -> 节日名（清明/公历节日/农历节日），无则 None。"""
    if (d.month, d.day) in SOLAR_FESTIVALS:
        return SOLAR_FESTIVALS[(d.month, d.day)]
    if d.month == 4 and d.day == qingming_day(d.year):
        return '清明'
    lun = solar_to_lunar(d.year, d.month, d.day)
    if lun and not lun[3]:
        return LUNAR_FESTIVALS.get((lun[1], lun[2]))
    return None


def lunar_text(d):
    """日历格子副标题：优先节日名，否则农历日/月名。"""
    name = festival_name(d)
    if name:
        return name
    lun = solar_to_lunar(d.year, d.month, d.day)
    if not lun:
        return ''
    return lunar_day_text(lun[1], lun[2], lun[3])


def ganzhi_year(lunar_year):
    return GAN[(lunar_year - 4) % 10] + ZHI[(lunar_year - 4) % 12]
