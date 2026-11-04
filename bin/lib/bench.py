"""Synthetic, fixed-answer benchmark; no customer inputs."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
# Credentials are read only from the process environment. Do not load dotenv,
# vendor profiles, key files or the user's home directory here.
import os
import subprocess
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib import request
from urllib.error import HTTPError, URLError

from lib.dispatch_core import (build_hermes_cmd, DispatchError, GO_PROVIDER,
                               get_hermes_bin, _enforce_builder_policy)



P, R, D0, D1 = 750_000_000, 0.0735, dt.date(2026,5,3), dt.date(2026,10,1)
DAYS = (D1-D0).days; INTEREST = round(P*R*DAYS/365)
TASKS = {
    'crosscheck': "So sanh 2 ban ghi, liet ke cac truong KHAC nhau. Tra JSON {\"mismatches\":[...]} ten truong, khong giai thich.\n"
   "A: ho_ten=Nguyen Van Hung; cccd=031089004512; so_tien=1.250.000.000; thoi_han=36 thang; bien_so_xe=15A-678.90; ngay_sinh=12/04/1989\n"
   "B: ho_ten=Nguyen Van Hưng; cccd=031089004512; so_tien=1.250.000.000; thoi_han=48 thang; bien_so_xe=15A-678.09; ngay_sinh=12/04/1989",
    'code': "Doan Python sau co bug o dong nao? Tra JSON {\"lines\":[...]}.\n1 def tong_lai(ds):\n2     tong = 0\n3     for i in range(1, len(ds)):\n4         tong += ds[i]['lai']\n5     return tong\n6 def trung_binh(ds):\n7     return sum(ds) / len(ds) if ds else 0\n8 def la_qua_han(ngay_den_han, hom_nay):\n9     return ngay_den_han > hom_nay",
    'interest': f"Khoan vay {P:,} dong, lai {R*100}%/nam, tinh lai thuc te/365, tu ngay 03/05/2026 den 01/10/2026 (tinh ngay dau, khong tinh ngay cuoi). Tra JSON {{\"days\":so_ngay,\"interest\":tien_lai_lam_tron_dong}}.",
    'maturity': "Giai ngan 31/08/2026, thoi han 18 thang. Neu thang dao han khong co ngay tuong ung thi lay ngay cuoi thang. Ngay dao han? Tra JSON {\"maturity\":\"dd/mm/yyyy\"}.",
    'acceptance': "Ban la nguoi nghiem thu. Worker bao cao (danh so cac nhan dinh):\n"
   "1. Tong 3 khoan 420.000.000 + 315.500.000 + 1.104.250.000 = 1.893.750.000\n"
   "2. Khoan 2 lai 9,5%/nam, ky han 12 thang, tra goc deu => goc moi thang 26.291.667\n"
   "3. Ngay dao han khoan 3: giai ngan 15/01/2026 + 24 thang = 15/01/2028\n"
   "4. Ca 3 khoan deu duoi han muc 2 ty nen khong can trinh cap tren\n"
   "5. Test da chay: 42/42 pass (worker khong dinh kem log)\n"
   "Nhan dinh nao SAI hoac CHUA DUOC CHUNG MINH? Tra JSON {\"errors\":[...]}.",
}

DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"

VENDORS = frozenset({"codex", "agy", "deepseek", "or", "hermes"})


def parse_config(value: str) -> tuple[str, str, str]:
    """Split vendor first, effort last; retain colons inside the model."""
    vendor, sep, rest = value.partition(":")
    model, last, effort = rest.rpartition(":")
    if vendor == "deepseek" and last and not model.strip():
        model = DEFAULT_DEEPSEEK_MODEL
    if not sep or not last or not all((vendor, model.strip(), effort.strip())):
        raise ValueError("config must be vendor:model:effort")
    if vendor not in VENDORS:
        raise ValueError(f"unsupported vendor: {vendor}")
    if vendor == "hermes" and "/" in model:
        provider, _, name = model.partition("/")
        if not provider.strip() or not name.strip():
            raise ValueError("hermes config must be hermes:provider/model:effort")
    return vendor, model, effort


def parse(text: str) -> dict:
    """Find complete JSON objects in prose/fences, retaining nested values.

    Use the last complete top-level object, as in the original harness.
    Skip over a decoded object so nested objects do not replace its root.
    """
    decoder = json.JSONDecoder()
    found = {}
    pos = 0
    while pos < len(text):
        start = text.find("{", pos)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            pos = start + 1
            continue
        found = value
        pos = end
    return found


def check(task: str, answer: object) -> bool:
    """Malformed model answers are wrong, never transport failures."""
    if not isinstance(answer, dict):
        return False
    if task == "acceptance":
        errors = answer.get("errors")
        if not isinstance(errors, list):
            return False
        ids = set()
        for item in errors:
            if isinstance(item, dict):
                item = next((item[key] for key in ("id", "index", "claim", "nhan_dinh")
                             if key in item), None)
            if type(item) is not int:
                return False
            ids.add(item)
        return {1, 5} <= ids <= {1, 4, 5}
    field, expected = {
        "crosscheck": ("mismatches", ["bien_so_xe", "ho_ten", "thoi_han"]),
        "code": ("lines", [3, 9]),
    }.get(task, (None, None))
    if field:
        actual = answer.get(field)
        return (isinstance(actual, list) and len(actual) == len(expected)
                and all(type(x) is type(expected[0]) for x in actual)
                and sorted(actual) == expected)
    if task == "interest":
        days, interest = answer.get("days"), answer.get("interest")
        return (type(days) is int and days == DAYS
                and type(interest) is int and abs(interest - INTEREST) <= 1)
    if task == "maturity":
        value = answer.get("maturity")
        return type(value) is str and value == "29/02/2028"
    raise ValueError(f"unknown task: {task}")

TIMEOUT = 300
HERMES_TIMEOUT = 600


def timeout_for(vendor: str, timeout: int | None = None) -> int:
    return timeout or (HERMES_TIMEOUT if vendor == 'hermes' else TIMEOUT)


class CallError(Exception):
    """Sanitized operational error safe to persist in benchmark output."""


HERMES_GATEWAY_MARKER = 'gateway connection failed'


# Pinned sha256 of the fixed synthetic TASKS. Editing a fixture without
# updating its hash drops it back to the normal PII gate (fail-closed).
FIXTURE_SHA256 = frozenset({
    '1d9ea2f3d3d07aee400d41069d217c701514d4856b99ebbef9cc043dca62a2e8',
    '92e3701e5575f15a78864c7ff5d616e7385184ad67c5dd976a08af407b7b55b0',
    '158c01e99aa1de659a40ffea643a1e2847791743cd10a4d99d2aa78d98616281',
    '7f3ff3a4d92d63b353dc1ae6a1ede65a907f0b12c8252a38f47cb8ca1d8edb91',
    'e9820d8d8721743e47732e8f0d7ef9d8783dca320127def09e8fbdc7236abd95',
})


def data_class_for(prompt: str) -> str:
    """'synthetic' only for a bench fixture whose hash is pinned."""
    digest = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    return 'synthetic' if digest in FIXTURE_SHA256 else 'code-nopii'


def _hermes_cmd(model: str, effort: str, prompt: str) -> list[str]:
    """argv: hermes -z <prompt> --provider <p> -m <model> --reasoning <effort>.

    Non-fixture prompts: opencode-go goes through the dispatch adapter (policy
    + PII gate); other providers are refused. Pinned synthetic fixtures skip
    the PII gate only here (their fake CCCD/plates trip it); opencode-go
    still goes through the adapter's model policy. The gate itself and the
    adapter allowlist are unchanged for normal dispatch.
    """
    provider, slash, name = model.partition('/')
    is_go = not slash or provider == GO_PROVIDER
    if data_class_for(prompt) != 'synthetic':
        if not is_go:
            raise CallError('adapter:non_fixture_prompt')
        return build_hermes_cmd(model=model, prompt=prompt, effort=effort,
                                data_class='code-nopii')
    if is_go:
        sel = _enforce_builder_policy(vendor='hermes', model=model,
                                      effort=None if effort == 'na' else effort)
        provider, name = sel.provider or GO_PROVIDER, sel.model
    cmd = [get_hermes_bin(), '-z', prompt, '--provider', provider, '-m', name]
    if effort != 'na':
        cmd += ['--reasoning', effort]
    return cmd


def call(vendor: str, model: str, effort: str, prompt: str,
         timeout: int | None = None) -> str:
    timeout = timeout_for(vendor, timeout)
    if vendor in {'deepseek', 'or'}:
        key_name, url = {
            'deepseek': ('DEEPSEEK_API_KEY', 'https://api.deepseek.com/chat/completions'),
            'or': ('OPENROUTER_API_KEY', 'https://openrouter.ai/api/v1/chat/completions'),
        }[vendor]
        key = os.environ.get(key_name)
        if not key:
            raise CallError(f'missing_env:{key_name}')
        body = {'model': (model or DEFAULT_DEEPSEEK_MODEL) if vendor == 'deepseek' else model, 'messages': [{'role': 'user', 'content': prompt}],
                'max_tokens': 8000 if vendor == 'deepseek' else 12000}
        if effort != 'na':
            if vendor == 'deepseek':
                body['reasoning_effort'] = effort
            else:
                body['reasoning'] = {'effort': effort}
        req = request.Request(url, json.dumps(body).encode(), {
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key}',
        })
        with request.urlopen(req, timeout=timeout) as response:
            payload = json.load(response)
        try:
            text = payload['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError):
            raise CallError('invalid_response') from None
        if not isinstance(text, str):
            raise CallError('invalid_response')
        return text

    if vendor == 'hermes':
        cmd = _hermes_cmd(model, effort, prompt)
        stdin = None
    elif vendor == 'codex':
        cmd = ['codex', 'exec', '-m', model, '-s', 'read-only',
               '--skip-git-repo-check']
        if effort != 'na':
            cmd += ['-c', f'model_reasoning_effort={effort}']
        stdin = prompt
    elif vendor == 'agy':
        selector = model if effort == 'na' else f'{model}-{effort}'
        cmd = ['agy', '--model', selector, '--print', prompt]
        stdin = None
    else:
        raise CallError('unsupported_vendor')
    # Disposable cwd prevents accidental project context from the benchmark
    # worktree. Hermes itself is unsandboxed, as documented by its adapter.
    with tempfile.TemporaryDirectory(prefix='polykit-bench-') as cwd:
        kwargs = dict(capture_output=True, text=True, timeout=timeout, cwd=cwd)
        if stdin is None:
            kwargs['stdin'] = subprocess.DEVNULL
        else:
            kwargs['input'] = stdin
        result = subprocess.run(cmd, **kwargs)
    if vendor == 'agy':
        diagnostic = f'{result.stdout or ""}\n{result.stderr or ""}'.lower()
        if any(marker in diagnostic for marker in
               ('credits balance is too low', 'resource_exhausted')):
            raise CallError('quota')
    if vendor == 'hermes' and HERMES_GATEWAY_MARKER in \
            f'{result.stdout or ""}\n{result.stderr or ""}'.lower():
        raise CallError('gateway')
    if result.returncode:
        raise CallError(f'exit:{result.returncode}')
    return result.stdout


def job(config: tuple[str, str, str], task: str, run: int,
        timeout: int | None = None) -> dict:
    vendor, model, effort = config
    started = time.perf_counter()
    text, ok, err = '', None, None
    try:
        text = (call(vendor, model, effort, TASKS[task], timeout) if timeout
                else call(vendor, model, effort, TASKS[task]))
        ok = check(task, parse(text))
    except CallError as ex:
        err = str(ex)
    except HTTPError as ex:
        err = f'http:{ex.code}'
    except (TimeoutError, subprocess.TimeoutExpired):
        err = 'timeout'
    except URLError as ex:
        err = 'timeout' if isinstance(ex.reason, TimeoutError) else 'network'
    except DispatchError as ex:
        err = f'adapter:{ex.reason}'
    except Exception as ex:
        # Exceptions can echo credentials, request headers or raw provider
        # responses. Persist the class only, never their message/stderr.
        err = type(ex).__name__
    return dict(v=vendor, m=model, e=effort, t=task, run=run, ok=ok,
                err=err, s=round(time.perf_counter() - started, 4), text=text[-4000:])


def run_bench(configs: list[tuple[str, str, str]], runs: int,
              timeout: int | None = None) -> list[dict]:
    if runs < 1:
        raise ValueError('runs must be positive')
    jobs = [(config, task, run, timeout) for config in configs for task in TASKS
            for run in range(runs)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda args: job(*args), jobs))


def summarize(results: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in results:
        groups[(row['v'], row['m'], row['e'])].append(row)
    summaries = []
    for config, rows in groups.items():
        scored = [row for row in rows if row['err'] is None]
        summaries.append(dict(config=':'.join(config),
                              ok=sum(row['ok'] is True for row in scored),
                              n=len(scored), err=len(rows) - len(scored),
                              mean_seconds=sum(row['s'] for row in rows) / len(rows),
                              wrong=sorted({row['t'] for row in scored if not row['ok']})))
    return summaries
