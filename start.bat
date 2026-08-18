@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title GZL - Gu Zhen Ren Wiki

type "%~dp0launcher_text\banner.txt"

set "RUN_PY="
if exist "runtime\python\python.exe" (
    set "RUN_PY=runtime\python\python.exe"
    type "%~dp0launcher_text\portable.txt"
    goto runtime_ready
)

set "PYCMD="
where python >nul 2>nul && set "PYCMD=python"
if not defined PYCMD ( where py >nul 2>nul && set "PYCMD=py -3" )
if not defined PYCMD (
    type "%~dp0launcher_text\no_python.txt"
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    type "%~dp0launcher_text\creating_environment.txt"
    %PYCMD% -m venv .venv
    if errorlevel 1 ( type "%~dp0launcher_text\environment_failed.txt" & pause & exit /b 1 )
)

if not exist ".venv\.deps_ok" (
    type "%~dp0launcher_text\installing_dependencies.txt"
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
    if errorlevel 1 ( type "%~dp0launcher_text\dependencies_failed.txt" & pause & exit /b 1 )
    echo ok> ".venv\.deps_ok"
)
set "RUN_PY=.venv\Scripts\python.exe"

:runtime_ready
type "%~dp0launcher_text\starting.txt"
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

REM Start Python directly so no nested command interpreter is created.
start "" /b "%RUN_PY%" -m uvicorn app.main:app --app-dir "%CD%" --host 127.0.0.1 --port %PORT% > "service.log" 2>&1

REM Check once per second for up to 90 seconds.
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
type "%~dp0launcher_text\ready.txt"
echo http://127.0.0.1:%PORT%
type "%~dp0launcher_text\keep_open.txt"
start "" "http://127.0.0.1:%PORT%"
pause
exit /b 0

:port_timeout
echo.
type "%~dp0launcher_text\startup_timeout.txt"
pause
exit /b 1
