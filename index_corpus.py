"""Index work/corpus into nox.db.

Usage: python index_corpus.py [limit] [repo,repo,...] [--resume]
  limit    max chunks to insert this run (default 1500)
  repos    comma-separated top-level folders under work/corpus (default: all)
  --resume continue from the cursor saved in nox.db instead of starting fresh
"""
import pathlib
import sys

from noxd import rag

root = pathlib.Path(__file__).resolve().parent / "work" / "corpus"
args = [a for a in sys.argv[1:] if a != "--resume"]
resume = "--resume" in sys.argv[1:]
limit = int(args[0]) if args else 1500
only = [r for r in args[1].split(",") if r] if len(args) > 1 else None
result = rag.index(root, limit, only, resume=resume)
print(result, flush=True)
if result.get("ok"):
    print(f"chunks={result['chunks']} skipped={result['skipped']} "
          f"next_candidate={result['next_candidate']}", flush=True)
sys.exit(0 if result.get("ok") else 1)
