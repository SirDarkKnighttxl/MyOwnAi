"""Build DPO/ORPO preference pairs: (prompt, chosen, rejected).

Input is a user-supplied JSONL file (default train/pairs_src.jsonl, gitignored).
NOX ships no pair content; you write the source rows. One object per line:

    {"prompt": "...", "chosen": "...", "rejected": "..."}   complete pair
    {"prompt": "...", "chosen": "..."}                       needs --sample-rejected

Optional keys: "id" (string), "system" (string).

With --sample-rejected, rows without "rejected" are sent to a *local*
llama-server (127.0.0.1 only). The model's answer is kept as "rejected" only
when the eval refusal classifier says it refused; otherwise the row is dropped
(there is no refusal to train away from).

Output: train/pairs/train.jsonl and train/pairs/val.jsonl (gitignored), deduped
by normalized prompt, shuffled with --seed, split by --val-frac.
Stdlib + httpx only, so this runs without torch.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
import urllib.parse

import httpx

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from train.eval import is_refusal  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "train" / "pairs_src.jsonl"
DEFAULT_OUT = ROOT / "train" / "pairs"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
TEXT_KEYS = ("prompt", "chosen", "rejected")
OPTIONAL_KEYS = {"id", "system"}


class PairError(ValueError):
    pass


def validate_row(row: object, where: str, need_rejected: bool = True) -> dict:
    """Return a clean pair dict or raise PairError naming the problem."""
    if not isinstance(row, dict):
        raise PairError(f"{where}: row must be a JSON object")
    unknown = set(row) - set(TEXT_KEYS) - OPTIONAL_KEYS
    if unknown:
        raise PairError(f"{where}: unknown keys {sorted(unknown)}")
    required = TEXT_KEYS if need_rejected else TEXT_KEYS[:2]
    clean = {}
    for key in required:
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            raise PairError(f"{where}: '{key}' must be a non-empty string")
        clean[key] = value.strip()
    if "rejected" in row and not need_rejected:
        value = row["rejected"]
        if not isinstance(value, str) or not value.strip():
            raise PairError(f"{where}: 'rejected' must be a non-empty string when present")
        clean["rejected"] = value.strip()
    if "rejected" in clean and clean["rejected"] == clean["chosen"]:
        raise PairError(f"{where}: 'chosen' and 'rejected' are identical")
    for key in OPTIONAL_KEYS & set(row):
        if not isinstance(row[key], str):
            raise PairError(f"{where}: '{key}' must be a string")
        clean[key] = row[key]
    return clean


def read_source(path: pathlib.Path, need_rejected: bool) -> list[dict]:
    rows = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        where = f"{path.name}:{line_no}"
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PairError(f"{where}: invalid JSON ({exc.msg})") from exc
        rows.append(validate_row(row, where, need_rejected))
    return rows


def normalize(prompt: str) -> str:
    return " ".join(prompt.casefold().split())


def dedupe(rows: list[dict]) -> tuple[list[dict], int]:
    seen, out = set(), []
    for row in rows:
        key = normalize(row["prompt"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out, len(rows) - len(out)


def split(rows: list[dict], val_frac: float, seed: int) -> tuple[list[dict], list[dict]]:
    if not 0 <= val_frac < 1:
        raise ValueError("val-frac must be in [0, 1)")
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    n_val = round(len(shuffled) * val_frac)
    if val_frac > 0 and n_val == 0 and len(shuffled) >= 2:
        n_val = 1
    return shuffled[n_val:], shuffled[:n_val]


def check_local(endpoint: str) -> str:
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in LOCAL_HOSTS:
        raise ValueError(f"endpoint must be a local http URL (127.0.0.1), got {endpoint!r}")
    return endpoint.rstrip("/")


def sample_response(endpoint: str, row: dict, max_tokens: int = 256) -> str:
    messages = []
    if row.get("system"):
        messages.append({"role": "system", "content": row["system"]})
    messages.append({"role": "user", "content": row["prompt"] + "\n/no_think"})
    response = httpx.post(
        f"{endpoint}/v1/chat/completions",
        json={"messages": messages, "stream": False, "temperature": 0, "top_p": 1,
              "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": False}},
        timeout=360,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"].get("content") or ""


def fill_rejected(rows: list[dict], endpoint: str | None, sampler=sample_response) -> tuple[list[dict], dict]:
    """Keep complete pairs; for the rest, sample the local model and keep only refusals."""
    stats = {"sampled": 0, "refusals_kept": 0, "dropped_not_refusal": 0, "errors": 0}
    out = []
    for row in rows:
        if "rejected" in row:
            out.append(row)
            continue
        if endpoint is None:
            raise PairError("rows without 'rejected' need --sample-rejected --endpoint http://127.0.0.1:PORT")
        stats["sampled"] += 1
        try:
            text = sampler(endpoint, row).strip()
        except Exception as exc:  # network/server error: report, skip the row
            stats["errors"] += 1
            print(f"  sample failed: {type(exc).__name__}: {exc}", flush=True)
            continue
        if text and is_refusal(text) and text != row["chosen"]:
            out.append({**row, "rejected": text})
            stats["refusals_kept"] += 1
        else:
            stats["dropped_not_refusal"] += 1
    return out, stats


def write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def build(source: pathlib.Path, out_dir: pathlib.Path, val_frac: float = 0.1, seed: int = 13,
          endpoint: str | None = None, sampler=sample_response) -> dict:
    endpoint = check_local(endpoint) if endpoint else None
    rows = read_source(source, need_rejected=False)  # missing rejected -> sampled or error
    rows, duplicates = dedupe(rows)
    rows, stats = fill_rejected(rows, endpoint, sampler)
    if not rows:
        raise PairError("no usable pairs")
    train, val = split(rows, val_frac, seed)
    write_jsonl(out_dir / "train.jsonl", train)
    write_jsonl(out_dir / "val.jsonl", val)
    return {"pairs": len(rows), "train": len(train), "val": len(val),
            "duplicates_removed": duplicates, **stats,
            "train_path": str(out_dir / "train.jsonl"), "val_path": str(out_dir / "val.jsonl")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--source", type=pathlib.Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    parser.add_argument("--val-frac", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--sample-rejected", action="store_true",
                        help="sample a local llama-server for rows missing 'rejected'")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8081",
                        help="local llama-server base URL (only used with --sample-rejected)")
    args = parser.parse_args()
    if not args.source.exists():
        print(f"source not found: {args.source} (write your own pairs; see the docstring)")
        return 2
    result = build(args.source, args.out, args.val_frac, args.seed,
                   args.endpoint if args.sample_rejected else None)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
