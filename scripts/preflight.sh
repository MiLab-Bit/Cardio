#!/usr/bin/env bash
# Cardio 发布前门禁（唯一入口）。退出码：0 = 无 FAIL（SKIP 不算失败）；1 = 至少一项 FAIL。
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

C_RESET=$'\033[0m'; C_OK=$'\033[1;32m'; C_BAD=$'\033[1;31m'; C_WARN=$'\033[1;33m'; C_DIM=$'\033[2m'
PASS=0; FAIL=0; SKIP=0
FAILED_ITEMS=(); SKIPPED_ITEMS=()
ok(){  PASS=$((PASS+1)); printf '%s[PASS]%s %s\n' "$C_OK" "$C_RESET" "$1"; }
bad(){ FAIL=$((FAIL+1)); FAILED_ITEMS+=("$1"); printf '%s[FAIL]%s %s\n' "$C_BAD" "$C_RESET" "$1"; }
skp(){ SKIP=$((SKIP+1)); SKIPPED_ITEMS+=("$1"); printf '%s[SKIP]%s %s\n' "$C_WARN" "$C_RESET" "$1"; }
sec(){ printf '\n%s---- %s ----%s\n' "$C_DIM" "$1" "$C_RESET"; }

PY=""
for c in venv/bin/python .venv/bin/python env/bin/python; do
  [ -x "$c" ] && PY="$REPO_ROOT/$c" && break
done
[ -z "$PY" ] && PY="$(command -v python3 || true)"
printf '仓库：%s\npython：%s\n' "$REPO_ROOT" "${PY:-未找到}"

# ---------------- 1/3 语法与导入 ----------------
sec "1/3 语法编译（compileall）"
if [ -n "$PY" ]; then
  if "$PY" -m compileall -q cardio run.py mock_llm.py >/dev/null 2>&1; then
    ok "cardio/ 与入口脚本语法通过"
  else
    "$PY" -m compileall -q cardio run.py mock_llm.py || true
    bad "语法编译失败"
  fi
else
  skp "找不到 python 解释器"
fi

# ---------------- 2/3 离线接口冒烟 ----------------
sec "2/3 离线接口冒烟"
if [ -z "$PY" ]; then
  skp "找不到 python 解释器"
elif [ ! -f tests/smoke.py ]; then
  skp "没有 tests/smoke.py"
else
  if "$PY" tests/smoke.py; then ok "离线冒烟通过"; else bad "离线冒烟未通过"; fi
  printf '  命令：%s tests/smoke.py\n' "$PY"
fi

# ---------------- 3/3 前端构建 ----------------
sec "3/3 前端构建（cardio-web）"
if [ ! -f cardio-web/package.json ]; then
  skp "没有 cardio-web/package.json"
elif ! command -v npm >/dev/null 2>&1; then
  skp "环境里没有 npm"
else
  (
    set -e
    cd cardio-web
    if [ -f package-lock.json ]; then npm ci --no-audit --no-fund >/dev/null; else npm install --no-audit --no-fund >/dev/null; fi
    npm run build >/dev/null
  ) && ok "前端构建通过（cardio-web）" || bad "前端构建失败（cardio-web）"
fi

# ---------------- 汇总 ----------------
printf '\n%s================ 汇总 ================%s\n' "$C_DIM" "$C_RESET"
printf 'PASS %s ｜ FAIL %s ｜ SKIP %s\n' "$PASS" "$FAIL" "$SKIP"
if [ "$SKIP" -gt 0 ]; then
  printf '\n%s被跳过的项：%s\n' "$C_WARN" "$C_RESET"
  for i in "${SKIPPED_ITEMS[@]}"; do printf '  · %s\n' "$i"; done
fi
if [ "$FAIL" -gt 0 ]; then
  printf '\n%s门禁未通过：%s\n' "$C_BAD" "$C_RESET"
  for i in "${FAILED_ITEMS[@]}"; do printf '  · %s\n' "$i"; done
  exit 1
fi
printf '\n%s门禁通过（没有失败项）。%s\n' "$C_OK" "$C_RESET"
