import pytest

from lib import bench


@pytest.mark.parametrize('text', [
    '{"nested":{"x":1},"items":[1,2]}',
    'noise ```json\n{"nested":{"x":1},"items":[1,2]}\n``` tail',
    'broken {xxx} then {"nested":{"x":1},"items":[1,2]} trailing {oops}',
])
def test_parse_json_noise_and_nesting(text):
    assert bench.parse(text) == {"nested": {"x": 1}, "items": [1, 2]}


@pytest.mark.parametrize('text', ['', 'no json', '[]', 'null'])
def test_parse_no_object(text):
    assert bench.parse(text) == {}


def test_parse_config_colons():
    assert bench.parse_config('or:vendor/x:free:na') == ('or', 'vendor/x:free', 'na')


@pytest.mark.parametrize('cfg', ['or:x', ':x:low', 'or::low', 'or:x:', 'unknown:x:low'])
def test_bad_config(cfg):
    with pytest.raises(ValueError):
        bench.parse_config(cfg)


@pytest.mark.parametrize('task,answer', [
    ('crosscheck', {'mismatches': ['ho_ten', 'bien_so_xe', 'thoi_han']}),
    ('code', {'lines': [9, 3]}),
    ('interest', {'days': 151, 'interest': 22805137}),
    ('maturity', {'maturity': '29/02/2028'}),
    ('acceptance', {'errors': [5, 1, 4]}),
])
def test_task_checkers(task, answer):
    assert bench.check(task, answer)
    assert not bench.check(task, {})


@pytest.mark.parametrize('answer', [None, [], {'lines': None}, {'lines': [True, 9]}, {'lines': [3, 3, 9]}])
def test_checker_malformed_answers_are_wrong(answer):
    assert not bench.check('code', answer)


@pytest.mark.parametrize('answer', [
    {'days': 151, 'interest': 'nan'},
    {'days': 151, 'interest': 22805137.9},
    {'days': 151, 'interest': True},
    {'days': 151, 'interest': 0},
])
def test_interest_rejects_invalid_values(answer):
    assert not bench.check('interest', answer)

import json
import subprocess
from urllib.error import HTTPError
from unittest.mock import Mock


@pytest.mark.parametrize('error', [TimeoutError(), HTTPError('url', 429, 'secret', {}, None),
                                    subprocess.TimeoutExpired(['cmd'], 300)])
def test_transport_errors_are_separate(monkeypatch, error):
    monkeypatch.setattr(bench, 'call', Mock(side_effect=error))
    row = bench.job(('or', 'x:free', 'na'), 'code', 0)
    assert row['ok'] is None
    assert row['err']
    assert row['s'] >= 0
    summary = bench.summarize([row])[0]
    assert (summary['ok'], summary['n'], summary['err'], summary['wrong']) == (0, 0, 1, [])
    assert 'secret' not in json.dumps(row)


def test_wrong_answers_count_without_errors(monkeypatch):
    monkeypatch.setattr(bench, 'call', lambda *args: '{"lines":null}')
    row = bench.job(('or', 'x', 'na'), 'code', 0)
    summary = bench.summarize([row])[0]
    assert row['ok'] is False and row['err'] is None
    assert (summary['ok'], summary['n'], summary['err'], summary['wrong']) == (0, 1, 0, ['code'])


@pytest.mark.parametrize('vendor,key', [('or', 'OPENROUTER_API_KEY'), ('deepseek', 'DEEPSEEK_API_KEY')])
def test_http_env_and_payload(monkeypatch, vendor, key):
    monkeypatch.setenv(key, 'test-only-key')
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b'{"choices":[{"message":{"content":"answer"}}]}'
    opener = Mock(return_value=response)
    monkeypatch.setattr(bench.request, 'urlopen', opener)
    assert bench.call(vendor, 'x:free', 'low', 'synthetic prompt') == 'answer'
    req = opener.call_args.args[0]
    assert req.get_header('Authorization') == 'Bearer test-only-key'
    assert json.loads(req.data)['model'] == 'x:free'


def test_missing_key_never_calls_network(monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    opener = Mock(side_effect=AssertionError('network forbidden'))
    monkeypatch.setattr(bench.request, 'urlopen', opener)
    row = bench.job(('or', 'x', 'na'), 'code', 0)
    assert row['ok'] is None and row['err'] == 'missing_env:OPENROUTER_API_KEY'
    opener.assert_not_called()


@pytest.mark.parametrize('vendor', ['agy', 'codex', 'hermes'])
def test_cli_nonzero_is_error_even_with_answer(monkeypatch, vendor):
    monkeypatch.setattr(bench, 'build_hermes_cmd', lambda **kwargs: ['hermes', '-z', kwargs['prompt']])
    monkeypatch.setattr(bench.subprocess, 'run', Mock(return_value=
                        subprocess.CompletedProcess([], 2, '{"lines":[3,9]}', 'secret')))
    model = 'glm-5.3-flash' if vendor == 'hermes' else 'x'
    row = bench.job((vendor, model, 'low'), 'code', 0)
    assert row['ok'] is None and row['err'] == 'exit:2'
    assert 'secret' not in json.dumps(row)


def test_codex_retains_complete_stdout(monkeypatch):
    answer = '{\n"lines": [\n3,\n9\n]\n}\n'
    monkeypatch.setattr(bench.subprocess, 'run', Mock(return_value=
                        subprocess.CompletedProcess([], 0, answer, '')))
    assert bench.job(('codex', 'x', 'low'), 'code', 0)['ok'] is True


def test_hermes_reuses_adapter(monkeypatch):
    builder = Mock(return_value=['hermes-adapter'])
    monkeypatch.setattr(bench, 'build_hermes_cmd', builder)
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, 'answer', ''))
    monkeypatch.setattr(bench.subprocess, 'run', runner)
    assert bench.call('hermes', 'glm-5.3-flash', 'low', 'prompt') == 'answer'
    assert builder.call_args.kwargs == dict(model='glm-5.3-flash', prompt='prompt',
                                             effort='low', data_class='code-nopii')
    assert runner.call_args.args[0] == ['hermes-adapter']


def test_cli_writes_unique_json_and_summary(monkeypatch, tmp_path, capsys):
    import bench_main as cli
    monkeypatch.setattr(bench, 'call', lambda *args: '{"lines":[3,9]}')
    args = ['--runs', '2', '--output-dir', str(tmp_path / 'out'), 'or:x:free:na']
    assert cli.main(args) == 0
    assert cli.main(args) == 0
    paths = list((tmp_path / 'out').glob('*.json'))
    assert len(paths) == 2
    payload = json.loads(paths[0].read_text())
    assert payload['schema_version'] == 1
    assert len(payload['results']) == 10
    assert payload['summary'][0]['ok'] == 2
    assert payload['summary'][0]['n'] == 10
    output = capsys.readouterr().out
    assert all(x in output for x in ['config', 'ok/n', 'err', 'giay TB', 'task sai', 'or:x:free:na'])


@pytest.mark.parametrize('args', [[], ['--runs', '0', 'or:x:na'], ['--runs', '-1', 'or:x:na'], ['or:x']])
def test_cli_bad_args(args):
    import bench_main as cli
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2


@pytest.mark.parametrize('errors', [
    [1, 5], [5, 4, 1], [1, 1, 5],
    [{'id': 1}, {'index': 5}],
    [{'claim': 1}, {'nhan_dinh': 4}, 5],
])
def test_acceptance_normalizes_required_and_optional_ids(errors):
    assert bench.check('acceptance', {'errors': errors})


@pytest.mark.parametrize('errors', [[1], [5], [1, 2, 5], [1, 5, {}],
                                    [True, 5], ['1', 5], [{'id': []}, 5]])
def test_acceptance_rejects_invalid_ids(errors):
    assert bench.check('acceptance', {'errors': errors}) is False


@pytest.mark.parametrize('task', bench.TASKS)
@pytest.mark.parametrize('value', [None, [], True, 1, 'x', {}, {'x': []}])
def test_all_checkers_reject_wrong_field_types(task, value):
    field = {'crosscheck': 'mismatches', 'code': 'lines', 'interest': 'interest',
             'maturity': 'maturity', 'acceptance': 'errors'}[task]
    assert bench.check(task, {field: value}) is False


@pytest.mark.parametrize('length', [301, 4000, 4500])
def test_job_retains_last_4000_characters(monkeypatch, length):
    output = 'a' * length + '{"lines":[3,9]}'
    monkeypatch.setattr(bench, 'call', lambda *args: output)
    row = bench.job(('codex', 'x', 'low'), 'code', 0)
    assert row['ok'] is True
    assert row['text'] == output[-4000:]


@pytest.mark.parametrize('message', ['credits balance is too low', 'RESOURCE_EXHAUSTED'])
@pytest.mark.parametrize('returncode', [0, 1])
@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_agy_quota_is_operational_error(monkeypatch, message, returncode, stream):
    streams = {'stdout': '', 'stderr': ''}
    streams[stream] = message
    monkeypatch.setattr(bench.subprocess, 'run', lambda *a, **kw:
                        subprocess.CompletedProcess([], returncode, **streams))
    row = bench.job(('agy', 'x', 'low'), 'code', 0)
    assert row['ok'] is None and row['err'] == 'quota'
    assert bench.summarize([row])[0]['n'] == 0


@pytest.mark.parametrize('effort', ['low', 'high', 'max'])
def test_deepseek_current_model_payload(monkeypatch, effort):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-only-key')
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b'{"choices":[{"message":{"content":"answer"}}]}'
    def open_request(req, **kwargs):
        payload = json.loads(req.data)
        assert payload['model'] == 'deepseek-flash'
        assert payload['reasoning_effort'] == effort
        return response
    monkeypatch.setattr(bench.request, 'urlopen', open_request)
    assert bench.call('deepseek', '', effort, 'prompt') == 'answer'


def test_deepseek_omitted_model_uses_api_default():
    assert bench.parse_config('deepseek::high') == ('deepseek', 'deepseek-flash', 'high')


def test_hermes_config_provider_form():
    assert bench.parse_config('hermes:xai-oauth/grok-4.7:low') == ('hermes', 'xai-oauth/grok-4.7', 'low')
    assert bench.parse_config('hermes:opencode-go/glm-5.3-flash:high')[1] == 'opencode-go/glm-5.3-flash'
    for bad in ('hermes:/grok:low', 'hermes:xai-oauth/:low'):
        with pytest.raises(ValueError):
            bench.parse_config(bad)


def test_hermes_go_provider_uses_adapter(monkeypatch):
    builder = Mock(return_value=['hermes-adapter'])
    monkeypatch.setattr(bench, 'build_hermes_cmd', builder)
    assert bench._hermes_cmd('opencode-go/glm-5.3-flash', 'high', 'p') == ['hermes-adapter']
    assert builder.call_args.kwargs['model'] == 'opencode-go/glm-5.3-flash'


def test_hermes_other_provider_argv(monkeypatch):
    monkeypatch.setattr(bench, 'get_hermes_bin', lambda: 'hermes')
    builder = Mock(side_effect=AssertionError('adapter not for xai'))
    monkeypatch.setattr(bench, 'build_hermes_cmd', builder)
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, '{"lines":[3,9]}', ''))
    monkeypatch.setattr(bench.subprocess, 'run', runner)
    row = bench.job(('hermes', 'xai-oauth/grok-4.7', 'low'), 'code', 0)
    assert row['ok'] is True and row['err'] is None
    assert runner.call_args.args[0] == ['hermes', '-z', bench.TASKS['code'], '--provider',
                                        'xai-oauth', '-m', 'grok-4.7', '--reasoning', 'low']
    assert runner.call_args.kwargs['stdin'] is subprocess.DEVNULL


@pytest.mark.parametrize('model', ['opencode-go/glm-5.3-flash', 'xai-oauth/grok-4.7',
                                   'openai-codex/gpt-6.1-sol'])
@pytest.mark.parametrize('task', ['crosscheck', 'code'])
def test_fixture_runs_on_non_train_hermes_lane(monkeypatch, model, task):
    from lib import go_data_gate
    monkeypatch.setattr(go_data_gate, '_which', lambda name: '/fake/pg-redact')
    monkeypatch.setattr(go_data_gate, '_checker_runner', Mock(side_effect=AssertionError('no gate')))
    monkeypatch.setattr(bench, 'get_hermes_bin', lambda: 'hermes')
    cmd = bench._hermes_cmd(model, 'high', bench.TASKS[task])
    provider, _, name = model.partition('/')
    assert cmd[0].endswith('hermes') and cmd[1] == '-z'
    assert cmd[3:7] == ['--provider', provider, '-m', name]


def _fake_pii_checker(monkeypatch):
    from lib import go_data_gate
    monkeypatch.setattr(go_data_gate, '_which', lambda name: '/fake/pg-redact')
    monkeypatch.setattr(go_data_gate, '_checker_runner', lambda *a, **k:
                        subprocess.CompletedProcess([], 1, '', ''))


CCCD_PROMPT = 'Kiem tra ho so khach Nguyen Van A, CCCD 031089004512, SDT 0912345678'


def test_train_lane_with_cccd_blocked(monkeypatch):
    _fake_pii_checker(monkeypatch)
    with pytest.raises(bench.CallError) as ex:
        bench._hermes_cmd('openrouter/meta/muse-spark-2-contributor', 'low', CCCD_PROMPT)
    assert str(ex.value) == 'adapter:pii_detected'
    from lib.go_data_gate import evaluate_go_data_gate, GoDataGateBlocked
    for model in ('vendor/x:free', 'vendor/x-free', 'x-contributor'):
        with pytest.raises(GoDataGateBlocked):
            evaluate_go_data_gate(data_class='code-nopii', prompt=CCCD_PROMPT,
                                  vendor='hermes', model=model)


def test_non_train_lane_with_cccd_passes(monkeypatch):
    _fake_pii_checker(monkeypatch)
    monkeypatch.setattr(bench, 'get_hermes_bin', lambda: 'hermes')
    for model in ('opencode-go/glm-5.3-flash', 'xai-oauth/grok-4.7', 'openai-codex/gpt-6.1-sol'):
        assert bench._hermes_cmd(model, 'low', CCCD_PROMPT)[2] == CCCD_PROMPT


def test_trains_on_data_patterns():
    from lib.model_policy import trains_on_data
    for m in ('a-contributor', 'vendor/x:free', 'x-free', 'meta/muse-spark-2-contributor', None, ''):
        assert trains_on_data(m)
    for m in ('glm-5.3-flash', 'deepseek-v4.1-flash', 'grok-4.7', 'gpt-6.1-sol', 'deepseek-flash'):
        assert not trains_on_data(m)


def test_hermes_default_timeout_600(monkeypatch):
    monkeypatch.setattr(bench, 'get_hermes_bin', lambda: 'hermes')
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, 'a', ''))
    monkeypatch.setattr(bench.subprocess, 'run', runner)
    bench.call('hermes', 'xai-oauth/grok-4.7', 'low', bench.TASKS['code'])
    assert runner.call_args.kwargs['timeout'] == 600
    bench.call('hermes', 'xai-oauth/grok-4.7', 'low', bench.TASKS['code'], 42)
    assert runner.call_args.kwargs['timeout'] == 42
    bench.call('codex', 'x', 'low', 'p')
    assert runner.call_args.kwargs['timeout'] == 300


@pytest.mark.parametrize('code,out,err', [(0, '{"lines":[3,9]}', 'Gateway connection failed'),
                                          (1, 'Error: Gateway connection failed: x', '')])
def test_hermes_gateway_failure_is_err(monkeypatch, code, out, err):
    monkeypatch.setattr(bench, 'get_hermes_bin', lambda: 'hermes')
    monkeypatch.setattr(bench.subprocess, 'run', Mock(return_value=
                        subprocess.CompletedProcess([], code, out, err)))
    row = bench.job(('hermes', 'xai-oauth/grok-4.7', 'low'), 'code', 0)
    assert row['ok'] is None and row['err'] == 'gateway'
    assert bench.summarize([row])[0]['n'] == 0
