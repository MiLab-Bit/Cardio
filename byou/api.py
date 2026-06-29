"""Byou API — FastAPI entry point with Claw platform Tool protocol support."""

from __future__ import annotations

import json as json_mod
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import asyncio

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from byou.config import get_settings
from byou.core.orchestrator import Orchestrator
from byou.agents import create_agent
from byou.core.learning_loop import LearningLoop
from byou.cua.planning import PlanningLayer

# ── App ──────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Byou API", version="0.2.0")

# ── CORS ──────────────────────────────────────────────────────────────────────────
# Tighten allow_origins for production!

_allowed_origins = get_settings().cors_allowed_origins if hasattr(get_settings(), 'cors_allowed_origins') else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API Key Middleware ────────────────────────────────────────────────────────────
# Claw platform calls require API key (header: X-Byou-Key)

_API_KEY_HEADER = "X-Byou-Key"
_MASTER_KEY = get_settings().master_api_key if hasattr(get_settings(), 'master_api_key') else None


async def verify_api_key(request: Request) -> str | None:
    """Verify API key for protected endpoints. Returns key if valid, else raises 401."""
    # Public endpoints (no auth required)
    public_paths = {"/health", "/docs", "/openapi.json", "/redoc"}
    if request.url.path in public_paths or request.url.path.startswith("/tool/info"):
        return None

    key = request.headers.get(_API_KEY_HEADER)
    if not key:
        raise HTTPException(status_code=401, detail={
            "error": {
                "code": "UNAUTHORIZED",
                "message": f"Missing {_API_KEY_HEADER} header",
            }
        })

    # In production: validate against Redis/DB
    # For now: accept any non-empty key if MASTER_KEY not set, else require match
    if _MASTER_KEY and key != _MASTER_KEY:
        raise HTTPException(status_code=401, detail={
            "error": {
                "code": "INVALID_API_KEY",
                "message": "Invalid API key",
            }
        })

    return key


# ── Orchestrator Singleton ────────────────────────────────────────────────────────

_orchestrator: Orchestrator | None = None
_orchestrator_lock = asyncio.Lock()


async def get_orchestrator() -> Orchestrator:
    """Thread-safe singleton accessor for Orchestrator."""
    global _orchestrator
    if _orchestrator is None:
        async with _orchestrator_lock:
            if _orchestrator is None:
                _orchestrator = Orchestrator()
                for name in ("extractor", "researcher", "synthesizer", "strategist", "critic"):
                    _orchestrator.register_agent(name, create_agent(name))
    return _orchestrator


# ── Request Models ────────────────────────────────────────────────────────────────

class PipelineRequest(BaseModel):
    card_image_path: str | None = None
    audio_file_path: str | None = None
    context: dict[str, Any] = {}


class ResearchRequest(BaseModel):
    company_name: str
    person_name: str = ""


# ── Tool Protocol Models (Claw Platform) ──────────────────────────────────────────

class ToolInvokeRequest(BaseModel):
    function: str
    parameters: dict[str, Any] = {}
    stream: bool = False
    async_run: bool = False
    session_id: str | None = None


class ToolInfoResponse(BaseModel):
    name: str
    description: str
    version: str
    auth: dict[str, str]
    functions: list[dict[str, Any]]


# ── In-Memory Task Store (for async tasks) ───────────────────────────────────────

_async_tasks: dict[str, dict[str, Any]] = {}
_task_lock = asyncio.Lock()


# ═════════════════════════════════════════════════════════════════════════════════
#  PUBLIC ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}


@app.get("/")
async def root():
    return {
        "message": "Byou API",
        "version": "0.2.0",
        "docs": "/docs",
        "health": "/health",
        "tool_info": "/tool/info",
    }


# ═════════════════════════════════════════════════════════════════════════════════
#  CLAW PLATFORM TOOL PROTOCOL
# ═════════════════════════════════════════════════════════════════════════════════

@app.get("/tool/info")
async def tool_info():
    """Return tool metadata for Claw platform discovery (no auth required)."""
    return {
        "name": "byou_bd_pipeline",
        "description": (
            "BD 客户智能分析 Multi-Agent 系统。"
            "输入客户信息（名片/音频/文本），输出结构化客户档案 + 跟进策略。"
        ),
        "version": "0.2.0",
        "auth": {
            "type": "api_key",
            "header": "X-Byou-Key",
        },
        "functions": [
            {
                "name": "analyze_customer",
                "description": "分析客户信息，输出结构化档案和跟进策略。支持流式输出。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "客户姓名"},
                        "company": {"type": "string", "description": "公司名称"},
                        "input_text": {"type": "string", "description": "自由文本输入（对话记录等）"},
                        "card_image_base64": {"type": "string", "description": "名片图片 base64"},
                        "audio_base64": {"type": "string", "description": "音频 base64"},
                        "pipeline": {
                            "type": "string",
                            "enum": ["default", "quick", "deep"],
                            "default": "default",
                            "description": "Pipeline 配置",
                        },
                    },
                    "required": [],
                },
                "returns": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "profile": {"type": "object"},
                        "strategy": {"type": "object"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
            },
            {
                "name": "cua_fill_form",
                "description": "用 CUA 自动填写网页表单。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "目标表单 URL"},
                        "form_data": {"type": "object", "description": "要填写的数据"},
                    },
                    "required": ["url", "form_data"],
                },
            },
        ],
    }


@app.post("/tool/invoke")
async def tool_invoke(req: ToolInvokeRequest, _key: str | None = Depends(verify_api_key)):
    """Invoke a tool function. Supports sync, async, and SSE streaming.

    - stream=True:  SSE 流式返回进度
    - async_run=True: 立即返回 task_id，后台执行
    """
    func = req.function
    params = req.parameters

    if func == "analyze_customer":
        return await _invoke_analyze_customer(params, req.stream, req.async_run)
    elif func == "cua_fill_form":
        return await _invoke_cua_fill_form(params)
    else:
        raise HTTPException(status_code=400, detail={
            "error": {
                "code": "UNKNOWN_FUNCTION",
                "message": f"Unknown function: {func}",
            }
        })


async def _invoke_analyze_customer(
    params: dict[str, Any],
    stream: bool,
    async_run: bool,
):
    """Handle analyze_customer function call."""
    orch = await get_orchestrator()

    # Decode base64 inputs if present
    card_path = None
    audio_path = None
    if params.get("card_image_base64"):
        card_path = _decode_base64_to_temp(params["card_image_base64"], ".jpg")
    if params.get("audio_base64"):
        audio_path = _decode_base64_to_temp(params["audio_base64"], ".mp3")

    if async_run:
        # Create async task
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        async with _task_lock:
            _async_tasks[task_id] = {
                "status": "running",
                "created_at": time.time(),
                "result": None,
                "error": None,
            }

        # Run in background
        asyncio.create_task(_run_pipeline_task(task_id, orch, card_path, audio_path, params))

        return JSONResponse(status_code=202, content={
            "task_id": task_id,
            "status": "running",
            "status_url": f"/tool/tasks/{task_id}",
        })

    if stream:
        return StreamingResponse(
            _pipeline_sse_stream(orch, card_path, audio_path, params),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Sync, non-streaming
    result = await orch.process_pipeline(
        card_image_path=card_path,
        audio_file_path=audio_path,
        context=params,
    )
    return result.model_dump()


async def _invoke_cua_fill_form(params: dict[str, Any]):
    """Handle cua_fill_form function call."""
    url = params["url"]
    form_data = params["form_data"]

    planner = PlanningLayer()
    perception = {
        "url": url,
        "title": "",
        "dom_hash": "",
        "elements": [
            {"type": "input", "text": k}
            for k in list(form_data.keys())[:10]
        ],
    }

    class FakeTask:
        id = "t1"
        target_url = ""
        actions = None
        def __init__(self, url: str):
            self.target_url = url

    task = FakeTask(target_url=url)
    result = await planner.process(perception, task, context=None)
    return {"status": "planned", "plan": result}


async def _pipeline_sse_stream(
    orch: Orchestrator,
    card_path: str | None,
    audio_path: str | None,
    params: dict[str, Any],
):
    """Generate SSE events for pipeline progress."""
    progress_queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=200)

    def on_progress(stage: str, data: dict) -> None:
        try:
            progress_queue.put_nowait({"stage": stage, "data": data})
        except asyncio.QueueFull:
            pass  # drop oldest

    async def run():
        try:
            result = await orch.process_pipeline(
                card_image_path=card_path,
                audio_file_path=audio_path,
                context=params,
                on_progress=on_progress,
            )
            await progress_queue.put({"stage": "complete", "result": result.model_dump()})
        except Exception as exc:
            await progress_queue.put({"stage": "error", "error": str(exc)})
        finally:
            await progress_queue.put(None)

    task = asyncio.create_task(run())

    try:
        while True:
            msg = await progress_queue.get()
            if msg is None:
                break
            yield f"data: {json_mod.dumps(msg, ensure_ascii=False)}\n\n"
    finally:
        await task


async def _run_pipeline_task(
    task_id: str,
    orch: Orchestrator,
    card_path: str | None,
    audio_path: str | None,
    params: dict[str, Any],
):
    """Run pipeline as background task and store result."""
    try:
        result = await orch.process_pipeline(
            card_image_path=card_path,
            audio_file_path=audio_path,
            context=params,
        )
        async with _task_lock:
            _async_tasks[task_id]["status"] = "completed"
            _async_tasks[task_id]["result"] = result.model_dump()
    except Exception as exc:
        async with _task_lock:
            _async_tasks[task_id]["status"] = "failed"
            _async_tasks[task_id]["error"] = str(exc)


@app.get("/tool/tasks/{task_id}")
async def get_task_status(task_id: str, _key: str | None = Depends(verify_api_key)):
    """Check async task status."""
    async with _task_lock:
        task = _async_tasks.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail={
            "error": {"code": "TASK_NOT_FOUND", "message": f"Task {task_id} not found"}
        })

    resp: dict[str, Any] = {
        "task_id": task_id,
        "status": task["status"],
    }
    if task["status"] == "completed":
        resp["result"] = task["result"]
    elif task["status"] == "failed":
        resp["error"] = task["error"]

    return resp


# ═════════════════════════════════════════════════════════════════════════════════
#  LEGACY ENDPOINTS (kept for backward compatibility)
# ═════════════════════════════════════════════════════════════════════════════════

@app.post("/pipeline", dependencies=[Depends(verify_api_key)])
async def run_pipeline(req: PipelineRequest):
    orch = await get_orchestrator()
    result = await orch.process_pipeline(
        card_image_path=req.card_image_path,
        audio_file_path=req.audio_file_path,
        context=req.context,
    )
    return result.model_dump()


@app.post("/pipeline/upload", dependencies=[Depends(verify_api_key)])
async def pipeline_upload(
    card: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
):
    """Upload files and run full pipeline — with security checks."""
    settings = get_settings()
    card_path, audio_path = None, None

    if card:
        _validate_upload(card, settings)
        card_path = await _save_upload(card)
    if audio:
        _validate_upload(audio, settings)
        audio_path = await _save_upload(audio)

    try:
        orch = await get_orchestrator()
        result = await orch.process_pipeline(
            card_image_path=card_path,
            audio_file_path=audio_path,
        )
        return result.model_dump()
    finally:
        for p in (card_path, audio_path):
            if p:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass


@app.post("/pipeline/upload/stream", dependencies=[Depends(verify_api_key)])
async def pipeline_upload_stream(
    card: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
):
    """Upload + run pipeline with SSE progress streaming."""
    settings = get_settings()
    card_path, audio_path = None, None

    if card:
        _validate_upload(card, settings)
        card_path = await _save_upload(card)
    if audio:
        _validate_upload(audio, settings)
        audio_path = await _save_upload(audio)

    orch = await get_orchestrator()

    async def event_stream():
        progress_queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=200)

        def on_progress(stage: str, data: dict) -> None:
            try:
                progress_queue.put_nowait({"stage": stage, "data": data})
            except asyncio.QueueFull:
                pass

        async def run():
            try:
                result = await orch.process_pipeline(
                    card_image_path=card_path,
                    audio_file_path=audio_path,
                    on_progress=on_progress,
                )
                await progress_queue.put({"stage": "pipeline_done", "data": result.model_dump()})
            except Exception as exc:
                await progress_queue.put({"stage": "pipeline_error", "error": str(exc)})
            finally:
                await progress_queue.put(None)

        task = asyncio.create_task(run())

        try:
            while True:
                msg = await progress_queue.get()
                if msg is None:
                    break
                yield f"data: {json_mod.dumps(msg, ensure_ascii=False)}\n\n"
        finally:
            await task
            for p in (card_path, audio_path):
                if p:
                    try:
                        Path(p).unlink(missing_ok=True)
                    except OSError:
                        pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/research", dependencies=[Depends(verify_api_key)])
async def run_research(req: ResearchRequest):
    agent = create_agent("researcher")
    result = await agent.execute({
        "company_name": req.company_name,
        "person_name": req.person_name,
    })
    return result


@app.get("/insights", dependencies=[Depends(verify_api_key)])
async def get_insights():
    orch = await get_orchestrator()
    return orch.learning_loop.get_insights()


@app.get("/history", dependencies=[Depends(verify_api_key)])
async def get_history(limit: int = Query(default=20, le=100)):
    """Recent pipeline execution records."""
    orch = await get_orchestrator()
    learning = orch.learning_loop
    records = learning.performance_history[-limit:]
    return {
        "total": len(learning.performance_history),
        "limit": limit,
        "records": records,
    }


@app.post("/chat", dependencies=[Depends(verify_api_key)])
async def chat(request: dict):
    """Simple chat endpoint — uses the critic agent for now."""
    message = request.get("message", "")
    if not message:
        raise HTTPException(400, "message required")
    agent = create_agent("critic")
    result = await agent.execute({"query": message, "context": {}})
    return {"reply": result.get("summary", result.get("text", str(result)))}


@app.post("/cua/plan", dependencies=[Depends(verify_api_key)])
async def cua_plan(request: dict):
    """Generate CUA execution plan for a target URL."""
    url = request.get("url", "")
    title = request.get("title", "")
    if not url:
        raise HTTPException(400, "url required")
    planner = PlanningLayer()
    perception = {
        "url": url,
        "title": title,
        "dom_hash": "",
        "elements": [
            {"type": "input", "text": "姓名"},
            {"type": "input", "text": "电话"},
            {"type": "button", "text": "提交"},
        ],
    }

    class FakeTask:
        id: str = "t1"
        target_url: str = ""
        actions: list | None = None
        def __init__(self, target_url: str):
            self.target_url = target_url

    task = FakeTask(target_url=url)
    result = await planner.process(perception, task, context=None)
    return result


# ═════════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═════════════════════════════════════════════════════════════════════════════════

def _decode_base64_to_temp(b64_str: str, suffix: str) -> str:
    """Decode base64 string to temp file, return path."""
    import base64
    data = base64.b64decode(b64_str)
    temp_dir = Path(tempfile.gettempdir())
    safe_name = f"byou_{uuid.uuid4().hex[:8]}{suffix}"
    dest = temp_dir / safe_name
    dest.write_bytes(data)
    return str(dest)


def _validate_upload(file: UploadFile, settings: Any) -> None:
    """Validate uploaded file: extension whitelist, MIME whitelist and size cap."""
    if not file.filename or ".." in file.filename or "/" in file.filename or "\\" in file.filename:
        raise HTTPException(400, "Invalid filename")

    ext = Path(file.filename).suffix.lower()
    if ext not in settings.upload_allowed_extensions:
        raise HTTPException(
            400, f"File type {ext} not allowed. Allowed: {settings.upload_allowed_extensions}"
        )

    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in settings.upload_allowed_mime_types:
        raise HTTPException(
            400, f"MIME type {mime} not allowed. Allowed: {settings.upload_allowed_mime_types}"
        )

    if file.size is not None and file.size > settings.upload_max_bytes:
        raise HTTPException(400, f"File too large. Max {settings.upload_max_bytes} bytes")


async def _save_upload(file: UploadFile) -> str:
    """Save uploaded file to a temp location, enforcing max size."""
    settings = get_settings()
    data = await file.read()

    if len(data) > settings.upload_max_bytes:
        raise HTTPException(400, f"File too large. Max {settings.upload_max_bytes} bytes")

    if not data:
        raise HTTPException(400, "Empty file")

    temp_dir = Path(tempfile.gettempdir())
    safe_name = f"byou_{uuid.uuid4().hex[:8]}_{file.filename}"
    dest = temp_dir / safe_name
    dest.write_bytes(data)
    return str(dest)
