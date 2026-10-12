#!/usr/bin/env python3
"""Cardio 离线接口冒烟：不连网、不连 Temporal、不连 LLM。

做法：把配置强制指向临时目录与假密钥，用 FastAPI TestClient 起进程内应用，
只打「不需要外部依赖」的端点。退出码 0 = 全部通过。
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ---- 离线化配置（必须在 import cardio.* 之前）----
_tmp = tempfile.mkdtemp(prefix="cardio-smoke-")
os.environ["CARDIO_DATA_DIR"] = _tmp
os.environ["CARDIO_DB_PATH"] = os.path.join(_tmp, "cardio.db")
os.environ.setdefault("CARDIO_JWT_SECRET", "ci-smoke-secret-not-for-prod")
os.environ.setdefault("CARDIO_LLM_BASE_URL", "http://127.0.0.1:9/v1")  # 不可达，冒烟不调用
os.environ.setdefault("CARDIO_LLM_API_KEY", "smoke-not-a-real-key")

RESULTS: list[tuple[bool, str]] = []


def check(name, fn):
    try:
        detail = fn() or ""
        RESULTS.append((True, f"{name} — {detail}"))
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((False, f"{name} — {type(exc).__name__}: {exc}"))
        traceback.print_exc()


def main() -> int:
    from fastapi.testclient import TestClient

    def _import():
        import cardio.server as srv  # noqa: F401
        return f"app = {srv.app.title} v{srv.app.version}"

    def _health():
        with TestClient(app) as c:
            r = c.get("/health")
            assert r.status_code == 200, f"status={r.status_code}"
            return f"GET /health -> 200 {r.json()}"

    def _healthz():
        with TestClient(app) as c:
            r = c.get("/api/healthz")
            assert r.status_code in (200, 401), f"status={r.status_code}"
            return f"GET /api/healthz -> {r.status_code}"

    def _openapi():
        with TestClient(app) as c:
            r = c.get("/openapi.json")
            assert r.status_code == 200, f"status={r.status_code}"
            paths = r.json().get("paths", {})
            assert len(paths) >= 8, f"只有 {len(paths)} 条路径"
            return f"{len(paths)} 条路径可生成 schema"

    def _auth_gate():
        with TestClient(app) as c:
            r = c.get("/api/apikeys")
            assert r.status_code in (401, 403), f"未带凭据应被拒，实际 status={r.status_code}"
            return f"GET /api/apikeys 无凭据 -> {r.status_code}（预期 401/403）"

    def _unknown():
        with TestClient(app) as c:
            r = c.get("/definitely-not-a-route")
            assert r.status_code == 404, f"status={r.status_code}"
            return "未知路径 -> 404（不是 5xx）"

    check("服务 import", _import)
    import cardio.server as srv

    app = srv.app
    check("GET /health", _health)
    check("GET /api/healthz", _healthz)
    check("GET /openapi.json", _openapi)
    check("鉴权闸门", _auth_gate)
    check("未知路径", _unknown)

    print("冒烟明细：")
    for okflag, line in RESULTS:
        print(f"  [{'PASS' if okflag else 'FAIL'}] {line}")
    failed = sum(1 for okflag, _ in RESULTS if not okflag)
    print(f"冒烟汇总：PASS {len(RESULTS) - failed} ｜ FAIL {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
