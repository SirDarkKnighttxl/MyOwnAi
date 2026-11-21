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
- Full suite passes: 36 tests.

## In Progress
- WP-14 corpus expansion and result re-ranking.

## Remaining
- WP-14 through WP-16.
- WP-13 stays last, after the portable harness is complete.

## Known Issues
- No known WP-08 through WP-12 defects.
- The repository is on a USB drive, so model and file operations can be slow.
- Models, binaries, runtime files, logs, database files, and `work/` are intentionally ignored.
