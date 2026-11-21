"""Tool-calling loop."""
from __future__ import annotations

import json
import pathlib

import httpx

from . import tools

MAX_STEPS = 12
SCRATCH = pathlib.Path(__file__).resolve().parent.parent / "work" / "scratchpad.md"


async def run(policy, base_url: str, messages: list, sampling: dict, on_event, think: bool = True) -> str:
    if SCRATCH.exists():
        plan = SCRATCH.read_text(encoding="utf-8", errors="replace")[:4000]
        if plan.strip():
            messages = messages + [{"role": "system",
                                    "content": "Current plan (scratchpad):\n" + plan}]

    payload = {
        "messages": messages,
        "stream": False,
        "temperature": sampling["temp"],
        "top_p": sampling["top_p"],
        "top_k": sampling["top_k"],
        "min_p": sampling["min_p"],
        "repeat_penalty": sampling["repeat_penalty"],
        "max_tokens": sampling["max_tokens"],
        "tools": tools.SCHEMA,
        "chat_template_kwargs": {"enable_thinking": think},
    }

    async with httpx.AsyncClient(timeout=600) as client:
        for step in range(MAX_STEPS):
            r = await client.post(f"{base_url}/v1/chat/completions", json=payload)
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            calls = msg.get("tool_calls") or []

            if not calls:
                return msg.get("content") or ""

            payload["messages"].append(msg)
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"]["arguments"] or "{}")
                except ValueError:
                    args = {}
                on_event({"tool": name, "args": args})
                result = tools.dispatch(policy, name, args)
                on_event({"tool_result": name, "ok": result.get("ok"), "result": result})
                payload["messages"].append({
                    "role": "tool", "tool_call_id": call.get("id", ""),
                    "name": name, "content": json.dumps(result)[:20000],
                })

    return "[stopped: max tool steps]"
