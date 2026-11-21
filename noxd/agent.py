"""Tool-calling loop."""
from __future__ import annotations

import json
import pathlib

import httpx

from . import tools

MAX_STEPS = 12
SCRATCH = pathlib.Path(__file__).resolve().parent.parent / "work" / "scratchpad.md"


def _response_text(message: dict, think: bool) -> str:
    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or ""

    if not think:
        # Some models can emit a raw reasoning suffix even when their template
        # was prefilled for no-think mode. Keep the UI contract tag-free.
        if "</think>" in content:
            return content.rsplit("</think>", 1)[1].lstrip()
        if "<think>" in content:
            return content.split("<think>", 1)[0].rstrip()
        return content

    if reasoning and "</think>" not in content:
        answer = f"\n\n{content.lstrip()}" if content else ""
        return f"<think>\n{reasoning.strip()}\n</think>{answer}"
    return content


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
    if not think:
        payload["reasoning_effort"] = "none"

    async with httpx.AsyncClient(timeout=600) as client:
        for step in range(MAX_STEPS):
            r = await client.post(f"{base_url}/v1/chat/completions", json=payload)
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            calls = msg.get("tool_calls") or []

            if not calls:
                return _response_text(msg, think)

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
