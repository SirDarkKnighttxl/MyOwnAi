import unittest
from unittest.mock import patch

from noxd import agent


SAMPLING = {
    "temp": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "min_p": 0.05,
    "repeat_penalty": 1.05,
    "max_tokens": 128,
}


class FakeResponse:
    def __init__(self, message):
        self.message = message

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": self.message}]}


class FakeClient:
    def __init__(self, message):
        self.message = message
        self.payload = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, _url, json):
        self.payload = json
        return FakeResponse(self.message)


class ThinkingTests(unittest.IsolatedAsyncioTestCase):
    async def run_agent(self, message, think):
        client = FakeClient(message)
        with patch.object(agent.httpx, "AsyncClient", return_value=client):
            text = await agent.run(
                policy=None,
                base_url="http://engine",
                messages=[{"role": "user", "content": "test"}],
                sampling=SAMPLING,
                on_event=lambda _event: None,
                think=think,
            )
        return text, client.payload

    async def test_enabled_reasoning_is_renderable(self):
        text, payload = await self.run_agent(
            {"content": "Answer", "reasoning_content": "Internal work"},
            think=True,
        )

        self.assertEqual(
            text,
            "<think>\nInternal work\n</think>\n\nAnswer",
        )
        self.assertIs(payload["chat_template_kwargs"]["enable_thinking"], True)
        self.assertNotIn("reasoning_effort", payload)

    async def test_disabled_reasoning_is_tag_free(self):
        text, payload = await self.run_agent(
            {
                "content": "<think>\nInternal work\n</think>\n\nAnswer",
                "reasoning_content": "Internal work",
            },
            think=False,
        )

        self.assertEqual(text, "Answer")
        self.assertNotIn("</think>", text)
        self.assertIs(payload["chat_template_kwargs"]["enable_thinking"], False)
        self.assertEqual(payload["reasoning_effort"], "none")

    def test_raw_reasoning_block_is_not_duplicated(self):
        message = {"content": "<think>\nWork\n</think>\n\nAnswer", "reasoning_content": "Work"}
        self.assertEqual(agent._response_text(message, True), message["content"])


if __name__ == "__main__":
    unittest.main()
