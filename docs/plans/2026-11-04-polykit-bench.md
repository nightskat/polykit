# PolyKit bench implementation

Spec: `BRIEF-bench.md`. Existing isolated worktree: `feat/polykit-bench`.
Use stdlib only; no live vendor calls during verification; no push.

1. Extract five fixed synthetic tasks into `bin/lib/bench.py`; implement JSON
   extraction, strict checkers and vendor:model:effort parsing. Test fenced/noisy
   and nested JSON, malformed answers, every task, model names containing colons.
   Run focused pytest and commit.
2. Add runner, aggregation and `bin/bench_main.py`; register `commands/bench.md` like
   existing commands. Reuse `build_hermes_cmd` including its policy/data gate.
   HTTP keys come only from env. Nonzero exits/HTTP/timeouts/missing credentials
   are err with ok=null, excluded from n and wrong-task list. Invalid answers
   are wrong. Preserve elapsed time on errors. JSON includes schema_version.
   Test all transports with mocks, output directory, CLI validation and summary;
   run focused tests and commit.
3. Replace raw harness with compatibility entry point; document Bench and traps
   in GUIDE-DIEU-PHOI and README. Run full pytest suite, inspect diff and commit.

Review focus: unsupported config before calls; nonzero CLI with plausible JSON;
malformed answer must not become transport err; no credential/error text leaked;
unique output files and all-error denominator zero. Existing adapter policy may
block Hermes configs or synthetic PII: report err, never bypass the gate.

## Execution result (2026-11-04)

- Steps 1–3 implemented. CLI is `bin/bench_main.py` (not `bin/bench.py`):
  the latter shadows the existing `bench.vision` namespace when tests put
  `bin/` first on sys.path. Full-suite collection caught this; renamed all callers.
- Fixed tests were written and run before implementation (27 core cases;
  another 17 runner/CLI cases initially failed, then passed).
- Verification: Python 3.11.8, `python -m pytest tests/ -q`:
  **1143 passed in 43.00s**. Focused bench suite: **44 passed**.
  Both CLI/wrapper `--help` work. `git diff --check` clean.
- Independent reviewer: no findings, approved subject to full-suite success;
  that condition has now passed. No live vendor/network calls for bench tests.
- Commits BLOCKED: `git add` and `git commit` both failed with
  `Unable to create '/Users/nightskat/Developer/polykit/.git/worktrees/polykit-bench/index.lock': Operation not permitted`.
  Linked-worktree Git metadata is outside the writable sandbox; approval is
  unavailable in this session. No commits created and no push attempted.
  BRIEF-bench.md was already untracked and has been preserved unchanged.
- Intended commit groups for an environment with Git metadata write access:
  1. `bin/lib/bench.py`, `tests/test_bench.py`, this plan: benchmark core/runner.
  2. `bin/bench_main.py`, `commands/bench.md`, `bench/bench_main_worker.py`:
     command registration and compatibility wrapper.
  3. `README.md`, `docs/GUIDE-DIEU-PHOI.md`: Bench usage and traps.
