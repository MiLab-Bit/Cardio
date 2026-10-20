# DEPLOY · 部署、验收与回滚（Cardio）

## 1. 本仓库的运行面
```
/opt/cardio  →  systemd：cardio-api（API）/ cardio-worker  →  127.0.0.1:8010
健康端点：/health
本机入口链路：Cloudflare Tunnel（cloudflared）→ Nginx → 本地端口
主机：阿里云 ECS cn-heyuan · ecs.u1-c1m2.large（2C4G）
```
**同一台机器上还跑着 lifetrip / redtrip / bizatlas / cardio / openclaw / glm-relay**：
部署本仓库时不要顺手动别的服务，也不要重启不属于本仓库的单元。

## 2. 部署前（只读自检）
```bash
APP_DIR=/opt/cardio bash scripts/deploy.sh --detect
```
它会打印：认到的 systemd 单元（并校验该单元确实指向 `/opt/cardio`）、端口、健康端点、当前版本、环境变量键名（值隐藏）。
识别不到就不会往下走——这是护栏，不是报错。

## 3. 部署
```bash
# 先 staging（如果该仓库有 staging 环境），再生产
APP_DIR=/opt/cardio TARGET_ENV=production bash scripts/deploy.sh <tag>
```
脚本行为：`git fetch --tags` → `checkout --force <ref>` → **校验 HEAD 与目标一致** → 重启 systemd 单元 →
轮询健康端点（最多约 60 秒）→ 失败则自动回退到上一个 tag。
可选：`POST_DEPLOY_CMD`（后置校验，非 0 触发回退）、`ISOCHRONE_PROBE`、`ROLLBACK_TO`。

**坑（实测过）**：脚本的 `APP_DIR` 默认值是 `/opt/lifetrip`。
不显式给 `APP_DIR` 就调用，会有把「本仓库的部署」打到 lifetrip 生产服务上的风险。
脚本已加护栏（`SERVICE` 与 `APP_DIR` 不一致时拒绝执行），但**请一律写成上面的完整命令**。

## 4. 验收清单
- [ ] `bash scripts/preflight.sh` 返回 0
- [ ] `curl -fsS http://127.0.0.1:8010/health` 返回 200
- [ ] `git -C /opt/cardio rev-parse HEAD` 与目标 tag 指向的 commit 一致
- [ ] 关键业务接口抽一条真实请求，返回非 5xx 且字段有值
- [ ] 机器上与本仓库无关的服务未受影响（`systemctl is-active` 抽查）

## 5. 回滚
```bash
git tag -l | sort -V | tail -3
APP_DIR=/opt/cardio TARGET_ENV=production bash scripts/deploy.sh <上一个 tag>
```
- 回滚后重跑第 4 节。
- 目标：≤ 30 分钟。LifeTrip 在 staging 上实测单次回滚 **8 秒**（见 `milab-release` 的演练记录）。
- 在 release notes 里记一句回滚原因。

## 6. 已知风险
- 内存：整机 3.6G，swap 常用 1.2G 上下，OpenClaw RSS 1.2~1.4G。发布时不要同时做其他维护动作。
- 端口/服务识别：本机多个仓库目录名互为前缀（`/opt/lifetrip` 与 `/opt/lifetrip-staging`），
  永远用 `APP_DIR=` 显式指定。
