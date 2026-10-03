@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
title 停止 Zbox 面板

echo.
echo   正在停止 Zbox 面板 ...
echo.

rem ---- 优先礼貌退出：--quit 经 IPC 通知运行中的实例（走正常清理：移除桌面右键菜单注入、格子收尾）----
set "PYW=pythonw"
where pythonw.exe >nul 2>nul
if errorlevel 1 set "PYW=pyw"
%PYW% "%~dp0main.pyw" --quit >nul 2>nul
ping -n 3 127.0.0.1 >nul

rem ---- 兜底：仍有残留进程（卡死时 --quit 可能等不到响应）则强制结束 ----
powershell -NoProfile -Command " $k = $false; Get-WmiObject Win32_Process | Where-Object { ($_.Name -match '^(pythonw?|zbox)\.exe$') -and ($_.CommandLine -match 'main\.pyw|zbox\.exe') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $k = $true }; if ($k) { exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo   [完成] 已停止（或本就没有运行中的实例）。
) else (
    echo   [完成] 已强制结束残留进程。
    echo          注意：强制结束不会清理桌面右键菜单注入，下次启动时会自动清掉。
)
echo.
ping -n 3 127.0.0.1 >nul
exit /b 0