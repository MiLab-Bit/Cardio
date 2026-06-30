#!/usr/bin/env python3
"""
Byou 桌面版启动器
- 自动找可用端口启动前端服务器
- 用 Edge App 模式打开（无地址栏，像桌面应用）
"""
import os
import sys
import time
import json
import subprocess
import webbrowser
import urllib.request
import urllib.error
import http.server
import socketserver
import threading
from functools import partial

# ── 配置 ────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR  = SCRIPT_DIR
BACKEND_PORT = 8000
BACKEND_URL  = f'http://127.0.0.1:{BACKEND_PORT}'
FRONTEND_DIR = os.path.join(SCRIPT_DIR, 'frontend', 'dist')
# ─────────────────────────────────────────────────────────

def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)

def is_backend_running():
    try:
        with urllib.request.urlopen(f'{BACKEND_URL}/health', timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False

def find_free_port():
    """让系统分配一个可用端口"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def start_frontend_server(port):
    os.chdir(FRONTEND_DIR)
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=FRONTEND_DIR)
    httpd = socketserver.TCPServer(('127.0.0.1', port), handler)
    log(f'前端服务器已启动：http://127.0.0.1:{port}')
    httpd.serve_forever()

def open_edge_app(url):
    """用 Edge App 模式打开（无地址栏，像桌面应用）"""
    try:
        # 先尝试 msedge
        subprocess.Popen(f'msedge --app="{url}" --window-size=1400,900', shell=True)
        log(f'已用 Edge App 模式打开（无地址栏，像桌面应用）')
        return True
    except Exception as e:
        pass
    try:
        # 备选：用默认浏览器
        webbrowser.open(url)
        log(f'已用默认浏览器打开')
        return True
    except Exception as e:
        log(f'打开浏览器失败：{e}')
        return False

def main():
    log('=== Byou 桌面版启动器 ===')

    # 1. 检查前端构建
    if not os.path.exists(os.path.join(FRONTEND_DIR, 'index.html')):
        log('错误：未找到前端构建文件')
        log('请先运行：cd frontend && npm run build')
        input('按 Enter 退出...')
        sys.exit(1)

    # 2. 启动后端（如果未运行）
    backend_proc = None
    if not is_backend_running():
        log('启动后端...')
        python = sys.executable
        backend_proc = subprocess.Popen(
            [python, '-m', 'uvicorn', 'byou.api:app',
             '--host', '127.0.0.1', '--port', str(BACKEND_PORT)],
            cwd=BACKEND_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            if is_backend_running():
                log(f'后端已启动：{BACKEND_URL}')
                break
            time.sleep(1)
        else:
            log('后端启动超时！')
            input('按 Enter 退出...')
            sys.exit(1)
    else:
        log(f'后端已在运行：{BACKEND_URL}')

    # 3. 找可用端口，启动前端服务器
    frontend_port = find_free_port()
    frontend_thread = threading.Thread(
        target=start_frontend_server,
        args=(frontend_port,),
        daemon=True
    )
    frontend_thread.start()
    time.sleep(1)

    # 4. 用 Edge App 模式打开
    frontend_url = f'http://127.0.0.1:{frontend_port}'
    log(f'正在打开应用窗口 → {frontend_url}')
    open_edge_app(frontend_url)

    log('Byou 桌面版已启动！')
    log(f'  前端：{frontend_url}')
    log(f'  后端：{BACKEND_URL}')
    log('按 Ctrl+C 停止前端服务器（后端会继续运行）...')

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log('正在退出...')
        if backend_proc:
            log('正在停止后端...')
            backend_proc.terminate()
            backend_proc.wait()
        log('已退出。')

if __name__ == '__main__':
    import socket
    main()
