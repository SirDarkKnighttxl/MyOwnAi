import pathlib
import sys

from noxd import rag

root = pathlib.Path(__file__).resolve().parent / "work" / "corpus"
limit = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
only = sys.argv[2].split(",") if len(sys.argv) > 2 else None
print(rag.index(root, limit, only), flush=True)
