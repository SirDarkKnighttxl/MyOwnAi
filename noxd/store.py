"""SQLite: sessions, messages, corpus chunks."""
from __future__ import annotations

import pathlib
import sqlite3
import time

DB = pathlib.Path(__file__).resolve().parent.parent / "nox.db"


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE IF NOT EXISTS sessions(
            id INTEGER PRIMARY KEY, title TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY, session INTEGER, role TEXT,
            content TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS chunks(
            id INTEGER PRIMARY KEY, path TEXT, text TEXT, vec TEXT);
        CREATE INDEX IF NOT EXISTS idx_msg_sess ON messages(session);
    """)
    return c


def new_session(title: str = "untitled") -> int:
    with conn() as c:
        cur = c.execute("INSERT INTO sessions(title, created) VALUES(?,?)",
                        (title[:80], time.time()))
        return cur.lastrowid


def list_sessions() -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT s.id, s.title, s.created, COUNT(m.id) n "
            "FROM sessions s LEFT JOIN messages m ON m.session=s.id "
            "GROUP BY s.id ORDER BY s.created DESC LIMIT 100").fetchall()
    return [dict(r) for r in rows]


def rename(sid: int, title: str) -> None:
    with conn() as c:
        c.execute("UPDATE sessions SET title=? WHERE id=?", (title[:80], sid))


def delete(sid: int) -> None:
    with conn() as c:
        c.execute("DELETE FROM messages WHERE session=?", (sid,))
        c.execute("DELETE FROM sessions WHERE id=?", (sid,))


def add_msg(sid: int, role: str, content: str) -> None:
    with conn() as c:
        c.execute("INSERT INTO messages(session, role, content, created) VALUES(?,?,?,?)",
                  (sid, role, content, time.time()))


def get_msgs(sid: int) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT role, content FROM messages WHERE session=? ORDER BY id", (sid,)).fetchall()
    return [dict(r) for r in rows]
