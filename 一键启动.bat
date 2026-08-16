@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 蛊箓 · 一键启动

echo ============================================
echo        蛊箓 · 蛊真人维基百科
echo        一键启动
echo ============================================
echo.

set "PYCMD="
where python >nul 2>nul && set "PYCMD=python"
if not defined PYCMD ( where py >nul 2>nul && set "PYCMD=py -3" )
if not defined PYCMD (
    echo [提示] 没找到 Python，请先安装（网址即将自动打开）：
    echo   https://www.python.org/downloads/
    echo 安装时务必勾选 Add Python to PATH，装完重新双击本文件。
    echo.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 首次运行：正在准备环境（约 1 分钟）...
    %PYCMD% -m venv .venv
    if errorlevel 1 ( echo 环境准备失败，请截图给开发者。 & pause & exit /b 1 )
)

if not exist ".venv\.deps_ok" (
    echo [2/3] 首次运行：正在安装依赖（需联网，约 2 分钟）...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
    if errorlevel 1 ( echo 依赖安装失败，请检查网络后重试。 & pause & exit /b 1 )
    echo ok> ".venv\.deps_ok"
)

echo [3/3] 正在启动服务...
set "PORT=8000"
netstat -ano | findstr /r ":8000 " | findstr "LISTENING" >nul 2>nul
if errorlevel 1 goto port_ok
set "PORT=8001"
netstat -ano | findstr /r ":8001 " | findstr "LISTENING" >nul 2>nul
if errorlevel 1 goto port_ok
set "PORT=8002"
netstat -ano | findstr /r ":8002 " | findstr "LISTENING" >nul 2>nul
if errorlevel 1 goto port_ok
set "PORT=8003"
:port_ok
echo.
echo 正在打开浏览器：http://127.0.0.1:%PORT%
echo 若浏览器提示无法连接，请等 5 秒后按 F5 刷新
echo 关闭本窗口 = 停止服务
echo.
start "" "http://127.0.0.1:%PORT%"
".venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port %PORT%
pause