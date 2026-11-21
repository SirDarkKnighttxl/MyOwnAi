"""NOX daemon."""
from __future__ import annotations

import asyncio
import json
import pathlib
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from . import agent, rag, store
from .engine import Engine
from .policy import Policy

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "nox.json"
PERSONA = ROOT / "policy" / "persona.md"
LESSONS = ROOT / "policy" / "lessons.md"
UI = ROOT / "ui" / "index.html"
MODEL_ROLES = {"stock", "ablit", "trained"}

app = FastAPI(title="NOX")
engine: Engine | None = None
policy: Policy | None = None


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
    parts = []
    if PERSONA.exists():
        parts.append(PERSONA.read_text(encoding="utf-8"))
    if LESSONS.exists():
        lessons = LESSONS.read_text(encoding="utf-8").strip()
        if lessons:
            parts.append("LESSONS\n" + lessons)
    return "\n\n".join(parts)


@app.on_event("startup")
def boot() -> None:
    global engine, policy
    c = cfg()
    policy = Policy(c)
    engine = Engine(c)
    threading.Thread(target=_bring_up, daemon=True).start()


def _bring_up() -> None:
    assert engine is not None
    engine.start()
    engine.wait_ready()


@app.on_event("shutdown")
def halt() -> None:
    if engine:
        engine.stop()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI)


@app.get("/api/status")
def status() -> dict:
    assert engine is not None
    return {"ready": engine.ready, "running": engine.running,
            "error": engine.error, "mode": policy.mode if policy else "?",
            "role": engine.cfg["model"].get("role", "stock"),
            "model": engine.model_path,
            "log": engine.log_tail(6) if engine.error else ""}


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


@app.post("/api/lessons")
async def add_lesson(req: Request) -> dict:
    text = (await req.json()).get("text", "").strip()
    if text:
        with LESSONS.open("a", encoding="utf-8") as fh:
            fh.write(f"- {text}\n")
    return {"ok": True}


@app.get("/api/config")
def get_config() -> dict:
    return cfg()


@app.put("/api/config")
async def set_config(req: Request) -> dict:
    global policy
    body = await req.json()
    role = body.get("model", {}).get("role")
    if role not in MODEL_ROLES:
        raise HTTPException(400, f"model.role must be one of {sorted(MODEL_ROLES)}")
    CONFIG.write_text(json.dumps(body, indent=2), encoding="utf-8")
    policy = Policy(body)
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
