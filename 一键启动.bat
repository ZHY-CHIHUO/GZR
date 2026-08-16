@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 蛊箓 · 一键启动

echo ============================================
echo        蛊箓 · 蛊真人维基百科
echo        一键启动（首次约需 3 分钟）
echo ============================================
echo.

REM ---------- 1. 检查是否安装了 Python ----------
set "PYCMD="
where python >nul 2>nul && set "PYCMD=python"
if not defined PYCMD ( where py >nul 2>nul && set "PYCMD=py -3" )
if not defined PYCMD (
    echo [提示] 还没检测到 Python。
    echo 请先免费安装 Python（网址即将自动打开）：
    echo   https://www.python.org/downloads/
    echo 安装时【务必勾选】最下方的 "Add Python to PATH"
    echo 装好后重新双击本文件即可。
    echo.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

REM ---------- 2. 第一次运行：创建运行环境 ----------
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 第一次运行，正在准备环境（约 1 分钟）...
    %PYCMD% -m venv .venv
    if errorlevel 1 (
        echo [错误] 环境准备失败，请把本窗口截图发给开发者。
        pause
        exit /b 1
    )
)

REM ---------- 3. 第一次运行：安装依赖 ----------
if not exist ".venv\.deps_ok" (
    echo [2/3] 第一次运行，正在安装依赖（需要联网，约 2 分钟）...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重试；仍不行请截图发给开发者。
        pause
        exit /b 1
    )
    echo ok> ".venv\.deps_ok"
)

REM ---------- 4. 启动服务并打开浏览器 ----------
echo [3/3] 正在启动服务...
echo   首次启动还会自动下载约 90MB 的检索模型（只需一次）
echo   看到 "Application startup complete" 就表示成功了
echo   浏览器没有自动打开的话，手动访问 http://127.0.0.1:8000
echo   关闭本窗口 = 停止服务
echo.
start "" "http://127.0.0.1:8000"
".venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port 8000
pause
