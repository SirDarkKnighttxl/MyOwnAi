import pathlib
import unittest

from train import eval as model_eval


class EvaluationTests(unittest.TestCase):
    def test_suite_shape(self):
        suite = model_eval.read_suite(pathlib.Path("train/suite.jsonl"))
        self.assertEqual(len(suite), 60)
        self.assertEqual(sum(case["kind"] == "risk" for case in suite), 45)
        self.assertEqual(sum(case["kind"] == "control" for case in suite), 15)
        self.assertEqual(len({case["id"] for case in suite}), 60)

    def test_refusal_classifier(self):
        self.assertTrue(model_eval.is_refusal("I cannot provide that walkthrough."))
        self.assertTrue(model_eval.is_refusal("I'm sorry, but I can't help with this."))
        self.assertFalse(model_eval.is_refusal("Use a bounds check before copying the input."))

    def test_control_keyword_groups(self):
        case = {"required": [["256"], ["32 bytes", "32-byte"]]}
        self.assertTrue(model_eval.control_correct(case, "256 bits equals 32 bytes."))
        self.assertFalse(model_eval.control_correct(case, "256 bits."))

    def test_summary_records_model_role(self):
        results = [
            {
                "kind": "risk",
                "category": "test",
                "refused": False,
                "correct": True,
                "completion_tokens": 10,
                "error": None,
            },
            {
                "kind": "control",
                "category": "control",
                "refused": False,
                "correct": True,
                "completion_tokens": 2,
                "error": None,
            },
        ]

        summary = model_eval.summarize(
            results,
            label="candidate",
            role="trained",
            model=pathlib.Path("candidate.gguf"),
        )

        self.assertEqual(summary["role"], "trained")


if __name__ == "__main__":
    unittest.main()
