"""Local embeddings + cosine retrieval over the corpus."""
from __future__ import annotations

import fnmatch
import json
import math
import pathlib
import socket
import subprocess
import sys
import time

import httpx

from .store import session

ROOT = pathlib.Path(__file__).resolve().parent.parent
BIN = ROOT / "bin" / ("llama-server.exe" if sys.platform == "win32" else "llama-server")
EMBED = ROOT / "models" / "nomic-embed-text-v1.5.Q4_K_M.gguf"
LOG = ROOT / "logs" / "embed.log"
PORT = 8095
# Embedding inputs must fit in one physical batch; llama-server's default
# n_ubatch is 512 tokens, which dense chunks (wordlists, SVG, dumps) exceed.
BATCH = 2048
MIN_SCORE = 0.60
RETRY_DELAYS = (0.5, 1.5)
MAX_CONSEC_FAIL = 20
LONG_CHUNK = 4000
PROGRESS_EVERY = 25
_sleep = time.sleep

TEXT_EXT = {".md", ".txt", ".rst", ".conf", ".cfg", ".yaml", ".yml", ".json"}
SKIP = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}
# Generated dumps, data and binary-ish text that only waste embed calls.
# Bump FILTER_VERSION whenever these change: it is part of the resume
# fingerprint, because candidate numbers shift when the file set changes.
FILTER_VERSION = 3
EXCLUDE_DIRS = {"images", "testdata", "test-data", "fixtures"}
EXCLUDE_NAMES = ("repomix-output*", "*wordlist*", "*.min.*")
MAX_LINE = 1000
_last_error = ""


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
    args = [str(BIN), "-m", str(EMBED), "-c", str(BATCH),
            "-b", str(BATCH), "-ub", str(BATCH), "-ngl", "99",
            "--host", "127.0.0.1", "--port", str(PORT), "--embeddings", "-np", "1"]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8", errors="replace") as log:
        log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} start: {' '.join(args)}\n")
        log.flush()
        # The child keeps its own copy of the handle; ours closes on exit.
        subprocess.Popen(args, cwd=str(BIN.parent), stdout=log,
                         stderr=subprocess.STDOUT, creationflags=flags)
    for _ in range(120):
        if _up():
            return True
        time.sleep(0.5)
    return False


def embed(text: str) -> list[float] | None:
    global _last_error
    try:
        r = httpx.post(f"http://127.0.0.1:{PORT}/v1/embeddings",
                       json={"input": text[:6000]}, timeout=120)
        if r.status_code != 200:
            _last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            return None
        return r.json()["data"][0]["embedding"]
    except Exception as e:
        _last_error = f"{type(e).__name__}: {e}"[:200]
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


def embed_retry(text: str, attempts: int = 3) -> list[float] | None:
    """Embed with backoff: try, wait 0.5s, try, wait 1.5s, try, then give up."""
    for attempt in range(attempts):
        vec = embed(text)
        if vec:
            return vec
        if attempt < attempts - 1:
            _sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
    return None


def _files(root: pathlib.Path, only: list[str] | None) -> list[pathlib.Path]:
    files = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in TEXT_EXT:
            continue
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if SKIP & set(rel.parts):
            continue
        if EXCLUDE_DIRS & set(rel.parts[1:-1]):
            continue
        if any(fnmatch.fnmatch(p.name.lower(), pat) for pat in EXCLUDE_NAMES):
            continue
        if only and rel.parts[0] not in only:
            continue
        try:
            if p.stat().st_size > 400_000:
                continue
        except OSError:
            continue
        longest = _longest_line(p)
        if longest > MAX_LINE:
            print(f"skip long-line {rel.as_posix()} longest={longest}", flush=True)
            continue
        files.append(p)
    # Stable order so a candidate number means the same chunk on every run.
    files.sort(key=lambda f: f.relative_to(root).as_posix())
    return files


def _longest_line(p: pathlib.Path) -> int:
    """Length of the longest line (newline excluded). Minified/SVG/dump files
    exceed MAX_LINE. An unreadable file counts as too long, so it is skipped
    and logged rather than silently dropped."""
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return max((len(line.rstrip("\r\n")) for line in f), default=0)
    except OSError:
        return MAX_LINE + 1


def _candidates(files: list[pathlib.Path]):
    """Yield (number, path, piece) for every indexable chunk, in a fixed order."""
    n = 0
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for piece in chunk(text):
            if len(piece.strip()) < 80:
                continue
            yield n, p, piece
            n += 1


def _state(c) -> dict | None:
    row = c.execute(
        "SELECT next_candidate, skipped, scope FROM index_state WHERE id=1").fetchone()
    return dict(row) if row else None


def _save_state(c, next_candidate: int, skipped: int, scope: str) -> None:
    c.execute(
        "INSERT OR REPLACE INTO index_state(id, next_candidate, skipped, scope, updated) "
        "VALUES(1,?,?,?,?)", (next_candidate, skipped, scope, time.time()))


def index(root: pathlib.Path, limit: int = 1500, only: list[str] | None = None,
          resume: bool = False) -> dict:
    """Embed corpus chunks into SQLite.

    The resume cursor (next_candidate) lives in index_state and is advanced in
    the same transaction as the rows it covers. Candidates that fail every
    retry are skipped; their cursor advance is committed with the next
    successful insert (or at a clean finish), so an abort or interrupt retries
    them instead of losing them. `limit` caps chunks inserted by this run.
    """
    if not ensure():
        return {"ok": False, "error": "embedding model unavailable"}

    repos = ",".join(sorted(only)) if only else "*"
    scope = f"{repos}|filter={FILTER_VERSION}"
    clean_cmd = f"python index_corpus.py {limit}" + (f" {','.join(only)}" if only else "")
    files = _files(root, only)
    print(f"{len(files)} candidate files", flush=True)

    with session() as c:
        state = _state(c) if resume else None
        if resume and state and state["scope"] != scope:
            return {"ok": False, "error": f"resume refused: saved scope {state['scope']!r} != "
                                          f"{scope!r} (repo list or file filter changed). "
                                          f"Run `{clean_cmd}` without --resume."}
        if not resume or not state:
            c.execute("DELETE FROM chunks")
            c.execute("DELETE FROM index_state")
            _save_state(c, 0, 0, scope)
            c.commit()
            state = {"next_candidate": 0, "skipped": 0}

        start = state["next_candidate"]
        committed_next, committed_skipped = start, state["skipped"]
        pending_next, pending_skipped = start, committed_skipped
        done, consec = 0, 0
        aborted = False
        if resume and start:
            print(f"resuming at candidate {start + 1}", flush=True)

        for n, p, piece in _candidates(files):
            if n < start:
                continue
            if done >= limit:
                break
            if len(piece) > LONG_CHUNK:
                print(f"  long chunk {len(piece)} chars: {p} #{n + 1}", flush=True)
            vec = embed_retry(piece)
            if not vec:
                consec += 1
                pending_skipped += 1
                pending_next = n + 1
                print(f"  skip {p} #{n + 1} (consec={consec}) {_last_error}", flush=True)
                if consec >= MAX_CONSEC_FAIL:
                    aborted = True
                    break
                continue
            consec = 0
            pending_next = n + 1
            c.execute("INSERT INTO chunks(path, text, vec) VALUES(?,?,?)",
                      (str(p), piece, json.dumps(vec)))
            _save_state(c, pending_next, pending_skipped, scope)
            c.commit()
            committed_next, committed_skipped = pending_next, pending_skipped
            done += 1
            if done % PROGRESS_EVERY == 0:
                print(f"  {done} chunks done={done} skipped={committed_skipped} "
                      f"consec={consec}", flush=True)

        if aborted:
            # Leave the failing run uncommitted so a resume retries it.
            return {"ok": False, "error": f"{consec} consecutive embed failures "
                                          f"(last: {_last_error})", "chunks": done,
                    "skipped": committed_skipped, "next_candidate": committed_next,
                    "consec": consec}
        if (pending_next, pending_skipped) != (committed_next, committed_skipped):
            _save_state(c, pending_next, pending_skipped, scope)
            c.commit()
        return {"ok": True, "chunks": done, "skipped": pending_skipped,
                "next_candidate": pending_next, "files": len(files)}


def search(query: str, k: int = 6) -> list[dict]:
    # Start (or confirm) the embed server first, so a dead server is reported
    # instead of masquerading as "no results above the floor".
    if not ensure():
        print("rag.search: embedding server unavailable", flush=True)
        return []
    qv = embed(query)
    if not qv:
        print(f"rag.search: query embed failed: {_last_error}", flush=True)
        return []
    with session() as c:
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
