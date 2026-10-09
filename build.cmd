@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
title Zbox 一键打包

echo.
echo   Zbox 一键打包
echo   ---------------------------------------------

rem ---- 定位 Python：优先 python.exe，退回到 py 启动器 ----
set "PY=python"
where python.exe >nul 2>nul
if errorlevel 1 set "PY=py"

rem 真正执行一次，避开 Windows 应用商店的 python 占位程序
%PY% -c "import sys" >nul 2>nul
if errorlevel 1 goto :no_python

rem ---- 版本号（version.py 是唯一来源） ----
for /f %%v in ('%PY% -c "from version import APP_VERSION; print(APP_VERSION)"') do set "VER=%%v"
echo   版本号：v%VER%
echo.

rem ---- 选择构建目标 ----
echo   请选择构建目标：
echo     1. Win端（EXE）
echo     2. 安卓端（APK）
echo     3. 鸿蒙端（HAP）
echo     4. Win端 + 安卓端
echo     5. Win端 + 鸿蒙端
echo     6. 安卓端 + 鸿蒙端
echo     7. Win端 + 安卓端 + 鸿蒙端（默认）
echo.
set /p "CHOICE=请输入 1-7 后回车 [7]: "
if "%CHOICE%"=="" set "CHOICE=7"
rem set /p 从管道读入会残留 \r；选项本来就是单个数字，只取首字符（交互输入无影响）
set "CHOICE=%CHOICE:~0,1%"
set "DO_PC="
set "DO_APK="
set "DO_HAP="
if "%CHOICE%"=="1" set "DO_PC=1"
if "%CHOICE%"=="2" set "DO_APK=1"
if "%CHOICE%"=="3" set "DO_HAP=1"
if "%CHOICE%"=="4" (set "DO_PC=1" & set "DO_APK=1")
if "%CHOICE%"=="5" (set "DO_PC=1" & set "DO_HAP=1")
if "%CHOICE%"=="6" (set "DO_APK=1" & set "DO_HAP=1")
if "%CHOICE%"=="7" (set "DO_PC=1" & set "DO_APK=1" & set "DO_HAP=1")
rem 七个分支都没命中 = 非法输入
if not defined DO_PC if not defined DO_APK if not defined DO_HAP goto :bad_choice
echo.

rem ============ Windows exe 安装包 ============
if not defined DO_PC goto :skip_pc
echo   [exe] Windows 安装包（首次打包较慢）...
%PY% -c "import PySide6" >nul 2>nul
if errorlevel 1 goto :need_deps
%PY% -c "import PyInstaller" >nul 2>nul
if not errorlevel 1 goto :pc_build

:need_deps
echo   [提示] 缺少打包依赖（PySide6 / PyInstaller）。
choice /c YN /n /m "   现在自动安装吗？[Y/N] "
if errorlevel 2 goto :no_deps
echo   正在安装依赖，可能需要几分钟 ...
%PY% -m pip install PySide6 pyinstaller
if errorlevel 1 goto :pip_failed
echo.

:pc_build
%PY% "%~dp0build.py"
if errorlevel 1 goto :pc_failed
echo.
:skip_pc

rem ============ Android APK ============
if not defined DO_APK goto :skip_apk
echo   [APK] Android 安装包 ...
where java.exe >nul 2>nul
if errorlevel 1 goto :no_java
if not exist "%~dp0android\gradlew.bat" goto :no_gradlew

rem SDK 路径只走 ANDROID_SDK_ROOT 环境变量（优先沿用已有值，否则从 local.properties
rem 提取，再否则用默认路径）：AGP 8.13 从 local.properties 读 sdk.dir 时会在
rem SdkLocator 校验处误报「文件名、目录名或卷标语法不正确」（2026-10 实测，同路径
rem 走环境变量即正常），所以构建期间把 local.properties 临时挪开、结束后还原。
set "LP=%~dp0android\local.properties"
set "LP_BAK=%~dp0android\local.properties.zbox-bak"
set "LP_MOVED="
if not defined ANDROID_SDK_ROOT (
    for /f %%v in ('%PY% -c "import re,os; p=r'android/local.properties'; m=re.search(r'(?m)^sdk\.dir=(.*)$', open(p).read()) if os.path.exists(p) else None; print(m.group(1).strip() if m else '')"') do set "ANDROID_SDK_ROOT=%%v"
)
if exist "%LP%" (
    move /y "%LP%" "%LP_BAK%" >nul
    set "LP_MOVED=1"
)
if not defined ANDROID_SDK_ROOT (
    if exist "%LOCALAPPDATA%\Android\Sdk" (
        set "ANDROID_SDK_ROOT=%LOCALAPPDATA%\Android\Sdk"
    ) else (
        if defined LP_MOVED move /y "%LP_BAK%" "%LP%" >nul
        goto :no_sdk
    )
)
call "%~dp0android\gradlew.bat" -p "%~dp0android" assembleDebug
set "APK_ERR=%ERRORLEVEL%"
if defined LP_MOVED move /y "%LP_BAK%" "%LP%" >nul
if not "%APK_ERR%"=="0" goto :apk_failed
echo.
:skip_apk

rem ============ 鸿蒙 HAP ============
if not defined DO_HAP goto :skip_hap
echo   [HAP] 鸿蒙安装包 ...
where devecocli.cmd >nul 2>nul
if errorlevel 1 goto :no_deveco
pushd "%~dp0harmony"
call devecocli.cmd build
if errorlevel 1 (popd & goto :hap_failed)
popd
echo.
:skip_hap

rem ============ 汇总产物（带版本号） ============
echo   正在汇总产物到 dist\release\ ...
if not exist "%~dp0dist\release" mkdir "%~dp0dist\release"
if defined DO_PC for %%f in ("%~dp0dist\zbox-Setup-v%VER%-*.exe") do copy /y "%%f" "%~dp0dist\release\" >nul
if defined DO_APK copy /y "%~dp0android\app\build\outputs\apk\debug\app-debug.apk" "%~dp0dist\release\zbox-Android-v%VER%.apk" >nul
if defined DO_HAP copy /y "%~dp0harmony\entry\build\default\outputs\default\entry-default-unsigned.hap" "%~dp0dist\release\zbox-HarmonyOS-v%VER%-unsigned.hap" >nul

echo.
echo   [完成] 本次产物（dist\release\）：
dir /b "%~dp0dist\release\"
echo.
echo   说明：exe 发给别人双击即装；apk 发手机点开安装；
echo         hap 是免签名调试包，只能装模拟器/开发者调试设备，
echo         分发真机需先签名或上架 AppGallery（见 harmony\README.md）。
echo.
pause
exit /b 0

:bad_choice
echo.
echo   [错误] 输入无效，请输入 1-7 的数字。
echo.
pause
exit /b 1

:pc_failed
echo.
echo   [错误] Windows 安装包打包失败，请查看上方 PyInstaller 的输出排查。
echo.
pause
exit /b 1

:apk_failed
echo.
echo   [错误] Android APK 打包失败，请查看上方 Gradle 的输出排查。
echo.
pause
exit /b 1

:hap_failed
echo.
echo   [错误] 鸿蒙 HAP 打包失败，请查看上方 hvigor 的输出排查。
echo          若报错与 SignHap / profile 有关：build-profile.json5 配了 release 签名，
echo          但 signing\ 下的证书材料不全（缺 .cer / .p7b，需从 AppGallery Connect 下载）。
echo          把材料补全，或把 signingConfig 改回空（免签名调试包）即可恢复构建。
echo.
pause
exit /b 1

:no_deps
echo.
echo   请先手动安装，再双击本脚本：
echo       %PY% -m pip install PySide6 pyinstaller
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
echo   [错误] 未找到可用的 Python，请先安装 Python 3.10 或更高版本。
echo          下载：https://www.python.org/downloads/
echo          安装时务必勾选 "Add Python to PATH"。
echo.
pause
exit /b 1

:no_java
echo   [错误] 未找到 Java。Android 打包需要 JDK 17，
echo          请先安装并加入 PATH（如 Temurin 17）。
echo.
pause
exit /b 1

:no_gradlew
echo   [错误] 未找到 android\gradlew.bat，Android 工程不完整。
echo.
pause
exit /b 1

:no_sdk
echo   [错误] 未找到 Android SDK。
echo          请安装 Android SDK，或把 ANDROID_SDK_ROOT 指向你的 SDK 路径。
echo.
pause
exit /b 1

:no_deveco
echo   [错误] 未找到 devecocli。鸿蒙打包需要 DevEco CLI：
echo          npm install -g @deveco/deveco-cli@stable
echo          （另需本机装有 DevEco Studio 作为工具链宿主）
echo.
pause
exit /b 1