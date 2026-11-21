"""Tool surface. Every call passes through Policy first."""
from __future__ import annotations

import html
import pathlib
import re as _re
import subprocess
import sys

import httpx

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NOX/1.0"}
SEARX = "http://127.0.0.1:8888"

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORK = ROOT / "work"

SCHEMA = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file. Returns content with line numbers.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "start": {"type": "integer", "description": "first line, 1-based"},
            "end": {"type": "integer", "description": "last line, inclusive"},
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write a text file, creating parent dirs. Overwrites.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        }, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "List a directory. Directories end with /.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "grep",
        "description": "Regex search across files. Returns path:line:match, capped.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
            "glob": {"type": "string", "description": "e.g. *.py"},
            "limit": {"type": "integer"},
        }, "required": ["pattern", "path"]}}},
    {"type": "function", "function": {
        "name": "shell",
        "description": "Run a shell command in work/. Returns exit code, stdout, stderr.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"},
            "cwd": {"type": "string"},
            "timeout": {"type": "integer"},
        }, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "update_scratchpad",
        "description": "Rewrite the task plan. Call this first on any multi-step task, and again whenever the plan changes. Mark steps [x] done, [!] blocked, [ ] pending.",
        "parameters": {"type": "object", "properties": {
            "content": {"type": "string", "description": "full markdown plan, replaces the old one"},
        }, "required": ["content"]}}},
    {"type": "function", "function": {
        "name": "search",
        "description": "Web search. Returns title, url, snippet. Free, no key.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "fetch",
        "description": "Fetch a URL as plain text. Strips tags, caps at 20k chars.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"},
        }, "required": ["url"]}}},
]


def _abs(raw: str) -> pathlib.Path:
    p = pathlib.Path(raw)
    return p if p.is_absolute() else (WORK / p).resolve()


def _deny(msg: str) -> dict:
    return {"ok": False, "error": msg}


def read_file(policy, args: dict) -> dict:
    path = _abs(args["path"])
    v = policy.check_path(str(path))
    if not v:
        return _deny(v.reason)
    if not path.is_file():
        return _deny(f"not a file: {path}")
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return _deny(str(exc))
    start = max(1, int(args.get("start", 1)))
    end = int(args.get("end", len(lines)))
    chunk = lines[start - 1:end]
    body = "\n".join(f"{start + i:>5}  {t}" for i, t in enumerate(chunk))
    return {"ok": True, "path": str(path), "total": len(lines), "content": body[:40000]}


def write_file(policy, args: dict) -> dict:
    path = _abs(args["path"])
    v = policy.check_path(str(path))
    if not v:
        return _deny(v.reason)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = args["content"]
    path.write_text(data, encoding="utf-8")
    return {"ok": True, "path": str(path), "bytes": len(data.encode())}


def list_dir(policy, args: dict) -> dict:
    path = _abs(args["path"])
    v = policy.check_path(str(path))
    if not v:
        return _deny(v.reason)
    if not path.is_dir():
        return _deny(f"not a dir: {path}")
    out = []
    for e in sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:400]:
        out.append(e.name + ("/" if e.is_dir() else ""))
    return {"ok": True, "path": str(path), "entries": out}


def grep(policy, args: dict) -> dict:
    base = _abs(args["path"])
    v = policy.check_path(str(base))
    if not v:
        return _deny(v.reason)
    pat = args["pattern"]
    glob = args.get("glob", "*")
    limit = min(int(args.get("limit", 200)), 800)
    hits = []
    files = [base] if base.is_file() else [p for p in base.rglob(glob) if p.is_file()]
    for f in files:
        if len(hits) >= limit:
            break
        try:
            with f.open("r", encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    if pat.lower() in line.lower():
                        hits.append(f"{f}:{n}:{line.rstrip()[:200]}")
                        if len(hits) >= limit:
                            break
        except OSError:
            continue
    return {"ok": True, "hits": hits, "count": len(hits), "capped": len(hits) >= limit}


def shell(policy, args: dict) -> dict:
    cmd = args["command"]
    v = policy.check_command(cmd)
    if not v:
        return _deny(v.reason)
    cwd = _abs(args.get("cwd", "."))
    if not cwd.is_dir():
        cwd = WORK
    timeout = min(int(args.get("timeout", 120)), 900)
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=str(cwd), capture_output=True,
            timeout=timeout, text=True, errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s"}
    return {
        "ok": r.returncode == 0, "code": r.returncode,
        "stdout": (r.stdout or "")[:20000], "stderr": (r.stderr or "")[:8000],
    }


SCRATCH = WORK / "scratchpad.md"


def update_scratchpad(policy, args: dict) -> dict:
    SCRATCH.parent.mkdir(parents=True, exist_ok=True)
    SCRATCH.write_text(args["content"], encoding="utf-8")
    return {"ok": True, "path": str(SCRATCH)}


def _strip(markup: str) -> str:
    markup = _re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", markup)
    markup = _re.sub(r"(?s)<[^>]+>", " ", markup)
    return _re.sub(r"[ \t\r\f\v]+", " ", html.unescape(markup)).strip()


def search(policy, args: dict) -> dict:
    q = args["query"]
    limit = min(int(args.get("limit", 8)), 20)
    hits = []
    try:
        with httpx.Client(timeout=25, headers=UA, follow_redirects=True) as c:
            try:
                r = c.get(f"{SEARX}/search", params={"q": q, "format": "json"})
                if r.status_code == 200:
                    for it in r.json().get("results", [])[:limit]:
                        hits.append({"title": it.get("title", ""), "url": it.get("url", ""),
                                     "snippet": _strip(it.get("content", ""))[:300]})
            except (httpx.HTTPError, ValueError):
                pass
            if not hits:
                r = c.get("https://html.duckduckgo.com/html/", params={"q": q})
                r.raise_for_status()
                for m in _re.finditer(
                    r'(?s)result__a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?result__snippet[^>]*>(.*?)</a>',
                    r.text,
                ):
                    hits.append({"title": _strip(m.group(2)), "url": html.unescape(m.group(1)),
                                 "snippet": _strip(m.group(3))[:300]})
                    if len(hits) >= limit:
                        break
    except httpx.HTTPError as exc:
        return _deny(f"search failed: {exc}")
    return {"ok": bool(hits), "hits": hits, "count": len(hits)}


def fetch(policy, args: dict) -> dict:
    url = args["url"]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    v = policy.check_host(url.split("/")[2].split(":")[0])
    if not v:
        return _deny(v.reason)
    try:
        with httpx.Client(timeout=30, headers=UA, follow_redirects=True) as c:
            r = c.get(url)
    except httpx.HTTPError as exc:
        return _deny(f"fetch failed: {exc}")
    body = _strip(r.text)
    return {"ok": r.is_success, "url": str(r.url), "status": r.status_code,
            "text": body[:20000]}


HANDLERS = {
    "read_file": read_file, "write_file": write_file,
    "list_dir": list_dir, "grep": grep, "shell": shell,
    "update_scratchpad": update_scratchpad,
    "search": search, "fetch": fetch,
}

NET = {"search", "fetch"}


def dispatch(policy, name: str, args: dict) -> dict:
    fn = HANDLERS.get(name)
    if not fn:
        return _deny(f"unknown tool: {name}")
    if name in NET and getattr(policy, "airgap", False):
        return _deny("airgap mode: network disabled")
    try:
        return fn(policy, args)
    except Exception as exc:
        return _deny(f"{type(exc).__name__}: {exc}")
