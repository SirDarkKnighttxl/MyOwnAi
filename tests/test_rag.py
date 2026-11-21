import json
import math
import unittest
from unittest.mock import patch

from noxd import rag


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
            patch.object(rag, "conn", return_value=FakeConnection(rows)),
        ):
            hits = rag.search("query")

        self.assertEqual([hit["path"] for hit in hits], ["high", "floor"])

    def test_context_is_empty_for_off_corpus_query(self):
        rows = [
            {"path": "noise", "text": "noise", "vec": json.dumps(unit_vector(0.59))},
        ]

        with (
            patch.object(rag, "embed", return_value=[1.0, 0.0]),
            patch.object(rag, "conn", return_value=FakeConnection(rows)),
        ):
            self.assertEqual(rag.context("off topic"), "")


if __name__ == "__main__":
    unittest.main()
