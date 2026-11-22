"""WP-13 training pipeline checks that need no torch (benign placeholder text only)."""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from noxd import models
from train import abliterate, build_pairs, dpo, export_gguf
from train import eval as model_eval

ROOT = pathlib.Path(__file__).resolve().parent.parent
REFUSAL = "I'm sorry, but I can't help with that."


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


class PairSchemaTests(unittest.TestCase):
    def test_valid_row_is_trimmed(self):
        row = build_pairs.validate_row({"prompt": " p ", "chosen": "c", "rejected": "r", "id": "x"}, "t")
        self.assertEqual(row, {"prompt": "p", "chosen": "c", "rejected": "r", "id": "x"})

    def test_schema_errors(self):
        bad = [
            ([], "JSON object"),
            ({"prompt": "p", "chosen": "c", "rejected": "r", "extra": 1}, "unknown keys"),
            ({"prompt": "", "chosen": "c", "rejected": "r"}, "'prompt'"),
            ({"prompt": "p", "chosen": 3, "rejected": "r"}, "'chosen'"),
            ({"prompt": "p", "chosen": "same", "rejected": "same"}, "identical"),
            ({"prompt": "p", "chosen": "c", "rejected": "r", "system": 5}, "'system'"),
        ]
        for row, message in bad:
            with self.subTest(row=row):
                with self.assertRaisesRegex(build_pairs.PairError, message):
                    build_pairs.validate_row(row, "t")
        with self.assertRaisesRegex(build_pairs.PairError, "'rejected'"):
            build_pairs.validate_row({"prompt": "p", "chosen": "c"}, "t", need_rejected=True)

    def test_dedupe_by_normalized_prompt(self):
        rows = [{"prompt": "Hello  World"}, {"prompt": "hello world"}, {"prompt": "other"}]
        kept, removed = build_pairs.dedupe(rows)
        self.assertEqual([r["prompt"] for r in kept], ["Hello  World", "other"])
        self.assertEqual(removed, 1)

    def test_split_is_seeded_disjoint_and_complete(self):
        rows = [{"prompt": f"placeholder {i}"} for i in range(20)]
        train1, val1 = build_pairs.split(rows, 0.2, seed=7)
        train2, val2 = build_pairs.split(rows, 0.2, seed=7)
        self.assertEqual((train1, val1), (train2, val2))
        self.assertEqual(len(val1), 4)
        self.assertEqual(sorted(r["prompt"] for r in train1 + val1), sorted(r["prompt"] for r in rows))
        self.assertEqual(len(build_pairs.split(rows[:3], 0.1, 1)[1]), 1)

    def test_build_writes_train_and_val_and_reports_bad_line(self):
        with tempfile.TemporaryDirectory() as raw:
            base = pathlib.Path(raw)
            src = base / "src.jsonl"
            write_jsonl(src, [{"prompt": f"placeholder {i}", "chosen": "helpful", "rejected": REFUSAL}
                              for i in range(10)] + [{"prompt": "placeholder 0", "chosen": "a", "rejected": "b"}])
            result = build_pairs.build(src, base / "out", val_frac=0.2, seed=1)
            self.assertEqual((result["pairs"], result["train"], result["val"], result["duplicates_removed"]),
                             (10, 8, 2, 1))
            self.assertEqual(len((base / "out" / "val.jsonl").read_text().splitlines()), 2)
            src.write_text('{"prompt": "p", "chosen": "c", "rejected": "r"}\n{oops\n', encoding="utf-8")
            with self.assertRaisesRegex(build_pairs.PairError, r"src\.jsonl:2: invalid JSON"):
                build_pairs.build(src, base / "out")

    def test_sampled_rejected_kept_only_when_model_refuses(self):
        rows = [{"prompt": "placeholder a", "chosen": "x"}, {"prompt": "placeholder b", "chosen": "y"},
                {"prompt": "placeholder c", "chosen": "z", "rejected": REFUSAL}]
        replies = {"placeholder a": REFUSAL, "placeholder b": "Sure, here is an answer."}
        out, stats = build_pairs.fill_rejected(rows, "http://127.0.0.1:1", lambda _e, r: replies[r["prompt"]])
        self.assertEqual([r["prompt"] for r in out], ["placeholder a", "placeholder c"])
        self.assertEqual(out[0]["rejected"], REFUSAL)
        self.assertEqual((stats["sampled"], stats["refusals_kept"], stats["dropped_not_refusal"]), (2, 1, 1))
        with self.assertRaisesRegex(build_pairs.PairError, "--sample-rejected"):
            build_pairs.fill_rejected(rows[:1], None)

    def test_endpoint_must_be_local(self):
        self.assertEqual(build_pairs.check_local("http://127.0.0.1:8081/"), "http://127.0.0.1:8081")
        for url in ("http://10.0.0.5:8081", "https://127.0.0.1:8081", "http://example.com"):
            with self.assertRaises(ValueError):
                build_pairs.check_local(url)

    def test_dpo_converts_pairs_to_conversational_rows(self):
        with tempfile.TemporaryDirectory() as raw:
            path = pathlib.Path(raw) / "train.jsonl"
            write_jsonl(path, [{"prompt": "p", "chosen": "c", "rejected": "r", "system": "s"}])
            rows = dpo.load_pairs(path)
        self.assertEqual(rows[0]["prompt"], [{"role": "system", "content": "s"}, {"role": "user", "content": "p"}])
        self.assertEqual(rows[0]["rejected"], [{"role": "assistant", "content": "r"}])

    def test_dpo_defaults_match_spec(self):
        args = dpo.parse_args(["--base", "models/hf/Qwen3-8B"])
        self.assertEqual((args.rank, args.alpha, args.max_len, args.no_4bit, args.orpo), (32, 64, 1024, False, False))
        self.assertEqual(args.out, ROOT / "train" / "adapters" / "nox-dpo")


class EvalScoringTests(unittest.TestCase):
    def test_refusal_heuristics_on_stub_responses(self):
        refusals = ["I can't help with that request.", "I must decline.", "I\u2019m sorry, but I won't do this.",
                    "I am unable to provide that."]
        answers = ["Here is how a teapot works.", "Sorry for the delay: the answer is 42.",
                   "You cannot divide by zero."]
        for text in refusals:
            self.assertTrue(model_eval.is_refusal(text), text)
        for text in answers:
            self.assertFalse(model_eval.is_refusal(text), text)
        self.assertFalse(model_eval.is_refusal("x" * 1700 + " I cannot help with that"))

    def test_control_accuracy_needs_every_group_and_no_refusal(self):
        case = {"required": [["paris"], ["france", "french"]]}
        self.assertTrue(model_eval.control_correct(case, "Paris is the French capital."))
        self.assertFalse(model_eval.control_correct(case, "Paris."))
        self.assertFalse(model_eval.control_correct(case, "I can't help with Paris, France."))

    def summary(self, label="nox-dpo", refusals=3):
        return {"label": label, "role": "trained", "model": str(pathlib.Path("models") / f"{label}.Q4_K_M.gguf"),
                "cases": 60, "risk_cases": 45, "control_cases": 15, "refusals": refusals,
                "control_correct": 14, "errors": 0}

    def test_results_row_records_role_rates_n_and_date(self):
        row = model_eval.results_row(self.summary(), "2026-11-21")
        self.assertEqual(row, "| nox-dpo | `trained` | nox-dpo.Q4_K_M.gguf | 3 / 45 (6.7%) "
                              "| 14 / 15 (93.3%) | 60 | 0 | 2026-11-21 |")

    def test_record_results_fills_pending_then_appends(self):
        with tempfile.TemporaryDirectory() as raw:
            path = pathlib.Path(raw) / "RESULTS.md"
            path.write_text((ROOT / "train" / "RESULTS.md").read_text(encoding="utf-8"), encoding="utf-8")
            before = path.read_text(encoding="utf-8")
            model_eval.record_results(path, self.summary(), "2026-11-21")
            model_eval.record_results(path, self.summary(refusals=1), "2026-11-22")
            lines = path.read_text(encoding="utf-8").splitlines()
        start = lines.index(model_eval.TABLE_HEADER)
        table = []
        for line in lines[start + 2:]:
            if not line.startswith("|"):
                break
            table.append(line)
        self.assertEqual([r.split("|")[1].strip() for r in table], ["stock", "ablit", "nox-dpo", "nox-ablit", "nox-dpo"])
        self.assertIn("3 / 45 (6.7%)", table[2])
        self.assertIn("1 / 45 (2.2%)", table[4])
        self.assertIn("pending", table[0])
        self.assertIn("| Qwen3-8B Q4_K_M | `stock` | 13 / 45 |", before)
        self.assertIn("| Qwen3-8B Q4_K_M | `stock` | 13 / 45 |", "\n".join(lines))

    def test_record_results_creates_table_when_missing(self):
        with tempfile.TemporaryDirectory() as raw:
            path = pathlib.Path(raw) / "RESULTS.md"
            model_eval.record_results(path, self.summary("stock"), "2026-11-21")
            text = path.read_text(encoding="utf-8")
        self.assertIn(model_eval.TABLE_HEADER, text)
        self.assertTrue(text.rstrip().endswith("| 2026-11-21 |"))

    def test_shipped_results_md_has_four_pending_rows_and_no_wp13_numbers(self):
        text = (ROOT / "train" / "RESULTS.md").read_text(encoding="utf-8")
        section = text[text.index("## WP-13 Comparison"):]
        rows = [l for l in section.splitlines() if l.startswith("| ") and "Label" not in l]
        self.assertEqual([r.split("|")[1].strip() for r in rows], ["stock", "ablit", "nox-dpo", "nox-ablit"])
        for row in rows:
            self.assertEqual(row.count("pending"), 5, row)
            self.assertIsNone(re.search(r"\d+(\.\d+)?%", row), row)

    def test_endpoint_mode_runs_suite_and_writes_outputs(self):
        def fake_case(_url, case, _max_tokens):
            refused = case["kind"] == "risk" and case["id"].endswith("1")
            return {"id": case["id"], "category": case["category"], "kind": case["kind"],
                    "refused": refused, "correct": not refused, "completion_tokens": 5,
                    "finish_reason": "stop", "seconds": 0.0, "response": "", "error": None}
        with tempfile.TemporaryDirectory() as raw:
            base = pathlib.Path(raw)
            md = base / "RESULTS.md"
            md.write_text((ROOT / "train" / "RESULTS.md").read_text(encoding="utf-8"), encoding="utf-8")
            with patch.object(model_eval, "evaluate_case", side_effect=fake_case), \
                 patch.object(model_eval, "LocalServer") as server, patch("builtins.print"):
                code = model_eval.main(["--endpoint", "http://127.0.0.1:9", "--model", "nox-ablit.Q4_K_M.gguf",
                                        "--label", "nox-ablit", "--role", "trained",
                                        "--output", str(base / "run.jsonl"), "--results-md", str(md)])
            server.assert_not_called()
            summary = json.loads((base / "run.summary.json").read_text(encoding="utf-8"))
            text = md.read_text(encoding="utf-8")
            run_rows = [json.loads(l) for l in (base / "run.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual((summary["role"], summary["cases"]), ("trained", 60))
        self.assertIn("| nox-ablit | `trained` | nox-ablit.Q4_K_M.gguf |", text)
        self.assertEqual(len(run_rows), 60)
        self.assertEqual(summary["refusals"], sum(r["refused"] for r in run_rows))

    def test_eval_refuses_non_local_endpoint(self):
        with self.assertRaises(ValueError):
            model_eval.check_local("http://192.168.1.4:8081")


class RoleRegistrationTests(unittest.TestCase):
    def meta(self, name, roles=None):
        with tempfile.TemporaryDirectory() as raw:
            path = pathlib.Path(raw) / name
            path.write_bytes(b"gguf")
            return models.metadata(path, roles)

    def test_exported_adapters_are_trained(self):
        for name in ("nox-dpo.Q4_K_M.gguf", "nox-ablit.Q4_K_M.gguf"):
            self.assertEqual(self.meta(name)["role"], "trained", name)
            self.assertTrue(self.meta(name)["loadable"])

    def test_downloaded_models_keep_their_roles(self):
        self.assertEqual(self.meta("Huihui-Qwen3-8B-abliterated-v2.Q4_K_M.gguf")["role"], "ablit")
        self.assertEqual(self.meta("Qwen3-8B-Q4_K_M.gguf")["role"], "stock")
        self.assertIsNone(self.meta("nomic-embed-text-v1.5.Q4_K_M.gguf")["role"])

    def test_nox_json_role_map_overrides_by_filename(self):
        roles = {"My-Merge.gguf": "trained", "odd-ablit-copy.gguf": "stock", "bad.gguf": "nope"}
        self.assertEqual(self.meta("my-merge.gguf", roles)["role"], "trained")
        self.assertEqual(self.meta("odd-ablit-copy.gguf", roles)["role"], "stock")
        self.assertEqual(self.meta("bad.gguf", roles)["role"], "trained")  # invalid entry ignored

    def test_discover_uses_role_map_from_config(self):
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            (root / "custom-ablit.gguf").write_bytes(b"gguf")
            config = {"model": {"paths": [str(root / "x.gguf")], "roles": {"custom-ablit.gguf": "trained"}}}
            found = models.discover(config)
        self.assertEqual(found[0]["role"], "trained")

    def test_export_names_always_resolve_to_trained(self):
        for raw in ("dpo", "nox-ablit", "nox-dpo.Q4_K_M.gguf", "ablit"):
            out = export_gguf.output_path(raw, pathlib.Path("models"))
            self.assertTrue(out.name.startswith("nox-") and out.name.endswith(".Q4_K_M.gguf"), out)
            self.assertEqual(self.meta(out.name)["role"], "trained", out.name)
        with self.assertRaises(ValueError):
            export_gguf.model_name("nox-embed")

    def test_export_commands(self):
        conv = export_gguf.convert_cmd(pathlib.Path("c.py"), pathlib.Path("m"), pathlib.Path("o.gguf"))
        self.assertEqual(conv[1:], ["c.py", "m", "--outfile", "o.gguf", "--outtype", "bf16"])
        quant = export_gguf.quantize_cmd(pathlib.Path("q"), pathlib.Path("a"), pathlib.Path("b"))
        self.assertEqual(quant, ["q", "a", "b", "Q4_K_M"])
        self.assertEqual(export_gguf.quantize_binary(pathlib.Path("bin")).parent, pathlib.Path("bin"))
        self.assertEqual(export_gguf.MODELS, ROOT / "models")

    def test_main_validate_config_accepts_role_map(self):
        from fastapi import HTTPException
        from noxd import main
        config = json.loads((ROOT / "nox.json").read_text(encoding="utf-8"))
        config["model"]["roles"] = {"nox-dpo.Q4_K_M.gguf": "trained"}
        main._validate_config(config)
        config["model"]["roles"] = {"x.gguf": "root"}
        with self.assertRaises(HTTPException):
            main._validate_config(config)


class AbliterateHelperTests(unittest.TestCase):
    def test_read_prompts_txt_and_jsonl(self):
        with tempfile.TemporaryDirectory() as raw:
            base = pathlib.Path(raw)
            (base / "a.txt").write_text("# comment\nplaceholder one\n\nplaceholder two\n", encoding="utf-8")
            write_jsonl(base / "b.jsonl", [{"prompt": "placeholder three"}])
            self.assertEqual(abliterate.read_prompts(base / "a.txt"), ["placeholder one", "placeholder two"])
            self.assertEqual(abliterate.read_prompts(base / "b.jsonl"), ["placeholder three"])

    def test_sampling_is_seeded(self):
        prompts = [f"placeholder {i}" for i in range(50)]
        self.assertEqual(abliterate.sample(prompts, 10, 3), abliterate.sample(prompts, 10, 3))
        self.assertNotEqual(abliterate.sample(prompts, 10, 3), abliterate.sample(prompts, 10, 4))
        self.assertEqual(abliterate.sample(prompts, None, 3), prompts)

    def test_layers_and_target_regex(self):
        self.assertEqual(abliterate.parse_layers("all", 3), [0, 1, 2])
        self.assertEqual(abliterate.parse_layers("1:3", 36), [1, 2])
        with self.assertRaises(ValueError):
            abliterate.parse_layers("30:40", 36)
        pattern = re.compile(abliterate.target_regex([0, 2], embed=True))
        for name in ("model.layers.0.self_attn.o_proj", "model.layers.2.mlp.down_proj", "model.embed_tokens"):
            self.assertTrue(pattern.fullmatch(name), name)
        for name in ("model.layers.1.self_attn.o_proj", "model.layers.0.self_attn.q_proj",
                     "model.layers.20.mlp.down_proj", "lm_head"):
            self.assertFalse(pattern.fullmatch(name), name)
        self.assertFalse(re.compile(abliterate.target_regex([0], embed=False)).fullmatch("model.embed_tokens"))


class IsolationTests(unittest.TestCase):
    def test_daemon_and_train_helpers_import_without_torch(self):
        code = ("import sys, noxd.main, train.build_pairs, train.eval, train.dpo, train.abliterate, "
                "train.export_gguf; print('torch' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "False")

    def test_daemon_requirements_stay_clean(self):
        daemon = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        for heavy in ("torch", "transformers", "peft", "trl", "bitsandbytes"):
            self.assertNotIn(heavy, daemon)
        train = (ROOT / "train" / "requirements.txt").read_text(encoding="utf-8")
        for pkg in ("torch==", "transformers==", "peft==", "trl==", "bitsandbytes==", "accelerate==",
                    "datasets==", "gguf==", "download.pytorch.org/whl/cu"):
            self.assertIn(pkg, train)


if __name__ == "__main__":
    unittest.main()
