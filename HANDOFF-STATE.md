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
- Full suite passes: 57 tests (`python -m pytest -q`).

## In Progress
- None.

## Pending Live Checks
- WP-14 live run on the Windows box: kill any stale llama-server on port 8095 first (it would keep the old 512 batch). Then `python index_corpus.py 1500 rea,ciphey` must finish and report chunks plus skipped, and `logs/embed.log` must show `n_ubatch = 2048`. The first live run aborted at 787 ciphey chunks and never reached `rea/`.
- Unverified: a REA CLI question surfacing REA docs above payload files. This needs the live embed model. No reranker was built (descoped), and retrieval is still plain cosine with the 0.60 floor.

## Remaining
- WP-15 and WP-16.
- Original WP-14 corpus expansion and re-rank work (pytorch/transformers docs, per-repo caps, reranker) was descoped and is not scheduled.
- WP-13 stays last, after the portable harness is complete.

## Known Issues
- No known WP-08 through WP-14 defects.
- The repository is on a USB drive, so model and file operations can be slow.
- Models, binaries, runtime files, logs, database files, and `work/` are intentionally ignored.
