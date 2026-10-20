# RELEASE · 发布流程与版本号方案（Cardio）

> 上游模板：`MiLab-Bit/milab-release`。**本文件是副本**——要改口径请改上游，再同步下来，避免两份说法不一致。

## 0. 本仓库现状（2026-10-12 实测）

| 项 | 值 |
|---|---|
| 代码目录 | `/opt/cardio` |
| systemd 单元 | cardio-api（API）/ cardio-worker |
| 端口 | `127.0.0.1:8010` |
| 健康端点 | `/health` |
| CI | `bash scripts/preflight.sh`（单一入口，已在仓库里） |
| 分支保护 | 已开（必需检查 `preflight`，strict=true，需 PR，禁 force push，enforce_admins=false） |
| tag ruleset | 已开（ruleset id 24902148 `protect-release-tags`） |
| 首个正式 tag | 无（尚未走第一次正式发布） |

## 1. 版本号方案
- 格式：`vYYYY.MM.<build>`，`build` 为该月内从 1 起的发布序号。例：`v2026.10.1`。
- tag **只增不删、不可移动**（由 tag ruleset 保护）。
- 线上跑的永远是某个 tag，不存在「线上是 main 的最新」。

## 2. 发布步骤
1. 在分支上完成改动 → 提 PR 到 `main`，CI 必须为绿。
2. 本地再跑一次门禁：`bash scripts/preflight.sh`
3. 合并 PR。
4. 打 tag 并推送（**只由人工执行**）：`git tag -a v2026.11.1 -m "Cardio v2026.11.1" && git push origin v2026.11.1`
5. 先部署到 staging 验收，再部署生产（命令见 `docs/DEPLOY.md` 第 3 节）。

## 3. 验收命令
- 门禁：`bash scripts/preflight.sh` → 退出码 0
- 健康检查：`curl -fsS http://127.0.0.1:8010/health` → 200

## 4. 回滚
```bash
git tag -l | sort -V | tail -3
APP_DIR=/opt/cardio TARGET_ENV=production bash scripts/deploy.sh <上一个 tag>
```
- 回滚后重跑第 3 节验收。
- 目标：从决定回滚到旧版本恢复服务 ≤ 30 分钟。
- 在 release notes 里记一句回滚原因。

- 本仓库的 preflight 覆盖 Python 侧；前端/数据侧的检查以 `.github/workflows/ci.yml` 为准。
## 5. 同源纪律
`scripts/*.sh`、`CLAUDE.md`、`docs/DEPLOY.md` 在业务仓库里都是**副本**。
先改 `MiLab-Bit/milab-release`，再往各业务仓库同步。
