"""Tool surface. Every call passes through Policy first."""
from __future__ import annotations

import html
import os
import pathlib
import re as _re
import signal
import subprocess
import sys
import tempfile

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
        "name": "edit_file",
        "description": "Replace one exact text block in a file. Fails if the block is missing or appears more than once.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
        }, "required": ["path", "old_text", "new_text"]}}},
    {"type": "function", "function": {
        "name": "apply_patch",
        "description": "Apply an exact unified diff to one file. Supports multiple hunks and rejects stale context.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "patch": {"type": "string"},
        }, "required": ["path", "patch"]}}},
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
        "name": "run_python",
        "description": "Run Python code from a temporary file under work/. Captures both streams and enforces a process-tree timeout.",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string"},
            "timeout": {"type": "number", "description": "seconds, 0.1-300"},
        }, "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "git_status",
        "description": "Show branch and working-tree status for a Git repository.",
        "parameters": {"type": "object", "properties": {
            "cwd": {"type": "string", "description": "repository path, relative to work/"},
        }}}},
    {"type": "function", "function": {
        "name": "git_diff",
        "description": "Show unstaged or staged changes for a Git repository.",
        "parameters": {"type": "object", "properties": {
            "cwd": {"type": "string", "description": "repository path, relative to work/"},
            "staged": {"type": "boolean", "description": "show staged changes"},
        }}}},
    {"type": "function", "function": {
        "name": "git_commit",
        "description": "Commit staged changes. A non-empty commit message is required.",
        "parameters": {"type": "object", "properties": {
            "cwd": {"type": "string", "description": "repository path, relative to work/"},
            "message": {"type": "string"},
        }, "required": ["message"]}}},
    {"type": "function", "function": {
        "name": "git_log",
        "description": "Show recent commits for a Git repository.",
        "parameters": {"type": "object", "properties": {
            "cwd": {"type": "string", "description": "repository path, relative to work/"},
            "limit": {"type": "integer", "description": "number of commits, 1-100"},
        }}}},
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


def edit_file(policy, args: dict) -> dict:
    path = _abs(args["path"])
    v = policy.check_path(str(path))
    if not v:
        return _deny(v.reason)
    if not path.is_file():
        return _deny(f"not a file: {path}")
    old_text = args["old_text"]
    new_text = args["new_text"]
    if not isinstance(old_text, str) or not isinstance(new_text, str):
        return _deny("old_text and new_text must be strings")
    if not old_text:
        return _deny("old_text must not be empty")
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            content = fh.read()
    except (OSError, UnicodeError) as exc:
        return _deny(str(exc))
    newline = "\r\n" if "\r\n" in content else "\r" if "\r" in content else "\n"
    old_text = old_text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    new_text = new_text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    matches = content.count(old_text)
    if matches == 0:
        return _deny("exact text not found; file may have changed")
    if matches > 1:
        return _deny(f"ambiguous edit: exact text appears {matches} times")
    updated = content.replace(old_text, new_text, 1)
    try:
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write(updated)
    except OSError as exc:
        return _deny(str(exc))
    return {"ok": True, "path": str(path), "replacements": 1}


_HUNK_HEADER = _re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))?"
    r" \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?: .*)?$"
)


def _parse_patch(raw: str) -> tuple[list[dict], str | None]:
    if not isinstance(raw, str) or not raw.strip():
        return [], "patch must be a non-empty string"

    lines = raw.splitlines()
    hunks = []
    current = None
    for line in lines:
        match = _HUNK_HEADER.match(line)
        if match:
            old_count = int(match.group("old_count") or 1)
            new_count = int(match.group("new_count") or 1)
            current = {
                "old_start": int(match.group("old_start")),
                "old_count": old_count,
                "new_start": int(match.group("new_start")),
                "new_count": new_count,
                "lines": [],
            }
            hunks.append(current)
            continue
        if current is None:
            if line.startswith(("diff --git ", "index ", "--- ", "+++ ")) or not line:
                continue
            return [], f"invalid unified diff before first hunk: {line[:80]}"
        if line == r"\ No newline at end of file":
            continue
        if not line or line[0] not in " +-":
            return [], f"invalid unified diff line: {line[:80]}"
        current["lines"].append(line)

    if not hunks:
        return [], "patch has no hunks"
    for number, hunk in enumerate(hunks, 1):
        old_seen = sum(line[0] in " -" for line in hunk["lines"])
        new_seen = sum(line[0] in " +" for line in hunk["lines"])
        if old_seen != hunk["old_count"] or new_seen != hunk["new_count"]:
            return [], (
                f"invalid hunk {number}: header expects "
                f"{hunk['old_count']} old/{hunk['new_count']} new lines, "
                f"body has {old_seen} old/{new_seen} new"
            )
    return hunks, None


def apply_patch(policy, args: dict) -> dict:
    path = _abs(args["path"])
    v = policy.check_path(str(path))
    if not v:
        return _deny(v.reason)
    if not path.is_file():
        return _deny(f"not a file: {path}")
    hunks, error = _parse_patch(args["patch"])
    if error:
        return _deny(error)
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            content = fh.read()
    except (OSError, UnicodeError) as exc:
        return _deny(str(exc))

    newline = "\r\n" if "\r\n" in content else "\r" if "\r" in content else "\n"
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    final_newline = normalized.endswith("\n")
    lines = normalized.splitlines()
    offset = 0
    previous_end = 0
    for number, hunk in enumerate(hunks, 1):
        old_count = hunk["old_count"]
        base = hunk["old_start"] if old_count == 0 else hunk["old_start"] - 1
        if base < previous_end:
            return _deny(f"invalid hunk {number}: hunks overlap or are out of order")
        index = base + offset
        old_lines = [line[1:] for line in hunk["lines"] if line[0] in " -"]
        new_lines = [line[1:] for line in hunk["lines"] if line[0] in " +"]
        if index < 0 or index + len(old_lines) > len(lines):
            return _deny(
                f"stale patch: hunk {number} is outside {path.name} "
                f"at line {hunk['old_start']}"
            )
        if lines[index:index + len(old_lines)] != old_lines:
            return _deny(
                f"stale patch: hunk {number} context does not match "
                f"{path.name} at line {hunk['old_start']}"
            )
        lines[index:index + len(old_lines)] = new_lines
        offset += len(new_lines) - len(old_lines)
        previous_end = base + len(old_lines)

    updated = newline.join(lines)
    if final_newline and lines:
        updated += newline
    try:
        path.write_text(updated, encoding="utf-8", newline="")
    except OSError as exc:
        return _deny(str(exc))
    return {"ok": True, "path": str(path), "hunks": len(hunks)}


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


def shell_cwd(args: dict) -> pathlib.Path:
    return _abs(args.get("cwd", "."))


def shell(policy, args: dict) -> dict:
    cmd = args["command"]
    cwd = shell_cwd(args)
    v = policy.check_command(cmd, str(cwd))
    if not v:
        return _deny(v.reason)
    if not cwd.is_dir():
        return _deny(f"not a dir: {cwd}")
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


def _kill_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_python(policy, args: dict) -> dict:
    code = args.get("code")
    timeout = args.get("timeout", 30)
    if not isinstance(code, str):
        return _deny("code must be a string")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0.1 <= timeout <= 300
    ):
        return _deny("timeout must be between 0.1 and 300 seconds")

    verdict = policy.check_path(str(WORK.resolve()))
    if not verdict:
        return _deny(verdict.reason)
    verdict = policy.check_command(pathlib.Path(sys.executable).name)
    if not verdict:
        return _deny(verdict.reason)

    WORK.mkdir(parents=True, exist_ok=True)
    path = None
    process = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix="nox-python-", suffix=".py", dir=WORK
        )
        path = pathlib.Path(raw_path)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(code)

        windows_flags = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            if sys.platform == "win32" else 0
        )
        process = subprocess.Popen(
            [sys.executable, str(path)],
            cwd=str(WORK),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            shell=False,
            creationflags=windows_flags,
            start_new_session=sys.platform != "win32",
        )
        try:
            stdout, stderr = process.communicate(timeout=float(timeout))
            timed_out = False
        except subprocess.TimeoutExpired:
            _kill_process_tree(process)
            stdout, stderr = process.communicate()
            timed_out = True

        result = {
            "ok": process.returncode == 0 and not timed_out,
            "code": process.returncode,
            "stdout": stdout[:40000],
            "stderr": stderr[:20000],
            "timed_out": timed_out,
        }
        if timed_out:
            result["error"] = f"timeout after {timeout}s; process tree killed"
        return result
    except OSError as exc:
        if process is not None:
            _kill_process_tree(process)
        return _deny(str(exc))
    finally:
        if path is not None:
            try:
                path.unlink()
            except OSError:
                pass


def _run_git(
    cwd: pathlib.Path,
    args: list[str],
    limit: int = 40000,
    safe_directory: str | None = None,
) -> dict:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    trusted_path = safe_directory or str(cwd.resolve())
    try:
        result = subprocess.run(
            [
                "git", "--no-pager",
                "-c", "color.ui=false",
                "-c", f"safe.directory={trusted_path}",
                *args,
            ],
            cwd=str(cwd),
            capture_output=True,
            timeout=120,
            text=True,
            errors="replace",
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except FileNotFoundError:
        return _deny("git executable not found")
    except subprocess.TimeoutExpired:
        return _deny("git command timed out after 120s")
    stdout = (result.stdout or "")[:limit]
    stderr = (result.stderr or "")[:8000]
    if result.returncode:
        return {
            "ok": False,
            "code": result.returncode,
            "error": (stderr or stdout or "git command failed").strip(),
        }
    response = {"ok": True, "stdout": stdout}
    if stderr:
        response["stderr"] = stderr
    return response


def _git_repository(policy, raw_cwd: str) -> tuple[pathlib.Path | None, dict | None]:
    cwd = _abs(raw_cwd)
    verdict = policy.check_path(str(cwd))
    if not verdict:
        return None, _deny(verdict.reason)
    verdict = policy.check_command("git")
    if not verdict:
        return None, _deny(verdict.reason)
    if not cwd.is_dir():
        return None, _deny(f"not a dir: {cwd}")

    # FAT/exFAT has no ownership metadata, so trust only for discovery and
    # validate the resolved repository root before running any requested action.
    probe = _run_git(
        cwd,
        ["rev-parse", "--show-toplevel"],
        limit=4000,
        safe_directory="*",
    )
    if not probe["ok"]:
        detail = probe.get("error", "not a git repository")
        return None, _deny(f"not a git repository: {detail}")
    root = pathlib.Path(probe["stdout"].strip()).resolve()
    verdict = policy.check_path(str(root))
    if not verdict:
        return None, _deny(verdict.reason)
    return root, None


def git_status(policy, args: dict) -> dict:
    root, error = _git_repository(policy, args.get("cwd", "."))
    if error:
        return error
    result = _run_git(root, ["status", "--short", "--branch"], limit=20000)
    if not result["ok"]:
        return result
    return {"ok": True, "repo": str(root), "status": result["stdout"]}


def git_diff(policy, args: dict) -> dict:
    staged = args.get("staged", False)
    if not isinstance(staged, bool):
        return _deny("staged must be a boolean")
    root, error = _git_repository(policy, args.get("cwd", "."))
    if error:
        return error
    command = ["diff"]
    if staged:
        command.append("--cached")
    result = _run_git(root, command)
    if not result["ok"]:
        return result
    return {
        "ok": True,
        "repo": str(root),
        "staged": staged,
        "diff": result["stdout"],
    }


def git_commit(policy, args: dict) -> dict:
    message = args.get("message")
    if not isinstance(message, str) or not message.strip():
        return _deny("commit message is required")
    root, error = _git_repository(policy, args.get("cwd", "."))
    if error:
        return error
    result = _run_git(root, ["commit", "-m", message.strip()], limit=20000)
    if not result["ok"]:
        return result
    return {"ok": True, "repo": str(root), "output": result["stdout"]}


def git_log(policy, args: dict) -> dict:
    limit = args.get("limit", 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        return _deny("limit must be an integer between 1 and 100")
    root, error = _git_repository(policy, args.get("cwd", "."))
    if error:
        return error
    result = _run_git(
        root,
        ["log", "--oneline", "--decorate", f"-n{limit}"],
        limit=20000,
    )
    if not result["ok"]:
        return result
    return {"ok": True, "repo": str(root), "log": result["stdout"]}


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
    "edit_file": edit_file, "apply_patch": apply_patch,
    "list_dir": list_dir, "grep": grep, "shell": shell,
    "run_python": run_python,
    "git_status": git_status, "git_diff": git_diff,
    "git_commit": git_commit, "git_log": git_log,
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
