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
- Full suite passes: 48 tests (`python -m pytest -q` or `python -m unittest discover -s tests`).

## In Progress
- None.

## Pending Live Checks
- WP-14 live run on the Windows box with the embed model: `python index_corpus.py 1500 rea,ciphey` must finish and report chunks plus skipped.
- Unverified: a REA CLI question surfacing REA docs above payload files. This needs the live embed model. No reranker was built (descoped), and retrieval is still plain cosine with the 0.60 floor.

## Remaining
- WP-15 and WP-16.
- Original WP-14 corpus expansion and re-rank work (pytorch/transformers docs, per-repo caps, reranker) was descoped and is not scheduled.
- WP-13 stays last, after the portable harness is complete.

## Known Issues
- No known WP-08 through WP-14 defects.
- The repository is on a USB drive, so model and file operations can be slow.
- Models, binaries, runtime files, logs, database files, and `work/` are intentionally ignored.
