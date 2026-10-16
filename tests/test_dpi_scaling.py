# -*- coding: utf-8 -*-
"""高 DPI 启动行为回归测试。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'main.pyw'


class HighDpiStartupTest(unittest.TestCase):
    def test_qt_coordinate_scaling_does_not_stack_with_manual_dpi_scaling(self):
        # main.pyw 的设计尺寸已经由 app.sc() 按系统 DPI 放大；Qt 不能再放大一次。
        probe = r'''
import json
import os
import runpy
runpy.run_path(%r, run_name='zbox_dpi_test')
from PySide6.QtWidgets import QApplication
qapp = QApplication([])
print(json.dumps({
    'qt_highdpi': os.environ.get('QT_ENABLE_HIGHDPI_SCALING'),
    'dpr': qapp.primaryScreen().devicePixelRatio(),
}))
''' % str(MAIN)
        env = os.environ.copy()
        env.pop('QT_ENABLE_HIGHDPI_SCALING', None)
        env.pop('QT_QPA_PLATFORM', None)
        result = subprocess.run(
            [sys.executable, '-c', probe], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(observed['qt_highdpi'], '0')
        self.assertEqual(observed['dpr'], 1.0)


if __name__ == '__main__':
    unittest.main()
