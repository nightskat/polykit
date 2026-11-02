"""BUG-16 — `--cd` có hiệu lực nhất quán cho mọi vendor CLI.

Subprocess thật với agy GIẢ (không có workdir_flag): vendor giả đọc file mốc
trong cwd của chính nó ⇒ chứng minh tiến trình con chạy ĐÚNG thư mục --cd.
Claude vẫn bounded/no-tools (SPEC P3): --cd bị bỏ qua có cảnh báo, argv không đổi.
"""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

from fake_cli import make_fake_agy, read_calls
from lib.dispatcher import run_vendor
from lib.states import VendorProbe

DISPATCH = Path(__file__).resolve().parents[1] / "bin" / "dispatch.py"


def _run(args, env, cwd=None):
    return subprocess.run([sys.executable, str(DISPATCH), *args, "--result-json", "--no-traps"],
                          capture_output=True, text=True, timeout=60, env=env, cwd=cwd)


def _ready(spec):
    return VendorProbe(name=spec.name, path=f"/fake/{spec.name}", authed=True,
                       quota_capped=False, version="1.0", models=[], error=None)


def _rec_runner(calls):
    def _r(cmd, **kw):
        calls.append((cmd, kw))
        m = MagicMock(); m.returncode = 0; m.stdout = "OK"; m.stderr = ""
        return m
    return _r


def test_agy_gia_doc_file_moc_trong_cd(tmp_path):
    env = make_fake_agy(tmp_path)
    work = tmp_path / "work"; work.mkdir()
    (work / "MOC.txt").write_text("moc-bug16-xyz", encoding="utf-8")
    other = tmp_path / "other"; other.mkdir()
    r = _run(["agy", "--cd", str(work), "--prompt", "READ:MOC.txt"], env, cwd=other)
    res = json.loads(r.stdout)
    assert res["status"] == "ok", res
    assert "moc-bug16-xyz" in res["stdout"]
    spawn = [c for c in read_calls(env) if "-p" in c["argv"]][-1]
    assert Path(spawn["cwd"]) == work.resolve()


def test_khong_cd_thi_chay_o_cwd_cha(tmp_path):
    """Đối chứng: không --cd ⇒ vendor không thấy file mốc."""
    env = make_fake_agy(tmp_path)
    work = tmp_path / "work"; work.mkdir()
    (work / "MOC.txt").write_text("moc", encoding="utf-8")
    other = tmp_path / "other"; other.mkdir()
    r = _run(["agy", "--prompt", "READ:MOC.txt"], env, cwd=other)
    assert "MISSING:" in json.loads(r.stdout)["stdout"]


def test_artifact_tuong_doi_ghi_vao_cd(tmp_path):
    env = make_fake_agy(tmp_path)
    work = tmp_path / "work"; work.mkdir()
    r = _run(["agy", "--cd", str(work), "--sandbox", "workspace-write",
              "--expect-artifact", "rel.txt", "--prompt", "WRITE:rel.txt"], env, cwd=tmp_path)
    assert json.loads(r.stdout)["status"] == "ok"
    assert (work / "rel.txt").exists()


def test_cd_khong_ton_tai_bi_chan_truoc_spawn(tmp_path):
    env = make_fake_agy(tmp_path)
    r = _run(["agy", "--cd", str(tmp_path / "khong-co"), "--prompt", "hi"], env)
    res = json.loads(r.stdout)
    assert res["status"] == "blocked"
    assert "--cd" in res["summary"]
    assert read_calls(env) == []


def test_dsh_va_codex_nhan_cwd(tmp_path):
    for vendor in ("dsh", "codex"):
        calls = []
        run_vendor(vendor, "hi", workdir=str(tmp_path), runner=_rec_runner(calls), detector=_ready)
        assert calls, vendor
        assert all(kw.get("cwd") == str(tmp_path.resolve()) for _, kw in calls), vendor


def test_claude_van_bounded_va_canh_bao_cd(tmp_path):
    calls = []
    r = run_vendor("claude", "hi", workdir=str(tmp_path), runner=_rec_runner(calls), detector=_ready)
    assert any("KHÔNG áp dụng cho claude" in w for w in r.warnings)
    cmd, kw = calls[-1]
    assert "cwd" not in kw
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--permission-mode") + 1] == "plan"
    assert "--dangerously-skip-permissions" not in cmd
