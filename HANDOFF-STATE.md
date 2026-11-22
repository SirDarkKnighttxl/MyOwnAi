# Handoff State

## Done
- WP-01 through WP-12 are committed and pushed on `main`.
- WP-08 adds a live header toggle, status reporting, config validation, and tool blocking.
- Live WP-08 check passed: ONLINE/AIRGAP badge changes, search and fetch stop in airgap mode, and local directory access still works.
- WP-09 adds exact single-block replacement and multi-hunk unified-diff tools.
- WP-09 rejects ambiguous edits and stale patch context without partial writes.
- WP-10 adds gated status, diff, commit, and log tools with USB-drive support.
- Live WP-10 check returned real status/diff/log output and rejected a missing commit message.
- WP-11 runs Python from temporary files, captures both streams, and kills the process tree on timeout.
- Live WP-11 check killed a busy loop and its spawned `ping -t` child with no files left behind.
- WP-12 adds command approval with allow, deny, and per-binary session grants.
- Live WP-12 check passed for the modal, ask mode, auto scope, and session reuse.
- WP-14 (rescoped to indexer resilience) adds `embed_retry` (3 tries, 0.5s then 1.5s backoff), a `MAX_CONSEC_FAIL=20` abort with skipped counting, and a SQLite resume cursor (`index_state.next_candidate`) committed in the same transaction as the inserted rows.
- WP-14: `python index_corpus.py <limit> <repo,repo> [--resume]`; without `--resume` the chunks and state are cleared. Long chunks (>4000 chars) are logged; progress prints every 25 chunks with done/skipped/consec.
- WP-14 skipped candidates are committed with the next successful insert, so an abort or interrupt retries them on resume instead of dropping them.
- WP-14 follow-up: all SQLite access goes through `store.session()` (commit + close), which fixes the Windows nox.db lock in tests. `pytest.ini` added.
- WP-14 follow-up: the embed server starts with `-c 2048 -b 2048 -ub 2048`, and its stdout/stderr go to `logs/embed.log` (grep `n_ubatch`). The first live run failed on dense chunks under the 512-token default batch.
- WP-14 follow-up: the indexer skips `images/`, `testdata/`, `fixtures/`, `repomix-output*`, `*wordlist*`, `*.min.*`, and any file whose longest line is over 1000 chars (logged as `skip long-line <relpath> longest=<n>`). `FILTER_VERSION=3` is part of the resume fingerprint, so `--resume` is refused after a filter change.
- `rag.search()` calls `ensure()` first and prints a message if the embed server is down, so a dead server no longer looks like zero results.
- WP-14 accepted by the owner.
- WP-15 adds the lessons memory editor. `noxd/lessons.py` treats every non-blank line of `policy/lessons.md` as a lesson, except `#` headers and `<!-- -->` comments, which are kept untouched. Indices are 0-based and renumber after a delete.
- WP-15 API: GET/POST `/api/lessons`, PUT/DELETE `/api/lessons/{i}`. An out-of-range index returns 404 and empty text returns 400. Writes are atomic (temp file + `os.replace`) and keep the file's CRLF/LF style. The UI has a `lessons` sidebar with inline edit, delete, and add.
- WP-15: the system prompt reads lessons.md fresh on every chat (it was never cached), so an edit reaches the next chat.
- WP-16 adds a portable runtime. `setup_runtime.bat` downloads python-3.12.10-embed-amd64 (SHA-256 pinned) into `runtime\python` and installs `packaging\python312._pth` (`..\..` + `import site`). It then bootstraps pip and installs `requirements.txt` using setuptools/wheel with `--no-build-isolation`, because the proxy_tools sdist can't build in isolation under `._pth`.
- WP-16: `run.bat` prefers `runtime\python\python.exe`, falls back to a working `python` on PATH (skipping the Store alias), and errors clearly if neither exists. The README documents the stripped-PATH acceptance check.
- Full suite passes: 79 tests (`python -m pytest -q`).

## In Progress
- None.

## Pending Live Checks
- WP-15 live check: in the UI, add a lesson, edit it, confirm the next chat's system prompt contains it, then delete it.
- WP-16 acceptance on Windows: run `setup_runtime.bat`, then the stripped-PATH `run.bat` check from the README.

## Remaining
- None before WP-13.
- Original WP-14 corpus expansion and re-rank work (pytorch/transformers docs, per-repo caps, reranker) was descoped and is not scheduled.
- WP-13 stays last, after the portable harness is complete.

## Known Issues
- No known WP-08 through WP-16 defects.
- `setup_fast.bat` still hardcodes `C:\NOX\models` (pre-existing, untouched).
- `GET /api/persona` returns persona plus lessons, so a client that PUTs that text back would copy the lessons into persona.md. The UI does not do this; left as is.
- The repository is on a USB drive, so model and file operations can be slow.
- Models, binaries, runtime files, logs, database files, and `work/` are intentionally ignored.
