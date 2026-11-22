import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from noxd import lessons, main

SAMPLE = (
    "# Lessons\r\n"
    "<!-- one lesson per line -->\r\n"
    "\r\n"
    "- first\r\n"
    "- second\r\n"
    "<!--\r\n"
    "- not a lesson\r\n"
    "-->\r\n"
    "third without bullet\r\n"
)


class LessonsTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        self.path = self.dir / "lessons.md"
        self.path.write_bytes(SAMPLE.encode("utf-8"))
        patcher = patch.object(main, "LESSONS", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        # No `with`: the startup hook (engine boot) must not run in tests.
        self.client = TestClient(main.app)

    def texts(self):
        return [item["text"] for item in self.client.get("/api/lessons").json()["lessons"]]


class LessonsApiTests(LessonsTestCase):
    def test_list_skips_headers_comments_and_blanks(self):
        body = self.client.get("/api/lessons").json()
        self.assertEqual(body["lessons"], [
            {"index": 0, "text": "first"},
            {"index": 1, "text": "second"},
            {"index": 2, "text": "third without bullet"},
        ])

    def test_edit_replaces_only_that_line(self):
        r = self.client.put("/api/lessons/1", json={"text": "second, edited"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.texts(), ["first", "second, edited", "third without bullet"])
        self.assertEqual(self.path.read_bytes().decode(), SAMPLE.replace("- second\r\n", "- second, edited\r\n"))

    def test_delete_removes_line_and_keeps_headers(self):
        r = self.client.delete("/api/lessons/0")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["text"], "first")
        raw = self.path.read_bytes().decode()
        self.assertNotIn("- first", raw)
        self.assertTrue(raw.startswith("# Lessons\r\n<!-- one lesson per line -->\r\n"))
        self.assertIn("- not a lesson", raw)

    def test_add_appends_with_existing_line_endings(self):
        r = self.client.post("/api/lessons", json={"text": "  fourth\nline  "})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["index"], 3)
        self.assertEqual(self.texts()[-1], "fourth line")
        raw = self.path.read_bytes()
        self.assertTrue(raw.endswith(b"- fourth line\r\n"))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))  # no bare LF mixed in

    def test_add_creates_missing_file_with_lf(self):
        self.path.unlink()
        self.client.post("/api/lessons", json={"text": "fresh"})
        self.assertEqual(self.path.read_bytes(), b"- fresh\n")

    def test_indices_renumber_after_delete_and_out_of_range_is_404(self):
        self.client.delete("/api/lessons/0")
        body = self.client.get("/api/lessons").json()["lessons"]
        self.assertEqual(body, [{"index": 0, "text": "second"},
                                {"index": 1, "text": "third without bullet"}])
        self.assertEqual(self.client.put("/api/lessons/2", json={"text": "x"}).status_code, 404)
        self.assertEqual(self.client.delete("/api/lessons/2").status_code, 404)
        self.assertEqual(self.client.delete("/api/lessons/-1").status_code, 404)
        self.assertEqual(self.texts(), ["second", "third without bullet"])

    def test_empty_text_is_rejected(self):
        self.assertEqual(self.client.post("/api/lessons", json={"text": "  "}).status_code, 400)
        self.assertEqual(self.client.put("/api/lessons/0", json={}).status_code, 400)
        self.assertEqual(self.texts(), ["first", "second", "third without bullet"])

    def test_write_is_atomic_and_leaves_no_temp_files(self):
        with patch.object(lessons.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                lessons.update(0, "never written", self.path)
        self.assertEqual(self.path.read_bytes().decode(), SAMPLE)
        self.client.post("/api/lessons", json={"text": "ok"})
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["lessons.md"])


class FakeRequest:
    async def json(self):
        return {"messages": [{"role": "user", "content": "hi"}], "rag": False, "think": False}


class LessonsReachPromptTests(LessonsTestCase):
    def test_added_lesson_is_in_persona(self):
        self.client.post("/api/lessons", json={"text": "brand new lesson"})
        self.assertIn("- brand new lesson", main.persona())
        self.assertNotIn("not a lesson", main.persona())

    def test_added_lesson_reaches_next_chat_system_prompt(self):
        persona_file = self.dir / "persona.md"
        persona_file.write_text("PERSONA", encoding="utf-8")
        captured = []

        async def fake_run(_policy, _url, messages, _sampling, _on_event, _think):
            captured.append(messages[0]["content"])
            return "done"

        async def run_chat():
            response = await main.chat(FakeRequest())
            async for _chunk in response.body_iterator:
                pass

        fake_engine = types.SimpleNamespace(ready=True, error=None, port=8081)
        with (
            patch.object(main, "PERSONA", persona_file),
            patch.object(main, "engine", fake_engine),
            patch.object(main, "policy", object()),
            patch.object(main.agent, "run", side_effect=fake_run),
        ):
            import asyncio
            asyncio.run(run_chat())
            self.client.post("/api/lessons", json={"text": "use the new lesson"})
            asyncio.run(run_chat())

        self.assertNotIn("use the new lesson", captured[0])
        self.assertIn("- use the new lesson", captured[1])
        self.assertTrue(captured[1].startswith("PERSONA\n\nLESSONS\n- first"))


if __name__ == "__main__":
    unittest.main()
