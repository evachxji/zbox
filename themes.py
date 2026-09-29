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
QFrame#titlebar { background: #1e2028; }
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
QLabel#clockBig { color: #f0ede6; font: 500 40px "%NUM%"; }
QLabel#calSub { color: #6d6a62; font: 10.5px "%CN%"; }
QLabel#calSub[accent="true"] { color: #e8a33d; }
QLabel#weekLabel { color: #6d6a62; font: 600 10px "%CN%"; }
QFrame#dayCell { border-radius: 10px; background: transparent; margin: 3px 0; }
QFrame#dayCell:hover { background: rgba(255,255,255,14); }
QLabel#dayNum { color: #e8e6e1; background: transparent; border-radius: 17px; }
QFrame#dayCell[dim="true"] QLabel#dayNum { color: #4c4a45; }
QFrame#dayCell[we="true"] QLabel#dayNum { color: #8f8b81; }
QFrame#dayCell[dim="true"][we="true"] QLabel#dayNum { color: #454340; }
QFrame#dayCell[sel="true"] { background: rgba(232,163,61,36); }
QFrame#dayCell[sel="true"] QLabel#dayNum { color: #e8a33d; }
QFrame#dayCell[today="true"] { background: #e8a33d; }
QFrame#dayCell[today="true"]:hover { background: #f2b45a; }
QFrame#dayCell[today="true"] QLabel#dayNum { color: #1a1610; font-weight: 700; }
QFrame#dayCell[today="true"] QLabel#daySub { color: rgba(26,22,16,190); }
QLabel#daySub { color: #6d6a62; font: 9px "%CN%"; }
QLabel#daySub[fest="true"] { color: #e8a33d; }
/* 节假日角标：贴格子右上角的圆角标签 —— 法定节假日「休」，调休上班日「班」。
   普通双休日不标；文字与配色都在这里给，app 只负责内容与摆位。 */
#badge { font: 700 8px "%CN%"; padding: 0 1px; border-radius: 3px; }
#badge[kind="off"] { color: #e05252; background: rgba(224,82,82,46); }
#badge[kind="work"] { color: #9a9aa0; background: rgba(255,255,255,26); }
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
QLabel#setUrl {
    color: #e8a33d; background: rgba(255,255,255,16); border-radius: 6px;
    font: 11px "%NUM%"; padding: 5px 8px;
}
QFrame#setSep { background: rgba(255,255,255,16); border: none; margin: 2px 0px; }
QWidget#settingsPanel QRadioButton, QWidget#settingsPanel QCheckBox {
    color: #e8e6e1; font: 12.5px "%CN%"; spacing: 6px; background: transparent;
}
QWidget#settingsPanel QRadioButton::indicator {
    width: 13px; height: 13px; border-radius: 7px;
    border: 1.5px solid #6d6a62; background: transparent;
}
QWidget#settingsPanel QCheckBox::indicator {
    width: 13px; height: 13px; border-radius: 4px;
    border: 1.5px solid #6d6a62; background: transparent;
}
QWidget#settingsPanel QRadioButton::indicator:hover, QWidget#settingsPanel QCheckBox::indicator:hover {
    border-color: #e8a33d;
}
QWidget#settingsPanel QRadioButton::indicator:checked {
    border-color: #e8a33d; image: url("%ICON_DIR%/dot_dark.png");
}
QWidget#settingsPanel QCheckBox::indicator:checked {
    background: #e8a33d; border-color: #e8a33d;
    image: url("%ICON_DIR%/tick_dark.png");
}
QWidget#timeField {
    background: rgba(255,255,255,10); border: 1px solid rgba(255,255,255,30); border-radius: 8px;
}
QWidget#timeField[hov="true"] { border-color: rgba(232,163,61,120); }
QWidget#timeField[focus="true"] { border-color: #e8a33d; background: rgba(232,163,61,16); }
QWidget#timeField QLineEdit {
    background: transparent; border: none; color: #f0ede6; font: 600 13px "%NUM%";
    padding: 4px 0px 4px 9px; selection-background-color: rgba(232,163,61,90);
}
QLineEdit#srcEdit {
    background: rgba(255,255,255,12); border: 1px solid rgba(255,255,255,28); border-radius: 7px;
    color: #cfccc4; font: 11px "%NUM%"; padding: 5px 8px; selection-background-color: rgba(232,163,61,90);
}
QLineEdit#srcEdit:focus { border-color: #e8a33d; color: #f0ede6; background: rgba(232,163,61,16); }
QToolButton#timeBtn { background: transparent; border: none; border-radius: 5px; }
QToolButton#timeBtn:hover { background: rgba(255,255,255,16); }
QFrame#timePopup { background: #23252d; border: 1px solid rgba(255,255,255,30); border-radius: 10px; }
QListWidget#timeCol {
    background: transparent; border: none; outline: none; padding: 0px 3px;
    color: #8d8a82; font: 600 12.5px "%NUM%";
}
QListWidget#timeCol[sep="true"] { border-left: 1px solid rgba(255,255,255,18); }
QListWidget#timeCol::item { height: 28px; border-radius: 6px; }
QListWidget#timeCol::item:hover { background: rgba(255,255,255,14); color: #e8e6e1; }
QListWidget#timeCol::item:selected { background: rgba(232,163,61,40); color: #f2b45a; }
QPushButton#setBtn {
    background: rgba(255,255,255,8); border: 1px solid rgba(255,255,255,28); border-radius: 8px;
    color: #e8e6e1; font: 12px "%CN%"; padding: 6px 12px;
}
QPushButton#setBtn:hover { border-color: rgba(232,163,61,130); color: #e8a33d; }
QPushButton#setBtn:pressed { background: rgba(232,163,61,30); }
QPushButton#setSave {
    background: #e8a33d; border: none; border-radius: 8px;
    color: #1a1610; font: 600 12px "%CN%"; padding: 6px 20px;
}
QPushButton#setSave:hover { background: #f2b45a; }
QPushButton#setSave:pressed { background: #d18f2e; }
/* 截止日期 tag（仿 Element 标签：圆角浅底 + 同色字） */
QLabel#todoDue {
    color: #a39e93; background: rgba(255,255,255,14); border-radius: 8px;
    font: 10px "%CN%"; padding: 2px 7px;
}
QLabel#todoDue[late="true"] { color: #e06666; background: rgba(224,102,102,30); }
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
QToolTip { background-color: #2a2d36; border: 1px solid rgba(255,255,255,40); padding: 4px 8px; }
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
QFrame#titlebar { background: #f7f8fa; }
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
QLabel#clockBig { color: #1b1b1f; font: 500 40px "%NUM%"; }
QLabel#calSub { color: #8a8a90; font: 10.5px "%CN%"; }
QLabel#calSub[accent="true"] { color: #0067c0; }
QLabel#weekLabel { color: #8a8a90; font: 600 10px "%CN%"; }
QLabel#weekLabel[we="true"] { color: #c94f4f; }
QFrame#dayCell { border-radius: 8px; background: transparent; margin: 3px 0; }
QFrame#dayCell:hover { background: rgba(0,0,0,13); }
QLabel#dayNum { color: #1b1b1f; background: transparent; border-radius: 17px; }
QFrame#dayCell[dim="true"] QLabel#dayNum { color: #b4b4ba; }
QFrame#dayCell[we="true"] QLabel#dayNum { color: #c94f4f; }
QFrame#dayCell[dim="true"][we="true"] QLabel#dayNum { color: #dcb0b0; }
QFrame#dayCell[sel="true"] { background: rgba(0,103,192,22); }
QFrame#dayCell[sel="true"] QLabel#dayNum { color: #0067c0; }
QFrame#dayCell[today="true"] { background: #0067c0; }
QFrame#dayCell[today="true"]:hover { background: #1a77cc; }
QFrame#dayCell[today="true"] QLabel#dayNum { color: #ffffff; font-weight: 700; }
QFrame#dayCell[today="true"] QLabel#daySub { color: rgba(255,255,255,210); }
QLabel#daySub { color: #9a9aa0; font: 9px "%CN%"; }
QLabel#daySub[fest="true"] { color: #0067c0; font-weight: 600; }
/* 节假日角标：贴格子右上角的圆角标签 —— 法定节假日「休」，调休上班日「班」。
   普通双休日不标；文字与配色都在这里给，app 只负责内容与摆位。 */
#badge { font: 700 8.5px "%CN%"; padding: 0 1px; border-radius: 3px; }
#badge[kind="off"] { color: #c42b1c; background: #fde7e6; }
#badge[kind="work"] { color: #77777d; background: rgba(0,0,0,20); }
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
QLabel#setUrl {
    color: #0067c0; background: rgba(0,0,0,6); border-radius: 6px;
    font: 11px "%NUM%"; padding: 5px 8px;
}
QFrame#setSep { background: rgba(0,0,0,16); border: none; margin: 2px 0px; }
QWidget#settingsPanel QRadioButton, QWidget#settingsPanel QCheckBox {
    color: #1b1b1f; font: 12.5px "%CN%"; spacing: 6px; background: transparent;
}
QWidget#settingsPanel QRadioButton::indicator {
    width: 13px; height: 13px; border-radius: 7px;
    border: 1.5px solid #9a9aa0; background: #ffffff;
}
QWidget#settingsPanel QCheckBox::indicator {
    width: 13px; height: 13px; border-radius: 4px;
    border: 1.5px solid #9a9aa0; background: #ffffff;
}
QWidget#settingsPanel QRadioButton::indicator:hover, QWidget#settingsPanel QCheckBox::indicator:hover {
    border-color: #0067c0;
}
QWidget#settingsPanel QRadioButton::indicator:checked {
    border-color: #0067c0; image: url("%ICON_DIR%/dot_light.png");
}
QWidget#settingsPanel QCheckBox::indicator:checked {
    background: #0067c0; border-color: #0067c0;
    image: url("%ICON_DIR%/tick_light.png");
}
QWidget#timeField {
    background: #ffffff; border: 1px solid rgba(0,0,0,30); border-radius: 8px;
}
QWidget#timeField[hov="true"] { border-color: rgba(0,103,192,140); }
QWidget#timeField[focus="true"] { border-color: #0067c0; background: rgba(0,103,192,10); }
QWidget#timeField QLineEdit {
    background: transparent; border: none; color: #1b1b1f; font: 600 13px "%NUM%";
    padding: 4px 0px 4px 9px; selection-background-color: rgba(0,103,192,60);
}
QLineEdit#srcEdit {
    background: #ffffff; border: 1px solid rgba(0,0,0,26); border-radius: 7px;
    color: #4a4a50; font: 11px "%NUM%"; padding: 5px 8px; selection-background-color: rgba(0,103,192,60);
}
QLineEdit#srcEdit:focus { border-color: #0067c0; color: #1b1b1f; background: rgba(0,103,192,10); }
QToolButton#timeBtn { background: transparent; border: none; border-radius: 5px; }
QToolButton#timeBtn:hover { background: rgba(0,0,0,12); }
QFrame#timePopup { background: #ffffff; border: 1px solid rgba(0,0,0,30); border-radius: 10px; }
QListWidget#timeCol {
    background: transparent; border: none; outline: none; padding: 0px 3px;
    color: #9a9aa0; font: 600 12.5px "%NUM%";
}
QListWidget#timeCol[sep="true"] { border-left: 1px solid rgba(0,0,0,20); }
QListWidget#timeCol::item { height: 28px; border-radius: 6px; }
QListWidget#timeCol::item:hover { background: rgba(0,0,0,10); color: #1b1b1f; }
QListWidget#timeCol::item:selected { background: rgba(0,103,192,26); color: #0067c0; }
QPushButton#setBtn {
    background: #ffffff; border: 1px solid rgba(0,0,0,30); border-radius: 8px;
    color: #1b1b1f; font: 12px "%CN%"; padding: 6px 12px;
}
QPushButton#setBtn:hover { border-color: #0067c0; color: #0067c0; background: rgba(0,103,192,13); }
QPushButton#setBtn:pressed { background: rgba(0,103,192,26); }
QPushButton#setSave {
    background: #0067c0; border: none; border-radius: 8px;
    color: #ffffff; font: 600 12px "%CN%"; padding: 6px 20px;
}
QPushButton#setSave:hover { background: #1a77cc; }
QPushButton#setSave:pressed { background: #0059a6; }
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
THEME_ORDER = ['nocturne', 'mica']  # 实际主题，默认第一个（深色）
AUTO = 'auto'  # 伪主题：跟随系统「应用模式」，由 app.resolve_theme() 解析成上面之一
THEME_CHOICES = THEME_ORDER + [AUTO]  # 设置窗口的主题选项顺序


_PX_RE = None


def build_qss(key, cn_font, num_font, scale=1.0, icon_dir=''):
    """生成主题 QSS，并按 DPI 缩放比放大所有 px 尺寸（分数 px，渲染无拉伸、文字锐利）。
    %ICON_DIR% 为 checkbox/radio 指示器图标目录（正斜杠路径，运行时由 app 生成）。"""
    global _PX_RE
    qss = THEMES[key]['qss'].replace('%CN%', cn_font).replace('%NUM%', num_font)
    qss = qss.replace('%ICON_DIR%', icon_dir)
    if abs(scale - 1.0) > 1e-6:
        if _PX_RE is None:
            import re
            _PX_RE = re.compile(r'(\d+(?:\.\d+)?)px')
        qss = _PX_RE.sub(lambda m: '%gpx' % (round(float(m.group(1)) * scale, 2)), qss)
    return qss












