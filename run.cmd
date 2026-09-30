@echo off
chcp 936 >nul
setlocal
rem 调试日志：源码运行常开，写 %%TEMP%%\zviber_debug.log（app.py 的 _dbg 自带 2MB 轮转）。
rem 生产 exe 由 build.py 打包，不经过本脚本，不受此开关影响。
set ZVIBER_DEBUG=1
cd /d "%~dp0"
title Zviber 桌面日历面板

echo.
echo   Zviber 桌面日历面板
echo   ---------------------------------------------
echo.

rem ---- 定位 Python：优先 python.exe，退回到 py 启动器 ----
set "PY=python"
set "PYW=pythonw"
where python.exe >nul 2>nul
if errorlevel 1 (
    set "PY=py"
    set "PYW=pyw"
)

rem 真正执行一次，避开 Windows 应用商店的 python 占位程序
%PY% -c "import sys" >nul 2>nul
if errorlevel 1 goto :no_python

rem ---- 依赖：本项目唯一依赖 PyQt5 ----
%PY% -c "import PyQt5" >nul 2>nul
if errorlevel 1 goto :need_pyqt5

goto :launch

:need_pyqt5
echo   [提示] 未检测到 PyQt5（本项目唯一的依赖）。
choice /c YN /n /m "   现在自动安装吗？[Y/N] "
if errorlevel 2 goto :no_pyqt5
echo   正在安装 PyQt5，请稍候 ...
%PY% -m pip install PyQt5
if errorlevel 1 goto :pip_failed
echo   安装完成。
echo.
goto :launch

:no_pyqt5
echo.
echo   请先手动安装，再双击本脚本：
echo       %PY% -m pip install PyQt5
echo.
pause
exit /b 1

:pip_failed
echo.
echo   [错误] 安装失败，请检查网络后重试。
echo.
pause
exit /b 1

:no_python
echo   [错误] 未找到可用的 Python，请先安装 Python 3.8 或更高版本。
echo          下载：https://www.python.org/downloads/
echo          安装时务必勾选 "Add Python to PATH"。
echo.
pause
exit /b 1

:launch
start "" %PYW% "%~dp0main.pyw"
echo   [完成] 已启动。若面板本就在运行，本操作即显示 / 隐藏。
echo          找不到面板时，请看任务栏右下角的系统托盘图标。
echo.
echo   本窗口 3 秒后自动关闭 ...
ping -n 4 127.0.0.1 >nul
exit /b 0
