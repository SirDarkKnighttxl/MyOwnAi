import io
import json
import math
import pathlib
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from unittest.mock import patch

from noxd import rag, store


def unit_vector(score):
    return [score, math.sqrt(1 - score * score)]


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, _query):
        return self

    def fetchall(self):
        return self.rows


class RetrievalFloorTests(unittest.TestCase):
    def test_search_rejects_scores_below_floor(self):
        rows = [
            {"path": "high", "text": "high", "vec": json.dumps(unit_vector(0.70))},
            {"path": "floor", "text": "floor", "vec": json.dumps(unit_vector(rag.MIN_SCORE))},
            {"path": "low", "text": "low", "vec": json.dumps(unit_vector(0.59))},
        ]

        with (
            patch.object(rag, "embed", return_value=[1.0, 0.0]),
            patch.object(rag, "ensure", return_value=True),
            patch.object(rag, "session", return_value=FakeConnection(rows)),
        ):
            hits = rag.search("query")

        self.assertEqual([hit["path"] for hit in hits], ["high", "floor"])

    def test_context_is_empty_for_off_corpus_query(self):
        rows = [
            {"path": "noise", "text": "noise", "vec": json.dumps(unit_vector(0.59))},
        ]

        with (
            patch.object(rag, "embed", return_value=[1.0, 0.0]),
            patch.object(rag, "ensure", return_value=True),
            patch.object(rag, "session", return_value=FakeConnection(rows)),
        ):
            self.assertEqual(rag.context("off topic"), "")

    def test_search_calls_ensure_first(self):
        order = []
        with (
            patch.object(rag, "ensure", side_effect=lambda: order.append("ensure") or True),
            patch.object(rag, "embed", side_effect=lambda q: order.append("embed") or [1.0, 0.0]),
            patch.object(rag, "session", return_value=FakeConnection([])),
        ):
            rag.search("query")
        self.assertEqual(order, ["ensure", "embed"])

    def test_search_reports_dead_server_instead_of_embedding(self):
        with (
            patch.object(rag, "ensure", return_value=False),
            patch.object(rag, "embed") as fake_embed,
            patch("builtins.print") as fake_print,
        ):
            self.assertEqual(rag.search("query"), [])
        fake_embed.assert_not_called()
        logged = " ".join(str(call.args[0]) for call in fake_print.call_args_list)
        self.assertIn("embedding server unavailable", logged)


REA_SCOPE = f"rea|filter={rag.FILTER_VERSION}"


class Interrupted(BaseException):
    """Stands in for Ctrl+C / a killed process mid-run."""


def candidate_text(n):
    return f"candidate {n:02d} " + "lorem ipsum dolor sit amet " * 6


class EmbedRetryTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        patcher = patch.object(rag, "_sleep", side_effect=self.sleeps.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_success_on_second_attempt(self):
        with patch.object(rag, "embed", side_effect=[None, [1.0]]) as fake:
            self.assertEqual(rag.embed_retry("x"), [1.0])
        self.assertEqual(fake.call_count, 2)
        self.assertEqual(self.sleeps, [0.5])

    def test_success_on_third_attempt(self):
        with patch.object(rag, "embed", side_effect=[None, None, [1.0]]) as fake:
            self.assertEqual(rag.embed_retry("x"), [1.0])
        self.assertEqual(fake.call_count, 3)
        self.assertEqual(self.sleeps, [0.5, 1.5])

    def test_none_after_three_failures(self):
        with patch.object(rag, "embed", return_value=None) as fake:
            self.assertIsNone(rag.embed_retry("x"))
        self.assertEqual(fake.call_count, 3)
        self.assertEqual(self.sleeps, [0.5, 1.5])


class ResumableIndexTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = pathlib.Path(tmp.name)
        self.root = base / "corpus"
        self.make_repo("rea", range(1, 11))
        self.make_repo("payloads", range(90, 93))
        self.db = base / "nox.db"
        self.calls = []
        for patcher in (
            patch.object(store, "DB", self.db),
            patch.object(rag, "ensure", return_value=True),
            patch.object(rag, "_sleep"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_repo(self, name, numbers):
        repo = self.root / name
        repo.mkdir(parents=True)
        for n in numbers:
            (repo / f"c{n:02d}.md").write_text(candidate_text(n), encoding="utf-8")

    def fake_embed(self, failing=(), interrupt_at=None):
        def embed(text):
            n = int(re.match(r"candidate (\d+)", text).group(1))
            self.calls.append(n)
            if n == interrupt_at:
                raise Interrupted()
            if n in failing:
                return None
            return [float(n), 1.0]
        return embed

    def rows(self):
        with closing(sqlite3.connect(self.db)) as c:
            texts = [r[0] for r in c.execute("SELECT text FROM chunks ORDER BY id")]
        return [int(re.match(r"candidate (\d+)", t).group(1)) for t in texts]

    def state(self):
        with closing(sqlite3.connect(self.db)) as c:
            return c.execute(
                "SELECT next_candidate, skipped, scope FROM index_state").fetchall()

    def test_resume_continues_from_sqlite_cursor(self):
        with patch.object(rag, "embed", side_effect=self.fake_embed({3}, interrupt_at=6)):
            with self.assertRaises(Interrupted):
                rag.index(self.root, 100, ["rea"])
        self.assertEqual(self.rows(), [1, 2, 4, 5])
        self.assertEqual(self.state(), [(5, 1, REA_SCOPE)])

        self.calls.clear()
        with patch.object(rag, "embed", side_effect=self.fake_embed({3})):
            result = rag.index(self.root, 100, ["rea"], resume=True)

        self.assertEqual(self.calls[0], 6)
        self.assertNotIn(3, self.calls)
        self.assertEqual(self.rows(), [1, 2, 4, 5, 6, 7, 8, 9, 10])
        self.assertTrue(result["ok"])
        self.assertEqual(result["chunks"], 5)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.state(), [(10, 1, REA_SCOPE)])

    def test_resume_ignores_row_count(self):
        with patch.object(rag, "embed", side_effect=self.fake_embed({3})):
            rag.index(self.root, 4, ["rea"])
        self.assertEqual(self.rows(), [1, 2, 4, 5])
        self.calls.clear()
        with patch.object(rag, "embed", side_effect=self.fake_embed()):
            rag.index(self.root, 1, ["rea"], resume=True)
        # 4 rows exist, but the cursor (5) decides where to start.
        self.assertEqual(self.calls, [6])

    def test_resume_false_clears_rows_and_state(self):
        with patch.object(rag, "embed", side_effect=self.fake_embed({3})):
            rag.index(self.root, 4, ["rea"])
        self.calls.clear()
        with patch.object(rag, "embed", side_effect=self.fake_embed()):
            result = rag.index(self.root, 2, ["rea"], resume=False)
        self.assertEqual(self.calls, [1, 2])
        self.assertEqual(self.rows(), [1, 2])
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(self.state(), [(2, 0, REA_SCOPE)])

    def test_aborts_after_max_consecutive_failures(self):
        with (
            patch.object(rag, "MAX_CONSEC_FAIL", 3),
            patch.object(rag, "embed", side_effect=self.fake_embed({3, 4, 5})),
        ):
            result = rag.index(self.root, 100, ["rea"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"].startswith("3 consecutive embed failures"))
        self.assertEqual(result["chunks"], 2)
        self.assertEqual(result["consec"], 3)
        self.assertNotIn(6, self.calls)
        self.assertEqual(self.rows(), [1, 2])
        # The failing run is not committed, so a resume retries it.
        self.assertEqual(self.state(), [(2, 0, REA_SCOPE)])

    def test_consecutive_counter_resets_on_success(self):
        with (
            patch.object(rag, "MAX_CONSEC_FAIL", 2),
            patch.object(rag, "embed", side_effect=self.fake_embed({2, 4, 6, 8})),
        ):
            result = rag.index(self.root, 100, ["rea"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["skipped"], 4)
        self.assertEqual(self.rows(), [1, 3, 5, 7, 9, 10])

    def test_repo_filter_limits_candidates(self):
        with patch.object(rag, "embed", side_effect=self.fake_embed()):
            rag.index(self.root, 100, ["payloads"])
        self.assertEqual(self.rows(), [90, 91, 92])

    def test_resume_rejects_different_repo_filter(self):
        with patch.object(rag, "embed", side_effect=self.fake_embed()):
            rag.index(self.root, 2, ["rea"])
            result = rag.index(self.root, 2, ["payloads"], resume=True)
        self.assertFalse(result["ok"])
        self.assertEqual(self.rows(), [1, 2])

    def test_resume_refused_after_file_filter_change(self):
        with patch.object(rag, "embed", side_effect=self.fake_embed()):
            rag.index(self.root, 2, ["rea", "ciphey"])
            with patch.object(rag, "FILTER_VERSION", rag.FILTER_VERSION + 1):
                result = rag.index(self.root, 1500, ["rea", "ciphey"], resume=True)
        self.assertFalse(result["ok"])
        self.assertIn("Run `python index_corpus.py 1500 rea,ciphey` without --resume.",
                      result["error"])
        self.assertEqual(self.rows(), [1, 2])

    def test_skip_line_and_abort_carry_last_embed_error(self):
        def failing(_text):
            rag._last_error = "HTTP 500: input is too large to process"
            return None
        with (
            patch.object(rag, "MAX_CONSEC_FAIL", 2),
            patch.object(rag, "embed", side_effect=failing),
            patch("builtins.print") as fake_print,
        ):
            result = rag.index(self.root, 100, ["rea"])
        self.assertIn("input is too large", result["error"])
        logged = " ".join(str(call.args[0]) for call in fake_print.call_args_list)
        self.assertIn("skip", logged)
        self.assertIn("input is too large", logged)

    def test_long_chunk_is_logged(self):
        with (
            patch.object(rag, "LONG_CHUNK", 50),
            patch.object(rag, "embed", side_effect=self.fake_embed()),
            patch("builtins.print") as fake_print,
        ):
            rag.index(self.root, 1, ["rea"])
        logged = " ".join(str(call.args[0]) for call in fake_print.call_args_list)
        self.assertIn("long chunk", logged)

    def test_progress_line_reports_counters(self):
        with (
            patch.object(rag, "PROGRESS_EVERY", 2),
            patch.object(rag, "embed", side_effect=self.fake_embed({3})),
            patch("builtins.print") as fake_print,
        ):
            rag.index(self.root, 4, ["rea"])
        logged = [str(call.args[0]) for call in fake_print.call_args_list]
        self.assertIn("  4 chunks done=4 skipped=1 consec=0", logged)


class ConnectionLeakTests(unittest.TestCase):
    """Windows can't delete an open nox.db; on Linux, count unclosed handles instead."""

    def test_index_search_and_store_close_every_connection(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = pathlib.Path(tmp.name)
        repo = base / "corpus" / "rea"
        repo.mkdir(parents=True)
        for n in (1, 2, 3):
            (repo / f"c{n:02d}.md").write_text(candidate_text(n), encoding="utf-8")

        opened = []
        real_connect = sqlite3.connect

        class TrackedConnection(sqlite3.Connection):
            closed = False

            def close(self):
                self.closed = True
                super().close()

        def tracking_connect(*args, **kwargs):
            c = real_connect(*args, factory=TrackedConnection, **kwargs)
            opened.append(c)
            return c

        with (
            patch.object(store, "DB", base / "nox.db"),
            patch.object(store.sqlite3, "connect", side_effect=tracking_connect),
            patch.object(rag, "ensure", return_value=True),
            patch.object(rag, "_sleep"),
            patch.object(rag, "embed", side_effect=lambda text: [1.0, 0.0] if "02" not in text[:12] else None),
        ):
            rag.index(base / "corpus", 10, ["rea"])
            rag.index(base / "corpus", 10, ["rea"], resume=True)
            rag.search("query")
            sid = store.new_session("t")
            store.add_msg(sid, "user", "hi")
            store.get_msgs(sid)
            store.list_sessions()
            store.delete(sid)
            with self.assertRaises(Interrupted):
                with store.session():
                    raise Interrupted()

        self.assertGreaterEqual(len(opened), 9)
        self.assertEqual([c for c in opened if not c.closed], [])


class CorpusFilterTests(unittest.TestCase):
    def test_dumps_wordlists_images_and_long_lines_are_excluded(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name) / "corpus"
        files = {
            "ciphey/README.md": "usage\n",
            "ciphey/docs/guide.md": "guide\n",
            "ciphey/images/repomix-output.txt": "dump\n",
            "ciphey/images/notes.md": "image notes\n",
            "ciphey/benches/data/wordlist.txt": "aaciv\n",
            "ciphey/tests/fixtures/sample.json": "{}\n",
            "rea/dist.min.json": "{}\n",
            "rea/svg.md": "<svg " + "x" * 3000 + ">\n",
            "rea/edge.md": "y" * 1000 + "\n",
            "rea/docs/cli.md": "rea --help\n",
            "images/top.md": "repo literally named images\n",
        }
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        kept = [f.relative_to(root).as_posix() for f in rag._files(root, None)]
        self.assertEqual(kept, ["ciphey/README.md", "ciphey/docs/guide.md",
                                "images/top.md", "rea/docs/cli.md", "rea/edge.md"])

    def test_file_with_5000_char_line_is_excluded_and_logged(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name) / "corpus"
        (root / "rea" / "docs").mkdir(parents=True)
        (root / "rea" / "docs" / "cli.md").write_text("rea usage\n", encoding="utf-8")
        (root / "rea" / "blob.md").write_text("short\n" + "z" * 5000 + "\nshort\n",
                                              encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            kept = [f.relative_to(root).as_posix() for f in rag._files(root, ["rea"])]
        self.assertEqual(kept, ["rea/docs/cli.md"])
        self.assertIn("skip long-line rea/blob.md longest=5000", out.getvalue().splitlines())


class EmbedServerStartTests(unittest.TestCase):
    def test_ensure_sets_batch_flags_and_logs_stderr(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = pathlib.Path(tmp.name)
        model = base / "embed.gguf"
        model.write_bytes(b"")
        log = base / "logs" / "embed.log"
        with (
            patch.object(rag, "_up", side_effect=[False, True]),
            patch.object(rag, "EMBED", model),
            patch.object(rag, "LOG", log),
            patch.object(rag.subprocess, "Popen") as popen,
        ):
            self.assertTrue(rag.ensure())
        args = popen.call_args.args[0]
        self.assertEqual(args[args.index("-b") + 1], "2048")
        self.assertEqual(args[args.index("-ub") + 1], "2048")
        self.assertEqual(args[args.index("-c") + 1], "2048")
        kwargs = popen.call_args.kwargs
        self.assertEqual(kwargs["stderr"], rag.subprocess.STDOUT)
        self.assertEqual(pathlib.Path(kwargs["stdout"].name), log)
        self.assertIn("-ub 2048", log.read_text(encoding="utf-8"))

    def test_embed_records_http_error(self):
        response = type("R", (), {"status_code": 500, "text": "input is too large"})()
        with patch.object(rag.httpx, "post", return_value=response):
            self.assertIsNone(rag.embed("x"))
        self.assertEqual(rag._last_error, "HTTP 500: input is too large")


if __name__ == "__main__":
    unittest.main()
