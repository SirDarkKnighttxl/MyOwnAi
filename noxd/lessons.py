"""policy/lessons.md as an indexed list: one lesson per line.

File format:
- A lesson is any non-blank line that is not a Markdown header (`#...`) and
  not inside an HTML comment (`<!-- ... -->`). A leading `- ` or `* ` bullet
  is display-only and stripped from the lesson text.
- Headers, comments and blank lines are never indexed and are kept exactly
  as written; edits only touch the lesson's own line.
- Indices are 0-based, in file order, and renumber after a delete (lesson
  i+1 becomes lesson i).

Writes are atomic (temp file in the same folder + os.replace) and keep the
file's existing line endings (CRLF stays CRLF on Windows; a new file uses LF).
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import threading

PATH = pathlib.Path(__file__).resolve().parent.parent / "policy" / "lessons.md"
_lock = threading.Lock()


def _path(path: pathlib.Path | None) -> pathlib.Path:
    return pathlib.Path(path) if path is not None else PATH


def _read(path: pathlib.Path) -> tuple[list[str], str]:
    """Return raw lines (no line endings) and the file's newline style."""
    try:
        raw = path.read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return [], "\n"
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # trailing newline, not an empty last line
    return lines, newline


def _write(path: pathlib.Path, lines: list[str], newline: str) -> None:
    data = (newline.join(lines) + newline if lines else "").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _lesson_lines(lines: list[str]) -> list[tuple[int, str]]:
    """(line number, lesson text) for every indexable line."""
    out, in_comment = [], False
    for n, line in enumerate(lines):
        s = line.strip()
        if in_comment:
            if "-->" in s:
                in_comment = False
            continue
        if not s or s.startswith("#"):
            continue
        if s.startswith("<!--"):
            in_comment = "-->" not in s[4:]
            continue
        if s[:2] in ("- ", "* "):
            s = s[2:].strip()
        if s:
            out.append((n, s))
    return out


def _clean(text: str) -> str:
    text = " ".join(str(text).split())  # one line, no stray CR/LF/tabs
    if not text:
        raise ValueError("lesson text is empty")
    return text


def list_lessons(path: pathlib.Path | None = None) -> list[dict]:
    lines, _ = _read(_path(path))
    return [{"index": i, "text": t} for i, (_, t) in enumerate(_lesson_lines(lines))]


def add(text: str, path: pathlib.Path | None = None) -> dict:
    text = _clean(text)
    p = _path(path)
    with _lock:
        lines, newline = _read(p)
        lines.append(f"- {text}")
        _write(p, lines, newline)
        index = len(_lesson_lines(lines)) - 1
    return {"index": index, "text": text}


def update(index: int, text: str, path: pathlib.Path | None = None) -> dict:
    text = _clean(text)
    p = _path(path)
    with _lock:
        lines, newline = _read(p)
        found = _lesson_lines(lines)
        if not 0 <= index < len(found):
            raise IndexError(index)
        lines[found[index][0]] = f"- {text}"
        _write(p, lines, newline)
    return {"index": index, "text": text}


def delete(index: int, path: pathlib.Path | None = None) -> dict:
    p = _path(path)
    with _lock:
        lines, newline = _read(p)
        found = _lesson_lines(lines)
        if not 0 <= index < len(found):
            raise IndexError(index)
        line_no, text = found[index]
        del lines[line_no]
        _write(p, lines, newline)
    return {"index": index, "text": text}


def prompt_block(path: pathlib.Path | None = None) -> str:
    """Lessons section for the system prompt; read from disk on every call."""
    items = list_lessons(path)
    if not items:
        return ""
    return "LESSONS\n" + "\n".join(f"- {item['text']}" for item in items)
