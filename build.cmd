@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
title Zviber 打包 exe 安装包

echo.
echo   Zviber 一键打包 exe 安装包
echo   ---------------------------------------------
echo.

rem ---- 定位 Python：优先 python.exe，退回到 py 启动器 ----
set "PY=python"
where python.exe >nul 2>nul
if errorlevel 1 set "PY=py"

rem 真正执行一次，避开 Windows 应用商店的 python 占位程序
%PY% -c "import sys" >nul 2>nul
if errorlevel 1 goto :no_python

if not exist "%~dp0build.py" goto :no_build

rem ---- 依赖：PyQt5（生成图标）+ PyInstaller（打包）----
%PY% -c "import PyQt5" >nul 2>nul
if errorlevel 1 goto :need_deps
%PY% -c "import PyInstaller" >nul 2>nul
if not errorlevel 1 goto :build

:need_deps
echo   [提示] 缺少打包依赖（PyQt5 / PyInstaller）。
choice /c YN /n /m "   现在自动安装吗？[Y/N] "
if errorlevel 2 goto :no_deps
echo   正在安装依赖，可能需要几分钟 ...
%PY% -m pip install PyQt5 pyinstaller
if errorlevel 1 goto :pip_failed
echo.

:build
echo   正在打包，请稍候（首次打包较慢）...
echo.
%PY% "%~dp0build.py"
if errorlevel 1 goto :build_failed

echo.
echo   [完成] 产物已生成：
echo       %~dp0dist\zviber-Setup-v*-x64.exe
echo.
echo   分发方式：把这个 exe 发给别人，双击即弹出安装向导，
echo   对方无需安装 Python。安装后是 onedir 目录，启动更快。
echo.
pause
exit /b 0

:build_failed
echo.
echo   [错误] 打包失败，请查看上方 PyInstaller 的输出排查。
echo.
pause
exit /b 1

:no_deps
echo.
echo   请先手动安装，再双击本脚本：
echo       %PY% -m pip install PyQt5 pyinstaller
echo.
pause
exit /b 1

:pip_failed
echo.
echo   [错误] 依赖安装失败，请检查网络后重试。
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

:no_build
echo   [错误] 未找到 build.py，无法打包。
echo.
pause
exit /b 1
