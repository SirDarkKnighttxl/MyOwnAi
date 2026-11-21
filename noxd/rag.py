"""Local embeddings + cosine retrieval over the corpus."""
from __future__ import annotations

import json
import math
import pathlib
import socket
import subprocess
import sys
import time

import httpx

from .store import conn

ROOT = pathlib.Path(__file__).resolve().parent.parent
BIN = ROOT / "bin" / ("llama-server.exe" if sys.platform == "win32" else "llama-server")
EMBED = ROOT / "models" / "nomic-embed-text-v1.5.Q4_K_M.gguf"
PORT = 8095
MIN_SCORE = 0.60

TEXT_EXT = {".md", ".txt", ".rst", ".conf", ".cfg", ".yaml", ".yml", ".json"}
SKIP = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}


def _up() -> bool:
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def ensure() -> bool:
    if _up():
        return True
    if not EMBED.exists():
        return False
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen(
        [str(BIN), "-m", str(EMBED), "-c", "2048", "-ngl", "99",
         "--host", "127.0.0.1", "--port", str(PORT), "--embeddings", "-np", "1"],
        cwd=str(BIN.parent), stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=flags,
    )
    for _ in range(120):
        if _up():
            return True
        time.sleep(0.5)
    return False


def embed(text: str) -> list[float] | None:
    try:
        r = httpx.post(f"http://127.0.0.1:{PORT}/v1/embeddings",
                       json={"input": text[:6000]}, timeout=120)
        return r.json()["data"][0]["embedding"]
    except Exception:
        return None


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def chunk(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return out


def index(root: pathlib.Path, limit: int = 1500, only: list[str] | None = None) -> dict:
    if not ensure():
        return {"ok": False, "error": "embedding model unavailable"}

    files = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in TEXT_EXT:
            continue
        if SKIP & set(p.parts):
            continue
        if only:
            try:
                rel = p.relative_to(root).parts[0]
            except ValueError:
                continue
            if rel not in only:
                continue
        try:
            if p.stat().st_size > 400_000:
                continue
        except OSError:
            continue
        files.append(p)

    print(f"{len(files)} candidate files", flush=True)
    done, fails = 0, 0
    with conn() as c:
        c.execute("DELETE FROM chunks")
        for p in files:
            if done >= limit:
                break
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for piece in chunk(text):
                if len(piece.strip()) < 80:
                    continue
                vec = embed(piece)
                if not vec:
                    fails += 1
                    if fails > 12:
                        return {"ok": False, "error": "embedding server died", "chunks": done}
                    continue
                fails = 0
                c.execute("INSERT INTO chunks(path, text, vec) VALUES(?,?,?)",
                          (str(p), piece, json.dumps(vec)))
                done += 1
                if done % 25 == 0:
                    print(f"  {done} chunks", flush=True)
                if done >= limit:
                    break
    return {"ok": True, "chunks": done, "files": len(files)}


def search(query: str, k: int = 6) -> list[dict]:
    qv = embed(query)
    if not qv:
        return []
    with conn() as c:
        rows = c.execute("SELECT path, text, vec FROM chunks").fetchall()
    scored = []
    for r in rows:
        try:
            scored.append((_cos(qv, json.loads(r["vec"])), r["path"], r["text"]))
        except Exception:
            continue
    scored.sort(reverse=True)
    return [{"score": round(s, 3), "path": p, "text": t}
            for s, p, t in scored[:k] if s >= MIN_SCORE]


def context(query: str, k: int = 6) -> str:
    hits = search(query, k)
    if not hits:
        return ""
    parts = ["Relevant corpus excerpts:"]
    for h in hits:
        parts.append(f"\n--- {h['path']} ({h['score']})\n{h['text'].strip()}")
    return "\n".join(parts)
