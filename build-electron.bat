@echo off
REM Byou Electron 打包脚本（在网络稳定时运行）
REM 用法：双击运行，或命令行：build-electron.bat

setlocal EnableDelayedExpansion

set PROJECT_DIR=%~dp0
set FRONTEND_DIR=%PROJECT_DIR%frontend

echo ================================================
echo  Byou Electron 桌面版打包脚本
echo ================================================
echo.

REM ── 1. 检查 Node.js ─────────────────────────────
where node >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Node.js，请先安装 Node.js 18+
    pause
    exit /b 1
)
echo [1/6] Node.js 已安装：%NODE_PATH%
node --version

REM ── 2. 安装前端依赖 ─────────────────────────
echo.
echo [2/6] 安装前端依赖…
cd /d "%FRONTEND_DIR%"
call npm install
if errorlevel 1 (
    echo [错误] npm install 失败，请检查网络
    pause
    exit /b 1
)

REM ── 3. 构建前端 ─────────────────────────────
echo.
echo [3/6] 构建前端生产版本…
call npm run build
if errorlevel 1 (
    echo [错误] 前端构建失败
    pause
    exit /b 1
)

REM ── 4. 安装 Electron（如未安装）────────────
echo.
echo [4/6] 检查 Electron…
call npm list electron >nul 2>&1
if errorlevel 1 (
    echo 安装 Electron（可能较慢，请耐心等待）…
    call npm install electron electron-builder --save-dev
)

REM ── 5. 打包 Windows 安装程序 ───────────────
echo.
echo [5/6] 打包 Windows 桌面版（首次需要下载 Electron 缓存）…
call npm run dist:win
if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

REM ── 6. 完成 ─────────────────────────────────
echo.
echo ================================================
echo  打包完成！
echo  安装程序位于：
echo  %FRONTEND_DIR%dist-electron\
echo ================================================
echo.
pause
