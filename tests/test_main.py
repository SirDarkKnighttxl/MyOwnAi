import types
import unittest
from unittest.mock import patch

from noxd import main


class FakeRequest:
    async def json(self):
        return {
            "messages": [{"role": "user", "content": "corpus question"}],
            "rag": True,
            "think": False,
        }


class RagInjectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rag_context_precedes_conversation_history(self):
        captured = {}

        async def fake_run(_policy, _url, messages, _sampling, _on_event, _think):
            captured["messages"] = messages
            return "done"

        fake_engine = types.SimpleNamespace(ready=True, error=None, port=8081)
        with (
            patch.object(main, "engine", fake_engine),
            patch.object(main, "policy", object()),
            patch.object(main, "persona", return_value="PERSONA"),
            patch.object(main.rag, "context", return_value="CORPUS EXCERPT"),
            patch.object(main.agent, "run", side_effect=fake_run),
        ):
            response = await main.chat(FakeRequest())
            async for _chunk in response.body_iterator:
                pass

        self.assertEqual(
            captured["messages"],
            [
                {"role": "system", "content": "PERSONA\n\nCORPUS EXCERPT"},
                {"role": "user", "content": "corpus question"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
