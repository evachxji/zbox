# -*- coding: utf-8 -*-
"""诊断埋点：顶部栏滑动 + 悬浮事件写调试日志。"""
import io
with io.open('app.py', 'r', encoding='utf-8') as f:
    src = f.read()

def rep(old, new):
    global src
    assert src.count(old) == 1, 'not found: %r' % old[:50]
    src = src.replace(old, new)

rep('''    def enterEvent(self, e):
        self._slide_titlebar(True)
        super(FloatingPanel, self).enterEvent(e)''',
'''    def enterEvent(self, e):
        _dbg('enterEvent')
        self._slide_titlebar(True)
        super(FloatingPanel, self).enterEvent(e)''')

rep('''    def _slide_titlebar(self, on):
        """栏窗高 0↔H 动画（从当前高度续滑，中途反向不打断）；只改栏窗几何，主窗口不动。"""
        if on and not self.isVisible():
            return   # 面板已收起就不再弹出栏窗（面板隐藏后光标划过原位置也会触发栏窗 Enter）''',
'''    def _slide_titlebar(self, on):
        """栏窗高 0↔H 动画（从当前高度续滑，中途反向不打断）；只改栏窗几何，主窗口不动。"""
        _dbg('slide_titlebar on=%s panelVis=%s tbVis=%s' % (on, self.isVisible(), self.titlebar.isVisible()))
        if on and not self.isVisible():
            return   # 面板已收起就不再弹出栏窗（面板隐藏后光标划过原位置也会触发栏窗 Enter）''')

with io.open('app.py', 'w', encoding='utf-8', newline='') as f:
    f.write(src)
print('ok')
