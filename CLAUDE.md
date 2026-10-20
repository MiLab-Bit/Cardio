# CLAUDE.md · 本仓库的 AI 协作规约

> 这份文件是给「接手这个仓库的 AI」看的，不是给人看的贡献指南。
> 目的：让 AI 不必每次重新摸环境、重新猜门禁。

## 1. 门禁命令
```bash
bash scripts/preflight.sh
```
**通过的定义**：该命令退出码为 0，且 CI（preflight）为绿。
不要为了让门禁变绿而修改测试期望值或删除测试；先判断是代码问题还是期望值确实过时，并在 PR 描述里说明。

## 2. 改动前必须知道的事
- 提交署名统一用 **MiLab**。**不要**改写历史提交，不要 rebase / amend 已推送的 commit。
- 不要直接推 `main`：改动走分支 + PR，CI 必须绿（分支保护已开）。
- 任何改动都要能对到一张 issue（本仓库属 REL Epic：`MiLab-Bit/milab-release` 的 issue，或本仓库自己的 issue）。
- 服务器运行配置（`/opt/cardio/**` 之外的 systemd 单元、nginx 配置）不在本仓库内，AI 不应修改。

## 3. 不许改的目录 / 文件
- 任何凭据：不得写入仓库、不得写进日志、不得贴进 issue。服务器上的凭据只存在于 600 权限的文件里。
- 已发布的 tag：不删、不移。
- 别人的红线服务：本机还跑着 `openclaw`、`glm-relay`、其它业务仓库，本仓库的改动与部署不得触碰它们。

## 4. 网络与运行环境约束
- 测试必须能**离线**跑通；不允许引入需要联网才能通过的测试。
- fixtures 必须 byte 级确定：重跑生成脚本后文件 hash 不得变化。
- 不要在服务器上跑 Node 构建（2C4G 会与 OpenClaw 抢内存），构建一律在 CI 里做。

## 5. 常用命令
```bash
bash scripts/preflight.sh                      # 门禁
APP_DIR=/opt/cardio bash scripts/deploy.sh --detect   # 只读自检：认成哪个服务/端口/健康端点
```
`bash scripts/deploy.sh <tag|ref>` 才会真的部署。**AI 不要自行部署、不要自行打 tag**。

## 6. 发布相关
发布不通过 AI 直接执行：打 tag、部署、回滚都需要人工确认。
AI 可以准备命令与脚本，但**不要**自行 `git push --tags`、**不要**自行跑 `scripts/deploy.sh`、**不要**改分支保护或 tag 保护。
