# -*- coding: utf-8 -*-
"""两套主题 QSS。%CN% / %NUM% 为字体占位符，运行时按系统可用字体替换。"""

COMMON = """
QToolTip { color: %TOOLTIP%; }
QScrollBar:vertical { background: transparent; width: 6px; margin: 2px; }
QScrollBar::handle:vertical { background: %SCROLL%; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QFrame#todoEditRow { background: transparent; }
"""

NOCTURNE = {
    'name': '深色',
    'count_fmt': '{:02d} OPEN',
    'week': ['周一', '周二', '周三', '周四', '周五', '周六', '周日'],
    'qss': COMMON.replace('%TOOLTIP%', '#e8e6e1').replace('%SCROLL%', 'rgba(255,255,255,40)') + """
QWidget#panelRoot { background: #1b1d24; }
QWidget#panel {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1e2028, stop:1 #15181d);
    border: 1px solid rgba(255,255,255,22);
    border-radius: 16px;
}
QFrame#tabBox { background: transparent; }
QToolButton#tab {
    background: transparent; border: none; border-bottom: 2px solid transparent;
    color: #7d7a72; font: 600 13px "%CN%"; padding: 4px 2px 5px;
}
QToolButton#tab[active="true"] { color: #f0ede6; border-bottom: 2px solid #e8a33d; }
QToolButton#iconBtn {
    background: transparent; border: none; border-radius: 6px;
    color: #7d7a72; font: 12px "%CN%";
}
QToolButton#iconBtn:hover { background: rgba(255,255,255,20); color: #e8e6e1; }
QToolButton#iconBtn[on="true"] { color: #e8a33d; }
QToolButton#closeBtn {
    background: transparent; border: none; border-radius: 6px; color: #7d7a72; font: 12px "%CN%";
}
QToolButton#closeBtn:hover { background: #c42b1c; color: #fff; }
QToolButton#todayBtn {
    background: transparent; border: 1px solid rgba(232,163,61,110); border-radius: 6px;
    color: #e8a33d; font: 600 11px "%CN%"; padding: 0 10px;
}
QToolButton#todayBtn:hover { background: rgba(232,163,61,30); }
QFrame#clockBar { background: #e8a33d; border: none; border-radius: 1.5px; margin: 5px 0px; }
QLabel#clockBig { color: #f0ede6; font: 700 40px "%NUM%"; }
QLabel#clockSec { color: #f0ede6; font: 700 16px "%NUM%"; padding-bottom: 5px; }
QLabel#calSub { color: #6d6a62; font: 10.5px "%CN%"; }
QLabel#calSub[accent="true"] { color: #e8a33d; }
QLabel#weekLabel { color: #6d6a62; font: 600 10px "%CN%"; }
QFrame#dayCell { border-radius: 10px; background: transparent; }
QFrame#dayCell:hover { background: rgba(255,255,255,14); }
QLabel#dayNum { color: #e8e6e1; font: 600 20px "%NUM%"; background: transparent; border-radius: 15px; }
QFrame#dayCell[dim="true"] QLabel#dayNum { color: #4c4a45; }
QFrame#dayCell[we="true"] QLabel#dayNum { color: #8f8b81; }
QFrame#dayCell[dim="true"][we="true"] QLabel#dayNum { color: #454340; }
QFrame#dayCell[today="true"] QLabel#dayNum { background: #e8a33d; color: #1a1610; font-weight: 700; }
QLabel#daySub { color: #6d6a62; font: 9px "%CN%"; }
QLabel#daySub[fest="true"] { color: #e8a33d; }
QLabel#badge { border-radius: 3px; }
QLabel#badge[kind="off"] { background: #e05252; }
QLabel#badge[kind="work"] { background: #6d6a62; }
QFrame#todoPane { border-left: 1px solid rgba(255,255,255,18); }
QLabel#todoTitle { color: #f0ede6; font: 600 14px "%CN%"; }
QLabel#todoCount { color: #e8a33d; font: 600 11px "%NUM%"; }
QListWidget#todoList { background: transparent; border: none; outline: none; }
QFrame#todoRow { background: transparent; border-radius: 9px; }
QFrame#todoRow:hover { background: rgba(255,255,255,12); }
QToolButton#todoCheck {
    background: transparent; border: 2px solid #6d6a62; border-radius: 6px;
    color: transparent; font: 700 10px "%CN%";
}
QFrame#todoRow:hover QToolButton#todoCheck { border-color: #e8a33d; }
QToolButton#todoCheck:checked { background: #e8a33d; border-color: #e8a33d; color: #1a1610; }
QLabel#todoText { color: #e8e6e1; font: 13px "%CN%"; background: transparent; }
QFrame#todoRow[done="true"] QLabel#todoText { color: #57554f; }
QToolButton#addHint {
    background: transparent; border: 1px dashed rgba(255,255,255,40); border-radius: 9px;
    color: #6d6a62; font: 12px "%CN%"; padding: 7px;
}
QToolButton#addHint:hover { border-color: rgba(232,163,61,130); color: #e8a33d; }
QLineEdit#todoEdit {
    background: rgba(255,255,255,24); border: 1.5px solid rgba(232,163,61,160); border-radius: 9px;
    color: #f0ede6; font: 14px "%CN%"; padding: 8px 12px; selection-background-color: rgba(232,163,61,90);
}
QMenu {
    background: #23252d; color: #e8e6e1; border: 1px solid rgba(255,255,255,30);
    border-radius: 8px; padding: 5px; font: 12px "%CN%";
}
QMenu::item { padding: 6px 22px; border-radius: 5px; }
QMenu::item:selected { background: rgba(232,163,61,55); }
QMenu::separator { height: 1px; background: rgba(255,255,255,20); margin: 4px 8px; }
/* ---- 设置窗口 ---- */
QDialog#settingsDlg { background: #1b1d24; }
QWidget#settingsPanel {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1e2028, stop:1 #15181d);
    border: 1px solid rgba(255,255,255,22); border-radius: 14px;
}
QLabel#setTitle { color: #f0ede6; font: 600 13px "%CN%"; }
QLabel#setLabel { color: #6d6a62; font: 12px "%CN%"; }
QFrame#setSep { background: rgba(255,255,255,16); border: none; margin: 2px 0px; }
QWidget#settingsPanel QRadioButton, QWidget#settingsPanel QCheckBox {
    color: #e8e6e1; font: 12.5px "%CN%"; spacing: 6px; background: transparent;
}
QWidget#settingsPanel QRadioButton::indicator {
    width: 13px; height: 13px; border-radius: 8px;
    border: 1.5px solid #6d6a62; background: transparent;
}
QWidget#settingsPanel QCheckBox::indicator {
    width: 13px; height: 13px; border-radius: 4px;
    border: 1.5px solid #6d6a62; background: transparent;
}
QWidget#settingsPanel QRadioButton::indicator:hover, QWidget#settingsPanel QCheckBox::indicator:hover {
    border-color: #e8a33d;
}
QWidget#settingsPanel QRadioButton::indicator:checked, QWidget#settingsPanel QCheckBox::indicator:checked {
    background: #e8a33d; border-color: #e8a33d;
}
QWidget#timeField {
    background: rgba(255,255,255,10); border: 1px solid rgba(255,255,255,30); border-radius: 8px;
}
QWidget#timeField QTimeEdit {
    background: transparent; border: none; color: #f0ede6; font: 600 13px "%NUM%";
    padding: 3px 0px 3px 8px; selection-background-color: rgba(232,163,61,90);
}
QToolButton#timeStep {
    background: transparent; border: none; border-radius: 3px;
    color: #6d6a62; font: 7px "%CN%"; padding: 0px;
}
QToolButton#timeStep:hover { background: rgba(255,255,255,16); color: #e8a33d; }
QPushButton#setBtn {
    background: rgba(255,255,255,8); border: 1px solid rgba(255,255,255,28); border-radius: 8px;
    color: #e8e6e1; font: 12px "%CN%"; padding: 6px 12px;
}
QPushButton#setBtn:hover { border-color: rgba(232,163,61,130); color: #e8a33d; }
QPushButton#setBtn:pressed { background: rgba(232,163,61,30); }
QLabel#todoDue { color: #a39e93; font: 10px "%NUM%"; background: transparent; letter-spacing: 0.5px; }
QLabel#todoDue[late="true"] { color: #e06666; }
QToolButton#todoDateBtn {
    background: transparent; border: none; border-radius: 6px; color: #8d8a82; font: 11px "%CN%";
}
QToolButton#todoDateBtn:hover { background: rgba(255,255,255,20); color: #e8a33d; }
QFrame#duePopup { background: #23252d; border: 1px solid rgba(255,255,255,30); border-radius: 10px; }
QCalendarWidget QWidget#qt_calendar_navigationbar { background: #23252d; }
QCalendarWidget QWidget#qt_calendar_calendarview { background: #23252d; alternate-background-color: #23252d; }
QCalendarWidget QTableView { background: #23252d; }
QCalendarWidget QAbstractItemView:enabled {
    color: #e8e6e1; background: #23252d; font: 12px "%NUM%"; outline: none;
    selection-background-color: #e8a33d; selection-color: #1a1610;
}
QCalendarWidget QToolButton { color: #e8e6e1; background: transparent; border: none; font: 600 12px "%CN%"; }
QCalendarWidget QToolButton#qt_calendar_prevmonth, QCalendarWidget QToolButton#qt_calendar_nextmonth {
    font: 700 15px "%NUM%"; padding: 0 8px;
}
QCalendarWidget QToolButton::menu-indicator { image: none; width: 0; }
QCalendarWidget QSpinBox {
    color: #e8e6e1; background: transparent; font: 12px "%NUM%";
    selection-background-color: rgba(232,163,61,90);
}
QCalendarWidget QHeaderView::section { background: #23252d; color: #6d6a62; border: none; font: 10px "%NUM%"; }
""",
}

MICA = {
    'name': '浅色',
    'count_fmt': '{:d} 项未完成',
    'week': ['周一', '周二', '周三', '周四', '周五', '周六', '周日'],
    'qss': COMMON.replace('%TOOLTIP%', '#1b1b1f').replace('%SCROLL%', 'rgba(0,0,0,50)') + """
QWidget#panelRoot { background: #f7f8fa; }
QWidget#panel {
    background: #f7f8fa;
    border: 1px solid rgba(0,0,0,26);
    border-radius: 12px;
}
QFrame#tabBox { background: rgba(0,0,0,14); border-radius: 8px; }
QToolButton#tab {
    background: transparent; border: none; border-radius: 6px;
    color: #5b5b60; font: 600 12px "%CN%"; padding: 5px 16px;
}
QToolButton#tab[active="true"] { background: #ffffff; color: #1b1b1f; border: 1px solid rgba(0,0,0,10); }
QToolButton#iconBtn {
    background: transparent; border: none; border-radius: 6px; color: #5b5b60; font: 12px "%CN%";
}
QToolButton#iconBtn:hover { background: rgba(0,0,0,16); }
QToolButton#iconBtn[on="true"] { color: #0067c0; }
QToolButton#closeBtn {
    background: transparent; border: none; border-radius: 6px; color: #5b5b60; font: 12px "%CN%";
}
QToolButton#closeBtn:hover { background: #c42b1c; color: #fff; }
QToolButton#todayBtn {
    background: transparent; border: none; border-radius: 6px; color: #0067c0;
    font: 600 11px "%CN%"; padding: 0 8px;
}
QToolButton#todayBtn:hover { background: rgba(0,103,192,26); }
QFrame#clockBar { background: #0067c0; border: none; border-radius: 1.5px; margin: 5px 0px; }
QLabel#clockBig { color: #1b1b1f; font: 700 38px "%NUM%"; }
QLabel#clockSec { color: #1b1b1f; font: 700 15px "%NUM%"; padding-bottom: 5px; }
QLabel#calSub { color: #8a8a90; font: 10.5px "%CN%"; }
QLabel#calSub[accent="true"] { color: #0067c0; }
QLabel#weekLabel { color: #8a8a90; font: 600 10px "%CN%"; }
QLabel#weekLabel[we="true"] { color: #c94f4f; }
QFrame#dayCell { border-radius: 8px; background: transparent; }
QFrame#dayCell:hover { background: rgba(0,0,0,13); }
QLabel#dayNum { color: #1b1b1f; font: 600 20px "%NUM%"; background: transparent; border-radius: 15px; }
QFrame#dayCell[dim="true"] QLabel#dayNum { color: #b4b4ba; }
QFrame#dayCell[we="true"] QLabel#dayNum { color: #c94f4f; }
QFrame#dayCell[dim="true"][we="true"] QLabel#dayNum { color: #dcb0b0; }
QFrame#dayCell[today="true"] QLabel#dayNum { background: #0067c0; color: #ffffff; font-weight: 700; }
QLabel#daySub { color: #9a9aa0; font: 9px "%CN%"; }
QLabel#daySub[fest="true"] { color: #0067c0; font-weight: 600; }
QLabel#badge { border-radius: 3px; }
QLabel#badge[kind="off"] { background: #c42b1c; }
QLabel#badge[kind="work"] { background: #a9a9af; }
QFrame#todoPane { border-left: 1px solid rgba(0,0,0,16); background: #f0f1f4; }
QLabel#todoTitle { color: #1b1b1f; font: 600 14px "%CN%"; }
QLabel#todoCount { color: #8a8a90; font: 11px "%CN%"; }
QListWidget#todoList { background: transparent; border: none; outline: none; }
QFrame#todoRow { background: transparent; border-radius: 8px; }
QFrame#todoRow:hover { background: rgba(0,0,0,11); }
QToolButton#todoCheck {
    background: transparent; border: 2px solid #9a9aa0; border-radius: 9px;
    color: transparent; font: 700 10px "%CN%";
}
QFrame#todoRow:hover QToolButton#todoCheck { border-color: #0067c0; }
QToolButton#todoCheck:checked { background: #0067c0; border-color: #0067c0; color: #ffffff; }
QLabel#todoText { color: #1b1b1f; font: 13px "%CN%"; background: transparent; }
QFrame#todoRow[done="true"] QLabel#todoText { color: #a8a8ae; }
QToolButton#addHint {
    background: transparent; border: 1px dashed rgba(0,0,0,46); border-radius: 8px;
    color: #8a8a90; font: 12px "%CN%"; padding: 7px;
}
QToolButton#addHint:hover { border-color: #0067c0; color: #0067c0; background: rgba(0,103,192,13); }
QLineEdit#todoEdit {
    background: #ffffff; border: 1px solid #0067c0; border-radius: 8px;
    color: #1b1b1f; font: 14px "%CN%"; padding: 8px 12px; selection-background-color: rgba(0,103,192,60);
}
QMenu {
    background: rgba(252,252,253,248); color: #1b1b1f; border: 1px solid rgba(0,0,0,26);
    border-radius: 8px; padding: 5px; font: 12px "%CN%";
}
QMenu::item { padding: 6px 22px; border-radius: 5px; }
QMenu::item:selected { background: rgba(0,103,192,26); }
QMenu::separator { height: 1px; background: rgba(0,0,0,16); margin: 4px 8px; }
/* ---- 设置窗口 ---- */
QDialog#settingsDlg { background: #f7f8fa; }
QWidget#settingsPanel {
    background: #f7f8fa; border: 1px solid rgba(0,0,0,26); border-radius: 12px;
}
QLabel#setTitle { color: #1b1b1f; font: 600 13px "%CN%"; }
QLabel#setLabel { color: #8a8a90; font: 12px "%CN%"; }
QFrame#setSep { background: rgba(0,0,0,16); border: none; margin: 2px 0px; }
QWidget#settingsPanel QRadioButton, QWidget#settingsPanel QCheckBox {
    color: #1b1b1f; font: 12.5px "%CN%"; spacing: 6px; background: transparent;
}
QWidget#settingsPanel QRadioButton::indicator {
    width: 13px; height: 13px; border-radius: 8px;
    border: 1.5px solid #9a9aa0; background: #ffffff;
}
QWidget#settingsPanel QCheckBox::indicator {
    width: 13px; height: 13px; border-radius: 4px;
    border: 1.5px solid #9a9aa0; background: #ffffff;
}
QWidget#settingsPanel QRadioButton::indicator:hover, QWidget#settingsPanel QCheckBox::indicator:hover {
    border-color: #0067c0;
}
QWidget#settingsPanel QRadioButton::indicator:checked, QWidget#settingsPanel QCheckBox::indicator:checked {
    background: #0067c0; border-color: #0067c0;
}
QWidget#timeField {
    background: #ffffff; border: 1px solid rgba(0,0,0,30); border-radius: 8px;
}
QWidget#timeField QTimeEdit {
    background: transparent; border: none; color: #1b1b1f; font: 600 13px "%NUM%";
    padding: 3px 0px 3px 8px; selection-background-color: rgba(0,103,192,60);
}
QToolButton#timeStep {
    background: transparent; border: none; border-radius: 3px;
    color: #9a9aa0; font: 7px "%CN%"; padding: 0px;
}
QToolButton#timeStep:hover { background: rgba(0,0,0,14); color: #0067c0; }
QPushButton#setBtn {
    background: #ffffff; border: 1px solid rgba(0,0,0,30); border-radius: 8px;
    color: #1b1b1f; font: 12px "%CN%"; padding: 6px 12px;
}
QPushButton#setBtn:hover { border-color: #0067c0; color: #0067c0; background: rgba(0,103,192,13); }
QPushButton#setBtn:pressed { background: rgba(0,103,192,26); }
QLabel#todoDue {
    color: #0067c0; background: rgba(0,103,192,26); border-radius: 8px;
    font: 10px "%CN%"; padding: 2px 7px;
}
QLabel#todoDue[late="true"] { color: #c42b1c; background: #fde7e6; }
QToolButton#todoDateBtn {
    background: transparent; border: none; border-radius: 6px; color: #8a8a90; font: 11px "%CN%";
}
QToolButton#todoDateBtn:hover { background: rgba(0,103,192,13); color: #0067c0; }
QFrame#duePopup { background: #ffffff; border: 1px solid rgba(0,0,0,26); border-radius: 10px; }
QCalendarWidget QWidget#qt_calendar_navigationbar { background: #ffffff; }
QCalendarWidget QWidget#qt_calendar_calendarview { background: #ffffff; alternate-background-color: #ffffff; }
QCalendarWidget QTableView { background: #ffffff; }
QCalendarWidget QAbstractItemView:enabled {
    color: #1b1b1f; background: #ffffff; font: 12px "%CN%"; outline: none;
    selection-background-color: #0067c0; selection-color: #ffffff;
}
QCalendarWidget QToolButton { color: #1b1b1f; background: transparent; border: none; font: 600 12px "%CN%"; }
QCalendarWidget QToolButton#qt_calendar_prevmonth, QCalendarWidget QToolButton#qt_calendar_nextmonth {
    font: 700 15px "%NUM%"; padding: 0 8px;
}
QCalendarWidget QToolButton::menu-indicator { image: none; width: 0; }
QCalendarWidget QSpinBox { color: #1b1b1f; background: transparent; font: 12px "%NUM%"; }
QCalendarWidget QHeaderView::section { background: #ffffff; color: #8a8a90; border: none; font: 10px "%CN%"; }
""",
}

THEMES = {'nocturne': NOCTURNE, 'mica': MICA}
THEME_ORDER = ['nocturne', 'mica']  # 默认第一个（深色）


_PX_RE = None


def build_qss(key, cn_font, num_font, scale=1.0):
    """生成主题 QSS，并按 DPI 缩放比放大所有 px 尺寸（分数 px，渲染无拉伸、文字锐利）。"""
    global _PX_RE
    qss = THEMES[key]['qss'].replace('%CN%', cn_font).replace('%NUM%', num_font)
    if abs(scale - 1.0) > 1e-6:
        if _PX_RE is None:
            import re
            _PX_RE = re.compile(r'(\d+(?:\.\d+)?)px')
        qss = _PX_RE.sub(lambda m: '%gpx' % (round(float(m.group(1)) * scale, 2)), qss)
    return qss







