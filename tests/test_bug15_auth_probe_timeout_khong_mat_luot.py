"""BUG-15 (23/08/2026): probe auth timeout CỨNG 10s làm MẤT TRẮNG cả lượt dispatch.

`agy models` là lệnh GỌI MẠNG, không phải kiểm cục bộ: máy rảnh 2,2-3,1s, máy tải
nặng tới 8,2s, thỉnh thoảng vượt 10s. Vượt là dispatcher trả `skipped:
auth_unverified`, exit 1, stdout 0 byte — prompt bay mất dù credential còn sống.

Kiểm-tra-tư-cách gọi mạng là PHÉP ĐO chịu ảnh hưởng của tải máy, không phải hằng số.
"""
import subprocess

import pytest

from lib.dispatcher import run_vendor
from lib.vendors import detect, REGISTRY, VendorSpec


def _spec(**kw):
    base = dict(name="giavendor", binary="giavendor", auth_hint="chạy giavendor login",
                version_cmd=["giavendor", "--version"],
                auth_check_cmd=["giavendor", "models"])
    base.update(kw)
    return VendorSpec(**base)


def _ok(stdout="acme/model-x\n"):
    class R:
        returncode = 0
        stderr = ""
    R.stdout = stdout
    return R


# ---------- 1. timeout theo loại lệnh, không cứng 10s ----------

def test_agy_duoc_timeout_30s_con_probe_cuc_bo_giu_10s():
    assert REGISTRY["agy"].auth_check_timeout == 30, "probe gọi mạng phải được nới"
    for ten in ("codex", "grok", "gemini"):
        assert REGISTRY[ten].auth_check_timeout == 10, (
            f"{ten}: probe cục bộ phải giữ 10s để hỏng thật còn báo nhanh")


def test_timeout_cua_spec_duoc_truyen_thuc_su_xuong_subprocess():
    """Khai 30 trong spec mà vẫn gọi subprocess với 10 thì khai để trang trí."""
    ghi = []

    def runner(cmd, **kw):
        ghi.append((cmd[-1], kw.get("timeout")))
        return _ok()

    detect(_spec(auth_check_timeout=30, auth_check_authoritative=False),
           which=lambda _: "/fake/giavendor", runner=runner)
    assert ("models", 30) in ghi, f"probe auth không dùng timeout của spec: {ghi}"


# ---------- 2. timeout + non-authoritative → thử lại ĐÚNG 1 lần ----------

def test_probe_timeout_khong_authoritative_thi_thu_lai_dung_mot_lan():
    lan = []

    def runner(cmd, **kw):
        if cmd[-1] == "models":
            lan.append(1)
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        return _ok("v1.0")

    detect(_spec(auth_check_authoritative=False),
           which=lambda _: "/fake/giavendor", runner=runner)
    assert len(lan) == 2, f"phải thử lại đúng 1 lần (tổng 2 lượt), thực tế {len(lan)}"


def test_lan_thu_hai_thanh_cong_thi_coi_nhu_ready():
    lan = []

    def runner(cmd, **kw):
        if cmd[-1] == "models":
            lan.append(1)
            if len(lan) == 1:
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
            return _ok()
        return _ok("v1.0")

    p = detect(_spec(auth_check_authoritative=False),
               which=lambda _: "/fake/giavendor", runner=runner)
    assert p.authed is True, f"lượt 2 chạy được mà vẫn không authed: {p.error!r}"


def test_probe_authoritative_thi_khong_ton_them_luot_cho():
    lan = []

    def runner(cmd, **kw):
        if cmd[-1] == "models":
            lan.append(1)
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        return _ok("v1.0")

    detect(_spec(auth_check_authoritative=True),
           which=lambda _: "/fake/giavendor", runner=runner)
    assert len(lan) == 1, "probe authoritative: hết giờ là kết luận được, đừng chờ thêm"


# ---------- 3. vẫn hỏng → CỨ DISPATCH, đừng vứt lượt ----------

def test_auth_unverified_van_dispatch_chu_khong_mat_trang_luot():
    """Lỗi gốc BUG-15: user chỉ đích danh vendor thì không còn lane nào để degrade
    sang — 'skip' ở đây nghĩa là mất trắng prompt."""
    goi = []

    def detector(spec):
        from lib.states import VendorProbe
        return VendorProbe(name="agy", path="/fake/agy", authed=None, quota_capped=False,
                           error="auth_probe_unverified — timeout sau 60.0s")

    def runner(cmd, **kw):
        goi.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "OK", "stderr": ""})()

    r = run_vendor("agy", "xin chào", model="claude-opus-4-6-thinking",
                   runner=runner, detector=detector)
    assert goi, "KHÔNG gọi vendor lượt nào — prompt bay mất, đúng lỗi BUG-15"
    assert r.status != "skipped", f"vẫn skip: {r.summary}"
    assert r.stdout == "OK"


def test_van_dispatch_nhung_phai_canh_bao_ro_trong_result():
    def detector(spec):
        from lib.states import VendorProbe
        return VendorProbe(name="agy", path="/fake/agy", authed=None, quota_capped=False,
                           error="auth_probe_unverified — timeout sau 60.0s")

    def runner(cmd, **kw):
        return type("R", (), {"returncode": 0, "stdout": "OK", "stderr": ""})()

    r = run_vendor("agy", "xin chào", runner=runner, detector=detector)
    canh_bao = " ".join(r.warnings)
    assert "auth" in canh_bao.lower(), f"dispatch mù, không cảnh báo gì: {r.warnings}"
    assert "timeout sau 60.0s" in canh_bao, (
        f"cảnh báo không mang bằng chứng probe: {r.warnings}")


def test_mat_auth_that_thi_van_skip_chu_khong_dispatch_bua():
    """Nới cho auth_unverified KHÔNG được nới luôn cho trạng thái authoritative."""
    goi = []

    def detector(spec):
        from lib.states import VendorProbe
        return VendorProbe(name="agy", path="/fake/agy", authed=False, quota_capped=False,
                           error="not logged in")

    def runner(cmd, **kw):
        goi.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "OK", "stderr": ""})()

    r = run_vendor("agy", "xin chào", runner=runner, detector=detector)
    assert r.status == "skipped" and not goi


# ---------- 4. thông điệp phải kèm thời gian probe + mã thoát ----------

def test_thong_diep_timeout_kem_thoi_gian_va_noi_ro_khong_co_ma_thoat():
    def runner(cmd, **kw):
        if cmd[-1] == "models":
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        return _ok("v1.0")

    p = detect(_spec(auth_check_authoritative=False, auth_check_timeout=30),
               which=lambda _: "/fake/giavendor", runner=runner)
    assert p.authed is None
    loi = p.error or ""
    assert "timeout" in loi, f"không nói là timeout: {loi!r}"
    assert "30s" in loi, f"thiếu ngưỡng timeout để đọc là hiểu ngay: {loi!r}"
    assert "mã thoát" in loi, f"phải nói rõ timeout KHÔNG có mã thoát: {loi!r}"


def test_thong_diep_skip_mang_theo_bang_chung_probe():
    def detector(spec):
        from lib.states import VendorProbe
        return VendorProbe(name="agy", path="/fake/agy", authed=False, quota_capped=False,
                           error="auth_probe_timeout — timeout sau 61.2s (exit …)")

    r = run_vendor("agy", "xin chào", runner=lambda *a, **k: None, detector=detector)
    assert "61.2s" in r.summary, (
        f"nhãn trần không đủ để cãi lại, phải kèm bằng chứng: {r.summary!r}")


def test_timeout_cua_version_cmd_khong_bi_gan_nham_cho_probe_auth():
    """Thông điệp nói SAI CHỖ là đúng họ lỗi BUG-13 — đừng tái phạm."""
    def runner(cmd, **kw):
        if cmd[-1] == "--version":
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        return _ok()

    p = detect(_spec(auth_check_authoritative=False),
               which=lambda _: "/fake/giavendor", runner=runner)
    assert "ngưỡng" not in (p.error or ""), (
        f"timeout của --version bị dán nhãn probe auth: {p.error!r}")
