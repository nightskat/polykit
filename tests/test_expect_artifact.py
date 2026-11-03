"""Việc 1 — giao việc GHI FILE: opt-in workspace-write + kiểm artifact kỳ vọng.
Chỉ dùng agy GIẢ (tests/fake_cli.py), không gọi vendor thật."""
import json
import subprocess
import sys
from pathlib import Path

from fake_cli import make_fake_agy, read_calls

DISPATCH = Path(__file__).resolve().parents[1] / "bin" / "dispatch.py"


def _run(args, env, cwd=None):
    return subprocess.run([sys.executable, str(DISPATCH), "agy", *args, "--result-json", "--no-traps"],
                          capture_output=True, text=True, timeout=60, env=env, cwd=cwd)


def test_ghi_that_artifact_ok(tmp_path):
    env = make_fake_agy(tmp_path)
    out = tmp_path / "out.txt"
    r = _run(["--sandbox", "workspace-write", "--expect-artifact", str(out),
              "--prompt", f"WRITE:{out}"], env)
    res = json.loads(r.stdout)
    assert r.returncode == 0, r.stderr
    assert res["status"] == "ok"
    assert out.exists()
    assert any("artifact ok" in w for w in res["warnings"])
    # opt-in workspace-write ⇒ cờ auto-approve của agy được nối vào argv
    assert "--dangerously-skip-permissions" in read_calls(env)[-1]["argv"]


def test_vendor_bao_xong_nhung_khong_ghi_thi_error(tmp_path):
    env = make_fake_agy(tmp_path)
    r = _run(["--sandbox", "workspace-write", "--expect-artifact", str(tmp_path / "khong.txt"),
              "--prompt", "CLAIM_ONLY"], env)
    res = json.loads(r.stdout)
    assert r.returncode == 1
    assert res["status"] == "error"
    assert res["reason"] == "artifact_missing"
    assert any("artifact_missing" in w for w in res["warnings"])


def test_file_cu_con_sot_khong_tinh(tmp_path):
    import os, time
    env = make_fake_agy(tmp_path)
    old = tmp_path / "cu.txt"
    old.write_text("cũ")
    t = time.time() - 3600
    os.utime(old, (t, t))
    r = _run(["--sandbox", "workspace-write", "--expect-artifact", str(old),
              "--prompt", "CLAIM_ONLY"], env)
    res = json.loads(r.stdout)
    assert res["reason"] == "artifact_missing"
    assert any("artifact_stale" in w for w in res["warnings"])


def test_expect_artifact_ma_read_only_bi_chan_truoc_spawn(tmp_path):
    env = make_fake_agy(tmp_path)
    r = _run(["--expect-artifact", "x.txt", "--prompt", "WRITE:x.txt"], env, cwd=tmp_path)
    res = json.loads(r.stdout)
    assert r.returncode == 2
    assert res["status"] == "blocked"
    assert read_calls(env) == []  # không probe, không spawn
    assert not (tmp_path / "x.txt").exists()


def test_mac_dinh_read_only_khong_noi_co_auto_approve(tmp_path):
    env = make_fake_agy(tmp_path)
    r = _run(["--prompt", "hello"], env)
    assert json.loads(r.stdout)["status"] == "ok"
    assert "--dangerously-skip-permissions" not in read_calls(env)[-1]["argv"]


def test_auto_approve_la_mo_ta_thi_khong_noi_vao_lenh():
    from lib.dispatcher import run_vendor  # noqa: F401  (import path check)
    import lib.dispatcher as d
    src = Path(d.__file__).read_text(encoding="utf-8")
    assert 'auto.startswith("-")' in src


def test_file_co_san_mtime_khong_doi_la_stale_du_trong_slack(tmp_path):
    """Snapshot trước lượt chạy: file vừa touch (trong slack 2s) nhưng vendor không ghi ⇒ stale."""
    import time as _t
    from lib.artifacts import check_artifacts, snapshot_artifacts
    f = tmp_path / "out.txt"
    f.write_text("cũ")
    since = _t.time()
    before = snapshot_artifacts(["out.txt"], str(tmp_path))
    ok, bad = check_artifacts(["out.txt"], str(tmp_path), since, before=before)
    assert ok == [] and "artifact_stale" in bad[0]
    _t.sleep(0.01)
    f.write_text("mới")
    ok, bad = check_artifacts(["out.txt"], str(tmp_path), since, before=before)
    assert bad == [] and "artifact ok" in ok[0]
