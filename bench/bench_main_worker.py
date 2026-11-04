"""Compatibility wrapper for the old positional-runs harness.

Prefer python3 bin/bench_main.py --runs N vendor:model:effort [...].
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from bench_main import main

if __name__ == '__main__':
    args = sys.argv[1:]
    if args and not args[0].startswith('-'):
        args = ['--runs', args[0], *args[1:]]
    raise SystemExit(main(args))
