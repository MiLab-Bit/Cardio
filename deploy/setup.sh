#!/usr/bin/env bash
# 在 ECS 上、代码已放到 /opt/cardio 后执行：安装依赖 + 注册 systemd + 检查
set -e
cd /opt/cardio

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

cp deploy/cardio.service /etc/systemd/system/cardio.service
systemctl daemon-reload
systemctl enable cardio
systemctl restart cardio
sleep 2
systemctl status cardio --no-pager || true

echo "---- health check ----"
curl -fsS --max-time 10 http://127.0.0.1:8000/health || echo "WARN: health check failed"

echo ""
echo "下一步（需人工/运维执行一次）："
echo "1) 把 deploy/cardio.nginx.conf 的内容并入 abc-ai.cn 的 server 块"
echo "2) nginx -t && systemctl reload nginx"
echo "3) 前端设置里确认后端地址为 https://www.abc-ai.cn/cardio"
