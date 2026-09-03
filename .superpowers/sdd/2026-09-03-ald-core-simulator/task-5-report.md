# Task 5 implementation report

## Delivered

- Added `validate RECIPE` and `simulate RECIPE --seed INT --output DIR` CLI commands.
- Added `--log-level` and simulation `--overwrite` options.
- Added deterministic validation JSON containing protocol, recipe/root provenance, packet digests, packet count/bytes, and expanded limits/metrics.
- Added canonical `audit.jsonl`, `cycles.csv`, `surface-final.json`, and conditional `fault.json` writers. Enum, digest, tuple, and immutable mapping values are converted without mutating source objects.
- Added atomic sibling-directory publication with collision checks, safe parent creation, symlink/non-directory rejection, overwrite backup/restore, and temporary cleanup.
- Added one structured JSON CLI error boundary with ALD exit-code mapping and optional DEBUG tracebacks.
- Added integration tests covering validation, deterministic simulation reports, fault reporting/status, collision preservation, and explicit overwrite.
- Hardened publication against recipe/output path overlap and late no-overwrite collisions using an atomic no-replace rename primitive. Transaction recovery now restores old output on any publication exception, retains recoverable backups when restore/cleanup fails, and rejects non-finite CSV metrics.
- Added invalid-UTF-8 recipe handling, successful `--help` status handling, and the module entrypoint guard.
- Round 2 binds staging, parent, and destination directory identities around Linux atomic no-replace/exchange operations; overwrite rollback now exchanges back only verified identities and never recursively cleans a swapped staging path. Added injected staging/parent swap and rollback-boundary regressions.
- Round 3 replaced the remaining path-based publisher with held `_OwnedDirectory` descriptors. Parent components are opened/created with `dir_fd` and `O_NOFOLLOW`; reports use descriptor-relative opens; renameat2 receives parent fd plus entry names; recursive cleanup uses fd-relative `listdir/stat/open/unlink/rmdir` and identity checks. All descriptors close on success and failures.
- Round 4 removed duplicate descriptor writers, retained descriptor state across close failures, closes newly opened parent components safely when transfer fails, and cleans or retains a just-created staging entry when its first child open fails. Publication now holds an exclusive regular-file `fcntl.flock` lock for the full transaction, rejects unsafe lock entries, preserves errno and destination names in rename errors, and routes argparse usage failures through the single structured JSON error boundary. The code documents the explicit single-user trust boundary: no guarantee is made against a hostile same-UID writer of the output parent because Linux `renameat2` has no source-FD binding for directory rename/unlink.
- Round 5 adds bounded close finalization that probes fd state before retrying, retains still-live resources in a module-owned deferred-close registry, drains that registry at publication boundaries, and unlocks publisher locks before close. Raw report descriptors are retained and finalized if `fdopen` fails, including stream/encoding errors. Removed the unused `_fd_identity` helper and added one-shot/persistent close and fd-leak regressions.

## Verification

- `python -m pytest tests/test_ald_media_controller.py -k 'validate_prints or simulate_ or replace_output or write_cycle_csv or invalid_utf8 or help_returns' -v` — 15 passed.
- `python -m pytest tests/test_ald_media_controller.py -k 'simulate_ or replace_output or publish_reports or write_cycle_csv or invalid_utf8 or help_returns' -q` — 18 passed.
- `python -m pytest tests/test_ald_media_controller.py -v` — 77 passed.
- `python -m pytest tests/test_ald_media_controller.py -q` — 82 passed.
- `python -m pytest tests/test_ald_media_controller.py -k 'lock_close or persistent_close or fdopen_failure or encoding_failure'` — 5 passed.
- `python -m pytest -q` — 87 passed.
- `python -m py_compile ald_media_controller.py` — passed.
- `git diff --check` — passed.

## Concerns

- Direct simulation remains intentionally offline and uses the existing deterministic controller/surface implementation. No media, network, subprocess, hardware, or wall-clock operations were added.
- The publisher lock is cooperative and intentionally leaves a regular lock entry in the output parent. Descriptor operations are hardened against accidental path races and preserve recoverable uncertain entries, but this remains a local single-user simulator boundary rather than a hostile multi-tenant publication service.
