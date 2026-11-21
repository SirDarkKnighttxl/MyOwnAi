"""In-memory command approval queue for the local UI."""
from __future__ import annotations

import asyncio
import time
import uuid

DECISIONS = {"allow", "deny", "allow-session"}


class ApprovalBroker:
    def __init__(self) -> None:
        self._pending: dict[str, dict] = {}

    async def request(self, command: str, cwd: str, binary: str) -> str:
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = {
            "id": request_id,
            "command": command,
            "cwd": cwd,
            "binary": binary,
            "created": time.time(),
            "future": future,
        }
        try:
            return await future
        finally:
            self._pending.pop(request_id, None)

    def list(self) -> list[dict]:
        pending = sorted(self._pending.values(), key=lambda item: item["created"])
        return [
            {key: value for key, value in item.items() if key != "future"}
            for item in pending
        ]

    def resolve(self, request_id: str, decision: str) -> bool:
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
        item = self._pending.get(request_id)
        if item is None or item["future"].done():
            return False
        item["future"].set_result(decision)
        return True

    def reset(self) -> None:
        for item in self._pending.values():
            future = item["future"]
            if not future.done():
                future.cancel()
        self._pending.clear()


broker = ApprovalBroker()
