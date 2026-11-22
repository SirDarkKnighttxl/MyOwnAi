"""NOX daemon."""
from __future__ import annotations

import asyncio
import copy
import json
import math
import pathlib
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from . import agent, approvals, lessons, models as model_manager, rag, store
from .engine import Engine
from .policy import Policy

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "nox.json"
PERSONA = ROOT / "policy" / "persona.md"
LESSONS = ROOT / "policy" / "lessons.md"
UI = ROOT / "ui" / "index.html"
MODEL_ROLES = {"stock", "ablit", "trained"}
SAMPLER_LIMITS = {
    "temp": (0.0, 2.0, float),
    "top_p": (0.0, 1.0, float),
    "top_k": (0, 200, int),
    "min_p": (0.0, 1.0, float),
    "repeat_penalty": (0.1, 2.0, float),
    "max_tokens": (1, 32768, int),
}

app = FastAPI(title="NOX")
engine: Engine | None = None
policy: Policy | None = None
model_lock = threading.RLock()
engine_use_lock = asyncio.Lock()


def cfg() -> dict:
    c = json.loads(CONFIG.read_text(encoding="utf-8"))
    override = ROOT / "runtime.json"
    if override.exists():
        try:
            o = json.loads(override.read_text(encoding="utf-8"))
            c["server"]["engine_port"] = o.get("engine_port", c["server"]["engine_port"])
        except (ValueError, KeyError):
            pass
    return c


def persona() -> str:
    """System prompt: persona.md + lessons.md, both read from disk per call."""
    parts = []
    if PERSONA.exists():
        parts.append(PERSONA.read_text(encoding="utf-8"))
    block = lessons.prompt_block(LESSONS)
    if block:
        parts.append(block)
    return "\n\n".join(parts)


@app.on_event("startup")
def boot() -> None:
    global engine, policy
    c = cfg()
    approvals.broker.reset()
    policy = Policy(c)
    engine = Engine(c)
    threading.Thread(target=_bring_up, daemon=True).start()


def _bring_up() -> None:
    assert engine is not None
    with model_lock:
        engine.start()
        engine.wait_ready()


@app.on_event("shutdown")
def halt() -> None:
    approvals.broker.reset()
    if engine:
        with model_lock:
            engine.stop()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI)


@app.get("/api/status")
def status() -> dict:
    assert engine is not None
    return {"ready": engine.ready, "running": engine.running,
            "error": engine.error, "mode": policy.mode if policy else "?",
            "airgap": policy.airgap if policy else False,
            "role": engine.cfg["model"].get("role", "stock"),
            "model": engine.model_path,
            "log": engine.log_tail(6) if engine.error else ""}


def _models_payload() -> dict:
    assert engine is not None
    loaded = engine.model_path if engine.running else None
    return {
        "models": model_manager.discover(engine.cfg, loaded),
        "loaded": loaded,
    }


@app.get("/api/models")
def get_models() -> dict:
    return _models_payload()


def _write_config(config: dict) -> None:
    temporary = CONFIG.with_suffix(CONFIG.suffix + ".tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    temporary.replace(CONFIG)


def _load_model(candidate: dict) -> None:
    assert engine is not None
    with model_lock:
        base = json.loads(CONFIG.read_text(encoding="utf-8"))
        old_engine_cfg = copy.deepcopy(engine.cfg)
        was_running = engine.running

        selected = candidate["config_path"]
        selected_key = model_manager.path_key(candidate["path"])
        remaining = [
            raw for raw in base["model"].get("paths", [])
            if model_manager.path_key(model_manager.resolve(raw)) != selected_key
        ]
        base["model"]["paths"] = [selected] + remaining
        base["model"]["role"] = candidate["role"]

        engine.stop()
        engine.cfg["model"] = copy.deepcopy(base["model"])
        engine.error = None
        engine.start()
        if engine.wait_ready():
            try:
                _write_config(base)
                return
            except OSError as exc:
                engine.error = f"could not persist model selection: {exc}"

        failure = engine.error or "model failed to start"
        engine.stop()
        engine.cfg = old_engine_cfg
        if was_running:
            engine.start()
            engine.wait_ready()
        raise RuntimeError(f"{failure}; previous model restored")


def _unload_model() -> None:
    assert engine is not None
    with model_lock:
        engine.stop()
        engine.model_path = None
        engine.error = None


@app.post("/api/models")
async def change_model(req: Request) -> dict:
    assert engine is not None
    body = await req.json()
    action = body.get("action")
    async with engine_use_lock:
        if action == "unload":
            await asyncio.to_thread(_unload_model)
        elif action == "load":
            requested = body.get("path", "")
            candidate = model_manager.select(engine.cfg, requested) if requested else None
            if candidate is None:
                raise HTTPException(404, "model is not in a configured model directory")
            if not candidate["loadable"]:
                raise HTTPException(400, "embedding models cannot be loaded as chat models")
            try:
                await asyncio.to_thread(_load_model, candidate)
            except RuntimeError as exc:
                raise HTTPException(500, str(exc)) from exc
        else:
            raise HTTPException(400, "action must be load or unload")
    return {"ok": True, **_models_payload()}


@app.get("/api/sessions")
def sessions() -> list[dict]:
    return store.list_sessions()


@app.post("/api/sessions")
async def make_session(req: Request) -> dict:
    body = await req.json()
    return {"id": store.new_session(body.get("title", "untitled"))}


@app.delete("/api/sessions/{sid}")
def drop_session(sid: int) -> dict:
    store.delete(sid)
    return {"ok": True}


@app.get("/api/sessions/{sid}")
def read_session(sid: int) -> dict:
    return {"messages": store.get_msgs(sid)}


@app.get("/api/persona")
def get_persona() -> dict:
    return {"text": persona()}


@app.put("/api/persona")
async def set_persona(req: Request) -> dict:
    PERSONA.write_text((await req.json()).get("text", ""), encoding="utf-8")
    return {"ok": True}


async def _lesson_text(req: Request) -> str:
    try:
        body = await req.json()
    except ValueError as exc:
        raise HTTPException(400, "body must be JSON") from exc
    text = body.get("text", "") if isinstance(body, dict) else ""
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(400, "text must be a non-empty string")
    return text


def _lesson_404(index: int) -> HTTPException:
    return HTTPException(404, f"no lesson at index {index}")


@app.get("/api/lessons")
def get_lessons() -> dict:
    return {"lessons": lessons.list_lessons(LESSONS)}


@app.post("/api/lessons")
async def add_lesson(req: Request) -> dict:
    item = lessons.add(await _lesson_text(req), LESSONS)
    return {"ok": True, **item, "lessons": lessons.list_lessons(LESSONS)}


@app.put("/api/lessons/{index}")
async def edit_lesson(index: int, req: Request) -> dict:
    text = await _lesson_text(req)
    try:
        item = lessons.update(index, text, LESSONS)
    except IndexError as exc:
        raise _lesson_404(index) from exc
    return {"ok": True, **item, "lessons": lessons.list_lessons(LESSONS)}


@app.delete("/api/lessons/{index}")
def drop_lesson(index: int) -> dict:
    try:
        item = lessons.delete(index, LESSONS)
    except IndexError as exc:
        raise _lesson_404(index) from exc
    return {"ok": True, **item, "lessons": lessons.list_lessons(LESSONS)}


@app.get("/api/config")
def get_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


@app.get("/api/approvals")
def get_approvals() -> dict:
    return {"pending": approvals.broker.list()}


@app.post("/api/approvals/{request_id}")
async def decide_approval(request_id: str, req: Request) -> dict:
    decision = (await req.json()).get("decision", "")
    try:
        resolved = approvals.broker.resolve(request_id, decision)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not resolved:
        raise HTTPException(404, "approval request not found")
    return {"ok": True}


def _validate_config(config: dict) -> None:
    role = config.get("model", {}).get("role")
    if role not in MODEL_ROLES:
        raise HTTPException(400, f"model.role must be one of {sorted(MODEL_ROLES)}")
    sampling = config.get("sampling")
    if not isinstance(sampling, dict):
        raise HTTPException(400, "sampling must be an object")
    for name, (minimum, maximum, value_type) in SAMPLER_LIMITS.items():
        value = sampling.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(400, f"sampling.{name} must be numeric")
        if value_type is int and not isinstance(value, int):
            raise HTTPException(400, f"sampling.{name} must be an integer")
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise HTTPException(
                400, f"sampling.{name} must be between {minimum} and {maximum}"
            )
    if not isinstance(config.get("ui", {}).get("airgap"), bool):
        raise HTTPException(400, "ui.airgap must be a boolean")


@app.put("/api/config")
async def set_config(req: Request) -> dict:
    global policy
    body = await req.json()
    _validate_config(body)
    _write_config(body)
    replacement = Policy(body)
    if policy is not None:
        replacement.inherit_session_grants(policy)
    policy = replacement
    return {"ok": True}


@app.post("/api/chat")
async def chat(req: Request) -> StreamingResponse:
    assert engine is not None and policy is not None
    if not engine.ready:
        raise HTTPException(503, engine.error or "engine not ready")

    body = await req.json()
    sid = body.get("session")
    messages = body.get("messages", [])
    think = bool(body.get("think", True))

    sys_parts = [persona()]
    if body.get("rag", True) and messages:
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        block = await asyncio.to_thread(rag.context, last)
        if block:
            sys_parts.append(block)
    system = "\n\n".join(p for p in sys_parts if p)

    full = [{"role": "system", "content": system}] + messages
    url = f"http://127.0.0.1:{engine.port}"
    sampling = cfg()["sampling"]

    if sid:
        store.add_msg(sid, "user", messages[-1]["content"] if messages else "")

    queue: asyncio.Queue = asyncio.Queue()

    async def drive() -> None:
        try:
            async with engine_use_lock:
                if not engine.ready:
                    raise RuntimeError(engine.error or "engine not ready")
                text = await agent.run(policy, url, full, sampling, queue.put_nowait, think)
            await queue.put({"final": text})
        except Exception as exc:
            await queue.put({"final": f"[error] {exc}"})
        finally:
            await queue.put(None)

    async def relay():
        task = asyncio.create_task(drive())
        while True:
            evt = await queue.get()
            if evt is None:
                break
            if "final" in evt:
                final = evt["final"]
                for i in range(0, len(final), 120):
                    yield ("data: " + json.dumps(
                        {"choices": [{"delta": {"content": final[i:i + 120]}}]}) + "\n\n").encode()
                if sid:
                    store.add_msg(sid, "assistant", final)
            else:
                yield ("data: " + json.dumps({"nox": evt}) + "\n\n").encode()
        await task
        yield b"data: [DONE]\n\n"

    return StreamingResponse(relay(), media_type="text/event-stream")
