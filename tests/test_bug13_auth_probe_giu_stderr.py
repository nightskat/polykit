"""BUG-13 (20/08/2026): probe auth hỏng vì lý do KHÔNG PHẢI auth vẫn bị dán nhãn
`auth_unverified`, và stderr thật thì bị vứt.

Nhãn đó bảo người đọc đi kiểm auth, trong khi nguyên nhân có thể là cờ sai, mạng,
hay CLI đổi cú pháp. Nhãn nói sai chỗ, mà bằng chứng để cãi lại đã bị vứt mất.
"""
from lib.vendors import detect, VendorSpec


def test_loi_khong_phai_auth_van_giu_duoc_stderr():
    spec = VendorSpec(name="giavendor", binary="giavendor",
                      auth_hint="chạy giavendor login",
                      version_cmd=["giavendor", "--version"],
                      auth_check_cmd=["giavendor", "whoami"],
                      auth_check_authoritative=False)

    def runner(cmd, **kw):
        class R:
            returncode = 2
            stdout = ""
            stderr = "error: unknown flag `whoami`\nusage: giavendor [OPTIONS]"
        return R()

    p = detect(spec, which=lambda _: "/fake/giavendor", runner=runner)
    assert p.authed is None, "vẫn là auth_unverified (chưa đủ bằng chứng để nói mất auth)"
    assert "unknown flag" in (p.error or ""), f"stderr thật bị vứt: {p.error!r}"
