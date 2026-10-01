# Code Review: Task 6 — CLI Interface

**Reviewed**: 2026-10-01
**Range**: `97e1df3..3b280f5` (commits `104e7e6`, `22a1527`, `3b280f5`)
**Decision**: **REQUEST CHANGES** (0 critical, 0 major, 4 medium, 3 low; all validation passes, all seven findings demonstrated with reproducers)

## Summary

The CLI implements the plan's code block faithfully, and every documented deviation is an improvement I verified rather than merely accepted: `--run-id` closes the Task 5 review gap (resume is now reachable from the CLI, and `test_run_suite_all_comma_split_and_run_id` pins the forwarding), `--no-resume` help text documents the "first run's numbers stand" semantics the Task 5 review asked for, dict dispatch removes the plan's dead trailing `return 1`, the unused `json` import is correctly dropped, and the test file grew from the plan's 4 tests to 21 — satisfying the plan's own DoD promises (`run` invokes Runner, `report` regenerates, `python -m` works) that the plan's snippet did not actually test. RED commit is test-only; the GREEN commit's single test edit is a case fix (`.lower()`), not a weakening. Full suite 83/83, `cli.py` 154/154 statements, package 598/598 (100%), worktree identical to HEAD.

However, at the same evidence bar as Task 5, the operator-facing read paths crash on an input class the codebase itself documents as a threat model, and the `run` command's input handling silently writes wrong-but-plausible or 0/0 rows into the append-only backdata CSV — the artifact this project guards hardest. Reproducer: `/tmp/repro_task6.py` (run with `cd /home/lai/Documents/office-agent/benchmarks && uv run python /tmp/repro_task6.py`), plus git-stub probes for `setup` described under L-1.

## Findings

### CRITICAL

None.

### MAJOR

None. (Task 5's M-A fix holds: a typo'd `--suite` value warns on stderr and never reaches the CSV — verified in R2d below.)

### MEDIUM

**M-1. `report` and `compare` crash with a raw `KeyError: 'suite'` on any stray valid JSON in a run directory** — `benchmarks/src/office_bench/cli.py:188` and `cli.py:243-244`.

`load_task_results` (`results.py:84-94`) skips only `meta.json`/`summary.json` by name and silently *skips* unparseable JSON, but happily ingests any other file that parses — including files that are not task results. `aggregate_suite` defends against this with `.get("suite")` (`results.py:107`), the Runner likewise (`runner.py:105`), and `_aggregate_forte`'s docstring (`results.py:129-135`) names the exact threat: *"a stray valid JSON ingested by `load_task_results`… so one alien file cannot crash aggregation after a full run."* The CLI alone subscripts: `suites = {r["suite"] for r in results}` — the one consumer that crashes on the input class every other consumer tolerates.

Reproducer (confirmed 2026-10-01, R1 in `/tmp/repro_task6.py`): a run dir with one valid result plus `notes.json` containing `{"note": "operator annotation"}` (an operator annotating a run is the realistic trigger):

```
report --run-id run1   -> CRASH KeyError: 'suite'
compare run1 run2      -> CRASH KeyError: 'suite'   (second run carried snippet.json = "[1, 2, 3]")
```

The operator gets a traceback, no report, no exit code. Suggested fix: `r.get("suite")` guarded by `isinstance(r, dict)` with `r.get("suite")` truthy — or filter non-conforming rows once right after load and say so on stderr.

**M-2. `--task-id` / `--category` comma-splitting neither strips whitespace nor drops empty segments — silently running a subset and permanently recording it, while the adjacent `--suite` handling strips** — `benchmarks/src/office_bench/cli.py:163-164` vs `cli.py:158`.

`--suite` gets `[s.strip() for s in args.suite.split(",")]`; two lines later `task_ids` and `categories` get bare `.split(",")`. Space-after-comma is ordinary shell usage, and the `--suite` precedent teaches the operator it is safe.

Reproducer (confirmed 2026-10-01, R2/R2b/R2c/R2d):

```
--category "cat-a, cat-b"   → 1 of 2 tasks runs, exit 0, stderr ''
   backdata row: r2,...,fakesuite,1,1,accuracy,100.0,{}     ← scoped for 2, plausible-looking
--task-id "t1, t2"          → 1 of 2 tasks runs, exit 0, no warning
--task-id ","               → 0 tasks run, exit 0, no warning
   backdata row: r2c,...,fakesuite,0,0,n/a,0.0,{}           ← permanent junk row
--suite " fakesuite , nosuch" → fakesuite fully runs (stripped); nosuch warned+skipped  ✓
```

The R2 row is the nastier one: it is *undetectable after the fact* — a legitimate-looking `1/1 accuracy 100.0` row that misrepresents what was requested, in an append-only CSV. R2c matches the Task 5 M-A damage class (permanent 0/0 `n/a` row) via a flag value that is one stray keystroke (`--task-id "$(cmd)"` with empty output produces the same). Suggested fix: mirror the suite handling — `[t.strip() for t in args.task_id.split(",") if t.strip()]` for both flags.

**M-3. `run` fabricates success on degenerate configurations — including permanent 0/0 CSV rows — and never checks that anything executed** — `benchmarks/src/office_bench/cli.py:69,72` (`--runs`, `--limit` accept any int) and `cli.py:173-177` (unconditional success path).

Two demonstrated triggers (confirmed 2026-10-01, R3/R4/R4b in `/tmp/repro_task6.py`):

```
(a) --suite all with an empty registry (the LIVE state today — suites/ has no adapters
    until Tasks 7-10):  exit 0, stderr '', stdout "Results saved to: …/2026-10-01_083954",
    meta.json + report.md written with zero result rows. No warning that no suite exists.

(b) --runs 0 (also --limit 0, also negative): exit 0, stderr '', and a permanent
    backdata row:  r4,...,fakesuite,0,0,n/a,0.0,{}
```

Case (a) is what any operator who builds the harness before Task 7 lands (or after a broken adapter import) experiences: a successful-looking no-op. Case (b) follows the same path a zero-match filter takes, but `--runs 0` is not an operator intent — it is an invalid config no layer validates (`RunConfig` doesn't either, Task 5). Suggested fix: a positive-int `type=` for `--runs`/`--limit` in the parser, and in `_cmd_run`, exit 1 with a clear stderr message when the registry is empty or when `runner.run()` executed zero suites (the runner already knows `executed`; surfacing it is a small change).

**M-4. `compare` fabricates a Delta and a Status verdict for suites that only one run contains** — `benchmarks/src/office_bench/cli.py:253-258`.

`all_suites = suites1 | suites2` feeds both aggregations; a suite absent from one side gets the empty-input placeholder (`primary_value: 0.0`), and the delta/status math runs on it anyway. The Delta and Status columns are the entire point of the command.

Reproducer (confirmed 2026-10-01, R5): run1 has only `forte` at 45.0, run2 has only `pptc` at 100.0:

```
Suite           Metric       run1         run2         Delta    Status
forte           avg_at_1     45.00        0.00         -45.00   ⚠️
pptc            n/a          0.00         100.00       +100.00  ✅
exit=0
```

An operator scanning for regressions reads "forte regressed by 45 points" when run2 simply never ran forte, and "pptc improved by 100" when run1 never ran pptc. Suggested fix: for a suite missing from either side, print `not run` in the value column and skip the delta/status (or omit the row and note it).

### LOW

**L-1. `setup` reports "Setup complete." and exits 0 regardless of git's outcome, and crashes with a raw `FileNotFoundError` when git is absent** — `benchmarks/src/office_bench/cli.py:121-129`.

`check=False` covers a nonzero exit but the return code is never inspected, and a missing binary isn't covered at all. Confirmed with stub binaries (no network, no submodule touched), 2026-10-01:

```
PATH=/tmp/gitstub_failing:$PATH … main(["setup"])
  → "fatal: repository not found" (from git) … "Setup complete. Verify JUDGE_MODEL…"  exit=0
PATH=/tmp/gitstub_empty … main(["setup"])
  → FileNotFoundError: [Errno 2] No such file or directory: 'git'  (traceback)
```

Plan-verbatim behavior, hence LOW, but the failure message actively misleads ("Setup complete" after a failed clone). Suggested fix: inspect `returncode`, print a stderr error and return 1 on failure; catch `OSError` for the missing-binary case.

**L-2. `trend` truncates to the last 10 rows with no indication that it did so — and the behavior is untested** — `benchmarks/src/office_bench/cli.py:213-214`.

Confirmed (R7): a 15-row CSV prints rows `run06`..`run15`, 10 rows, with no "showing 10 of 15" marker anywhere in the output. The truncation itself is plan-specified ("Show last 10 rows"), so this is a visibility/test gap rather than a defect: no test uses more than two rows, so a regression to `rows[-5:]` or an off-by-one would pass. Suggested fix: print a `showing {n} most recent of {m} rows` line; pin with a >10-row test.

**L-3. Test gaps that let M-1 through M-4 past a 100 %-covered module** — `benchmarks/tests/test_cli.py`.

`cli.py` is 154/154 statements, yet all four mediums are invisible to the suite, because the tests exercise the seams only against mocks and happy-path fixtures: (a) every `run` test patches `Runner` entirely, so the CLI→Runner contract is pinned only at the mock boundary — nothing asserts what backdata row / report a real degenerate config produces (M-2/M-3); (b) no `report`/`compare` test includes a non-result JSON in the run dir (M-1 — the fixtures write only well-formed results); (c) the *correct* `--suite` whitespace stripping (R2d) is itself unpinned, which is exactly the asymmetry M-2 lives in; (d) `compare` is tested only on two runs sharing one suite, never disjoint ones (M-4). Coverage here measures reachability, not behavior — same lesson as Task 5's L-3.

### Observations (correct behavior, noted so it is not re-flagged)

- **Argparse edge behavior is sound, verified live**: no command → help + exit 0 (`main([])`); invalid subcommand `bogus` → clean usage error on stderr, exit 2; `--task-id ""` is falsy → `None` → no filter (the right semantics).
- **`--run-id` on `report`/`compare`/`run` accepts path-y strings** (`RESULTS_BASE / args.run_id` is unvalidated). This is a local operator tool with no security boundary behind it; not flagged, but worth remembering if the CLI ever grows a server wrapper.
- **`RESULTS_BASE`/`DATA_BASE` from `__file__` `parents[3]`** — resolves correctly in the repo's editable/`uv run` layout (verified: probes read `/home/lai/Documents/office-agent/results/benchmarks`). Under a non-editable install it would point outside any repo; plan-verbatim and same class as Task 5's `_agent_version` note.
- **Zero-result `report --run-id X`** on an existing empty run dir regenerates an empty report and exits 0 ("Report regenerated") — defensible given the existence check; the crash variant is M-1.
- **`test_run_suite_all_comma_split_and_run_id`'s `.name` assignments are inert** — verified that `config.suites` comes from registry keys and `Runner` is mocked (`object()` fixtures with registry keys `k1`/`k2` produce `suites == ["k1", "k2"]`). Harmless fixture realism, not a defect.
- **Registry tests do not pollute**: both the `sys.modules` fake-adapter injection and the `builtins.__import__` override go through `monkeypatch` (auto-restored); the suite passed identically standalone (21/21) and in the full run (83/83, twice).
- **Empty registry today**: `list --suite nope` prints `Available: ` with nothing after it — cosmetic; self-resolves as Tasks 7-10 land the adapters.

## Validation Results

| Check | Result | Note |
|-------|--------|------|
| Tests | Pass | `uv run pytest tests/test_cli.py -v` → `21 passed in 0.18s` |
| Full suite | Pass | `uv run pytest tests/ -q` → `83 passed in 5.90s` |
| Coverage | Pass | `cli.py 154/154 (100%)`, `__main__.py 3/3`, package `TOTAL 598/598 (100%)` — matches the commit claim |
| Worktree | Clean | `git diff HEAD -- <reviewed paths>` → 0 lines; untracked only `.claude/skills/`, `.ua/`, `benchmarks/.coverage` |
| CLI probes | Pass | `python -m office_bench --help` exit 0; `list --suite nope` → exit 1 `Available: `; `trend` → exit 1 `No backdata.csv found. Run benchmarks first.`; `bogus` → exit 2 invalid choice |
| Reproducers | Confirmed | `/tmp/repro_task6.py` (R1-R7, all as described); setup stubs in `/tmp/gitstub_failing`, `/tmp/gitstub_empty`. No network touched, no repo file modified |
| TDD shape | Pass | `104e7e6` test-only (+296), `22a1527` adds `cli.py`+`__main__.py` (+267, test delta is one `.lower()` case fix), `3b280f5` +68 test lines |
| Typecheck / Lint | Skipped | none configured for `benchmarks/` (same as Tasks 4-5) |

## Verified strengths

- DoD exceeded on every clause: `list` output, `run`→Runner wiring (registry identity, `RESULTS_BASE` and `run_id` forwarding both asserted), `report` regeneration from existing results, `trend` CSV read + suite filter + empty/missing cases, `compare` delta (`+5.00` asserted), `python -m office_bench --help` via a real subprocess — and the entry point's exit-code forwarding is pinned too.
- Both Task 5 review carries were addressed in this diff, with tests: `--run-id` makes resume reachable from the CLI (`runner.run(tmp_path, run_id="my-run")` asserted), and `--no-resume`'s help text now states that existing files are kept and "the first run's numbers stand".
- Registry construction is genuinely lazy and per-adapter ImportError-tolerant, binding each future adapter to its fixed submodule path (`OfficeBench`, `PPTC`, `SpreadsheetBench-2`, `FORTE` under `data/benchmarks/`) — pinned by the fake-adapter test, with the empty-registry degradation pinned separately.
- Tests are well-isolated: every writable operation patches `RESULTS_BASE` to `tmp_path`; no test touches the network, the gateway, or git submodules (`setup` asserts on a mocked `subprocess`).
- Documented deviations from the plan are all in the right direction, including replacing the plan's unreachable `return 1` with dict dispatch — a coverage-honest refactor, not gold-plating.

## Files Reviewed

- `benchmarks/src/office_bench/cli.py` — Added (259 lines)
- `benchmarks/src/office_bench/__main__.py` — Added (7 lines)
- `benchmarks/tests/test_cli.py` — Added (364 lines)
- Read for context (unchanged): `runner.py`, `results.py`, `reference.py`, `agent_bridge.py`, `suites/base.py`, `docs/superpowers/plans/2026-10-01-benchmark-harness.md` (Task 6), `.claude/reviews/task5-runner-orchestrator-review.md`

## Recommended next steps

1. Fix M-2 and M-3's CSV-writing paths first — they permanently damage the append-only dataset on ordinary operator input; both are 2-5 line parser/`_cmd_run` changes, and R2c/R4 reproductions are ready to become tests.
2. Fix M-1 by matching the `.get`-style guard the rest of the codebase already uses; add one `report` test with a stray `notes.json` (R1 ready to become a test).
3. Fix M-4 by suppressing Delta/Status for suites absent from either side; L-1 by checking `returncode` (and `OSError`) in `_cmd_setup`; L-2 by printing a truncation count.
4. Carry L-3's test gaps into the fix commits — especially one end-to-end `run` test with a real (fake-suite, fake-bridge) Runner rather than a mock, which would have caught M-2/M-3.

**Verdict: REQUEST CHANGES** — two of the four mediums silently write wrong-or-junk rows into the append-only backdata CSV, a third crashes both reporting commands on an input class the codebase's own docstrings call out, and all four are small, test-ready fixes in this repo's established TDD style.

---

## Resolution (2026-10-01)

All seven demonstrable findings fixed in a second TDD loop; re-validated
**96/96 tests, coverage 100%** (`cli.py` 197/197, package 641/641).

| Finding | Resolution | Commit |
|---------|------------|--------|
| M-1 | `report`/`compare` filter loaded rows through `_result_rows()` (dict with truthy `"suite"`) before deriving suites or aggregating. This also shields `aggregate_suite`, whose per-row `.get` turned out to raise `AttributeError` on non-dict stray JSON (a layer below the crash the review demonstrated) — discovered while fixing, covered by the same test. | `620cce1` |
| M-2 | `--task-id`/`--category` (and `--suite`) split via `_split_csv` — strip whitespace, drop empty segments; a filter flag resolving to zero names exits 1 on stderr before the Runner is constructed, so it can never run zero tasks and append a misleading CSV row. End-to-end test (real Runner, fake suite, mock bridge, via `main()`) pins the honest 2/2 row for `"t1, t2"`. | `620cce1` |
| M-3 | `--runs`/`--limit` use a ≥1 argparse type (`0`/negatives/garbage → clean exit 2); `--suite all` with an empty registry and a `--suite` value resolving to zero names exit 1 with a stderr message and never create a run. | `620cce1` |
| M-4 | `compare` prints `not run` in the value column and a bare `—` under Delta/Status for suites absent from either run; no fabricated deltas. | `620cce1` |
| L-1 | `_cmd_setup` inspects git's returncode (exit 1 + stderr on failure) and catches `OSError` for a missing binary; "Setup complete" prints only after success. Both failure modes tested with a mocked `subprocess`. | `620cce1` |
| L-2 | `trend` prints `(showing N most recent of M rows)` whenever it truncates; a 12-row test pins the marker and the truncation itself. | `620cce1` |
| L-3 | All carried: (a) end-to-end `run` test through the real Runner; (b) stray-JSON tests for both reporting commands; (c) the correct `--suite` stripping pinned explicitly; (d) disjoint-suite `compare` test. | `95b0eb3`, `620cce1` |

Observations required no action (argparse edge behavior verified sound by
the reviewer; path-y `--run-id`, non-editable-install `RESULTS_BASE`, and
the empty `Available:` cosmetic remain noted for the future).
