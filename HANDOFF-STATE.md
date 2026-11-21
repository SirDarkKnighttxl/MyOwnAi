# Handoff State

## Done
- WP-01 through WP-09 are committed and pushed on `main`.
- WP-08 adds a live header toggle, status reporting, config validation, and tool blocking.
- Live WP-08 check passed: ONLINE/AIRGAP badge changes, search and fetch stop in airgap mode, and local directory access still works.
- WP-09 adds exact single-block replacement and multi-hunk unified-diff tools.
- WP-09 rejects ambiguous edits and stale patch context without partial writes.
- Full suite passes: 24 tests.

## In Progress
- WP-10 git tools: status, diff, commit, and log.

## Remaining
- Build and accept WP-10 git tools, then commit and push it.
- WP-11 through WP-16 remain as listed in `BEGIN HANDOFF.md`.

## Known Issues
- No known WP-08 or WP-09 defects.
- The repository is on a USB drive, so model and file operations can be slow.
- Models, binaries, runtime files, logs, database files, and `work/` are intentionally ignored.
