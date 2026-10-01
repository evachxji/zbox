@echo off
chcp 936 >nul
setlocal
rem 编译 zshell_host.exe（x64，/MT 静态 CRT，零外部依赖）。需要 MSVC Build Tools。
cd /d %~dp0

set VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe
if not exist "%VSWHERE%" (
    echo [错误] 未找到 vswhere，请先安装 Visual Studio Build Tools（含 C++ 工作负载）
    exit /b 1
)
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set VS=%%i
if not defined VS (
    echo [错误] 未找到带 C++ 工具的 Visual Studio 安装
    exit /b 1
)
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul

cl /nologo /O2 /MT /EHsc /utf-8 zshell.cpp /Fe:zshell_host.exe
if errorlevel 1 (
    echo [错误] 编译失败
    exit /b 1
)
rem 清理中间文件，只留 exe
del /q zshell.obj 2>nul
echo [完成] %~dp0zshell_host.exe
