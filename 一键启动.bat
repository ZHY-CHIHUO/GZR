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

echo [3/3] 正在启动服务，首次加载数据约需 5~15 秒，请稍候...
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

REM 后台启动服务，日志写到 service.log
start "" /b cmd /c "".venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port %PORT% > service.log 2>&1"

REM 每 1 秒检查一次，最多等 90 秒
set /a WAIT=0
:waitloop
ping -n 2 127.0.0.1 >nul
netstat -ano | findstr /r ":%PORT% " | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 goto port_ready
set /a WAIT+=1
if %WAIT% GEQ 90 goto port_timeout
goto waitloop

:port_ready
echo.
echo 服务已就绪，正在打开浏览器...
start "" "http://127.0.0.1:%PORT%"
echo 访问地址：http://127.0.0.1:%PORT%
echo 若浏览器没有弹出，请手动打开上面的地址
echo 关闭本窗口 = 停止服务
echo.
pause
exit /b 0

:port_timeout
echo.
echo [提示] 服务启动超时（90 秒），请查看同目录下的 service.log
pause
exit /b 1