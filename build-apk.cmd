@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
title Zbox 打包 Android APK

echo.
echo   Zbox 一键打包 Android 传输 APK
echo   ---------------------------------------------
echo.

rem ---- 定位 Java：Gradle 需要 JDK 17 ----
where java.exe >nul 2>nul
if errorlevel 1 goto :no_java

if not exist "%~dp0android\gradlew.bat" goto :no_gradlew

rem ---- SDK 位置：android\local.properties 不入库，缺失时按默认路径生成 ----
if not exist "%~dp0android\local.properties" (
    if exist "%LOCALAPPDATA%\Android\Sdk" (
        echo sdk.dir=%LOCALAPPDATA%\Android\Sdk>"%~dp0android\local.properties"
    ) else (
        goto :no_sdk
    )
)

echo   正在打包，请稍候（首次构建需下载依赖，可能几分钟）...
echo.
call "%~dp0android\gradlew.bat" -p "%~dp0android" assembleDebug
if errorlevel 1 goto :build_failed

echo.
echo   [完成] APK 已生成：
echo       %~dp0android\app\build\outputs\apk\debug\app-debug.apk
echo.
echo   把这个 apk 发到手机上点开即可安装（需允许"安装未知来源应用"）。
echo.
pause
exit /b 0

:build_failed
echo.
echo   [错误] 打包失败，请查看上方 Gradle 的输出排查。
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
echo   [错误] 未找到 Android SDK，且默认路径不存在：
echo          %LOCALAPPDATA%\Android\Sdk
echo          请安装 Android SDK 后手工创建 android\local.properties，
echo          内容一行：sdk.dir=<你的 SDK 路径>
echo.
pause
exit /b 1
