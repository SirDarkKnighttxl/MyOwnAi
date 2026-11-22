"""Portable GGUF discovery and model metadata."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def resolve(raw: str) -> pathlib.Path:
    path = pathlib.Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def path_key(path: pathlib.Path | str) -> str:
    return str(pathlib.Path(path).resolve()).casefold()


def config_path(path: pathlib.Path) -> str:
    path = path.resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def roots(config: dict) -> list[pathlib.Path]:
    found = []
    seen = set()
    for raw in config.get("model", {}).get("paths", []):
        path = resolve(raw)
        root = path.parent if path.suffix.lower() == ".gguf" else path
        key = path_key(root)
        if key not in seen:
            seen.add(key)
            found.append(root)
    return found


TRAINED_PREFIX = "nox-"  # train/export_gguf.py writes models/nox-<name>.Q4_K_M.gguf
ROLES = {"stock", "ablit", "trained"}


def metadata(path: pathlib.Path, roles: dict | None = None) -> dict:
    """Role resolution: embedding names first, then an explicit nox.json
    `model.roles` {filename: role} entry, then the `nox-` prefix (our own
    trained exports, e.g. nox-ablit is trained, not the downloaded ablit),
    then the legacy name heuristics."""
    name = path.name
    lower = name.lower()
    mapped = {str(k).casefold(): v for k, v in (roles or {}).items() if v in ROLES}
    embedding = "embed" in lower or "nomic" in lower
    if embedding:
        role = None
        kind = "embedding"
    elif lower in mapped:
        role = mapped[lower]
        kind = "chat"
    elif lower.startswith(TRAINED_PREFIX):
        role = "trained"
        kind = "chat"
    elif "ablit" in lower:
        role = "ablit"
        kind = "chat"
    elif lower == "qwen3-8b-q4_k_m.gguf":
        role = "stock"
        kind = "chat"
    else:
        role = "trained"
        kind = "chat"
    try:
        portable = path.resolve().is_relative_to(ROOT)
    except (OSError, ValueError):
        portable = False
    return {
        "name": name,
        "path": str(path.resolve()),
        "config_path": config_path(path),
        "bytes": path.stat().st_size,
        "role": role,
        "kind": kind,
        "loadable": not embedding,
        "location": "portable" if portable else "fast",
    }


def discover(config: dict, loaded_path: str | None = None) -> list[dict]:
    loaded_key = path_key(loaded_path) if loaded_path else None
    role_map = config.get("model", {}).get("roles") or {}
    results = []
    seen = set()
    for root in roots(config):
        if not root.is_dir():
            continue
        for path in root.glob("*.gguf"):
            key = path_key(path)
            if key in seen or not path.is_file():
                continue
            seen.add(key)
            try:
                item = metadata(path, role_map)
            except OSError:
                continue
            item["active"] = key == loaded_key
            results.append(item)
    return sorted(
        results,
        key=lambda item: (
            not item["active"],
            item["kind"] != "chat",
            item["role"] or "",
            item["name"].lower(),
            item["location"],
        ),
    )


def select(config: dict, requested_path: str) -> dict | None:
    requested_key = path_key(resolve(requested_path))
    for item in discover(config):
        if path_key(item["path"]) == requested_key:
            return item
    return None
