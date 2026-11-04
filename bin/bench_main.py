#!/usr/bin/env python3
"""PolyKit synthetic benchmark command (also registered as /polykit:bench)."""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from lib.bench import parse_config, run_bench, summarize

DEFAULT_OUTPUT_DIR = Path.home() / 'Claude' / 'Build' / 'tools' / 'bench'


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('runs must be positive')
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=positive_int, default=1)
    parser.add_argument('--timeout', type=positive_int, default=None,
                        help='giay moi call (mac dinh 300, hermes 600)')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument('configs', nargs='+', type=parse_config,
                        metavar='vendor:model:effort')
    args = parser.parse_args(argv)
    # Repeating a config should not silently double its requested runs.
    configs = list(dict.fromkeys(args.configs))
    output_dir = args.output_dir.expanduser()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        # Reserve output before spending calls; unique even within one second.
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         prefix='bench-', suffix='.json',
                                         dir=output_dir, delete=False) as out:
            results = run_bench(configs, args.runs, args.timeout)
            summary = summarize(results)
            json.dump(dict(schema_version=1,
                           created_at=datetime.now(timezone.utc).isoformat(),
                           runs=args.runs, results=results, summary=summary),
                      out, ensure_ascii=False, indent=2)
            out.write('\n')
            path = out.name
    except OSError as ex:
        parser.exit(1, f'bench: output/runner error ({type(ex).__name__})\n')
    print(f'{"config":60} {"ok/n":9} {"err":5} {"giay TB":>9}  task sai')
    for row in summary:
        print(f'{row["config"]:60} {row["ok"]}/{row["n"]:<7} '
              f'{row["err"]:<5} {row["mean_seconds"]:9.2f}  '
              f'{", ".join(row["wrong"]) or "-"}')
    print(f'JSON: {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
