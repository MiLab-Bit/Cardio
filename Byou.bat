@echo off
REM Byou 桌面版启动脚本
REM 用法：双击运行

setlocal EnableDelayedExpansion
set PROJECT_DIR=%~dp0
set BACKEND_PORT=8000
set FRONTEND_PORT=3001
set BACKEND_URL=http://127.0.0.1:%BACKEND_PORT%
set FRONTEND_URL=http://127.0.0.1:%FRONTEND_PORT%

echo ================================================
echo  Byou 桌面版启动中…
echo ================================================
echo.

REM ── 1. 检查 Python ─────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM ── 2. 检查前端构建是否存在 ──────────────────
if not exist "%PROJECT_DIR%frontend\dist\index.html" (
    echo [错误] 未找到前端构建文件
    echo 请先运行：cd frontend && npm run build
    pause
    exit /b 1
)

REM ── 3. 启动后端（如果未运行）──────────────
curl -s -o nul -w "%%{http_code}" %BACKEND_URL%/health 2>nul | findstr "200" >nul
if errorlevel 1 (
    echo [1/3] 正在启动后端…
    start "Byou Backend" cmd /c "cd /d "%PROJECT_DIR%" && python -m uvicorn byou.api:app --host 127.0.0.1 --port %BACKEND_PORT%"
    echo 等待后端启动…
    timeout /t 5 /nobreak > nul
) else (
    echo [1/3] 后端已在运行
)

REM ── 4. 启动前端静态服务器 ─────────────────
echo [2/3] 正在启动前端服务器（端口 %FRONTEND_PORT%）…
start "Byou Frontend" cmd /c "cd /d "%PROJECT_DIR%frontend\dist" && python -m http.server %FRONTEND_PORT% --bind 127.0.0.1"
timeout /t 2 /nobreak > nul

REM ── 5. 用 Edge App 模式打开（无地址栏，像桌面应用）──
echo [3/3] 正在打开应用窗口…
start msedge --app="%FRONTEND_URL%" --window-size=1400,900 --new-window
echo.
echo ================================================
echo  Byou 已启动！
echo  关闭此窗口不会停止后端/前端服务器。
echo  要停止服务，请关闭名为 "Byou Backend" 和 "Byou Frontend" 的命令行窗口。
echo ================================================
echo.
pause
