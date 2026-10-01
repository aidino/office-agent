# Code Review: Task 11 — Setup Command & Git Submodules

**Reviewed**: 2026-10-01
**Commit**: b8e4ab4 (pre-fix)
**Decision**: REQUEST CHANGES → **FIXED**

## Summary

Task 11 correctly implements all 6 spec §10.3 setup steps and `.gitmodules`. Two HIGH issues (non-portable `which` subprocess call, oversized function) and four MEDIUM issues (unhandled OSError, unused imports, misordered tests, overly loose assertion) were found and fixed in-place.

## Findings

### CRITICAL
None

### HIGH

**H-1: Non-portable `which` subprocess call** — `cli.py:209-211`
- Used `subprocess.run(["which", "libreoffice"])` — `which` doesn't exist on Windows.
- **Fix**: Replaced with `shutil.which("libreoffice")` — stdlib, cross-platform, no subprocess needed.

**H-2: `_cmd_setup()` exceeded 50-line function limit** — `cli.py:160-237` (78 lines)
- All 6 setup steps were inline in a single function.
- **Fix**: Extracted 6 helper functions (`_setup_submodules`, `_setup_check_dataset`, `_setup_check_pptc`, `_setup_check_libreoffice`, `_setup_check_forte`, `_setup_check_api_keys`). `_cmd_setup` is now 11 lines.

### MEDIUM

**M-3: Unprotected `subprocess.run` for `which` (step 4)** — `cli.py:209-211`
- No `try/except OSError` wrapper, unlike step 1's git call. Would crash on systems without `which`.
- **Fix**: Eliminated by H-1 (replaced with `shutil.which`).

**M-5: Unused imports in `test_setup.py`** — lines 4-5
- `import os` and `from pathlib import Path` were imported but never used.
- **Fix**: Removed both.

**M-6: Test section ordering doesn't match step numbering** — `test_setup.py`
- Tests were ordered: Step 1, 4, 6, 2, 3, 5. Confusing to follow.
- **Fix**: Reordered to: Step 1, 2, 3, 4, 5, 6, then step-ordering test.

**M-8: Overly loose assertion in `test_setup_acknowledges_present_api_key`** — `test_setup.py:74`
- `"set" in printed.lower()` matches "dataset" — would pass even without API key acknowledgment.
- **Fix**: Changed to negative assertion: verify the warning message is NOT present when key is set.

### LOW

**L-7: `test_setup_runs_submodule_update` doesn't mock print** — `test_setup.py:21-30`
- Inconsistent with other tests that all mock `builtins.print`. Prints to real stdout during test.
- **Status**: Accepted — captures to capsys implicitly; test purpose is verifying subprocess calls, not output.

## Validation Results

| Check | Result |
|---|---|
| Tests (163) | ✅ Pass |
| Coverage (95%) | ✅ Pass |
| `cli.py` coverage (97%) | ✅ Pass |

## Files Reviewed

| File | Change | Status |
|---|---|---|
| `benchmarks/src/office_bench/cli.py` | Modified | Fixed (H-1, H-2, M-3) |
| `benchmarks/tests/test_setup.py` | Added | Fixed (M-5, M-6, M-8) |
| `.gitmodules` | Added | Clean |
| `.claude/tdd/task11-setup.tdd.md` | Added | Clean |
| `docs/superpowers/plans/2026-10-01-benchmark-harness.md` | Modified | Steps checked |
