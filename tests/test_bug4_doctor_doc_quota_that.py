"""BUG-4: doctor phải đọc log evidence để phát hiện vendor ĐANG bị quota_capped.

Trước đây doctor chỉ đo "binary chạy --version được không" → vendor vừa trả
429/"usage limit" vẫn hiện `ready` xanh, người đọc tin nhầm. Các test ở đây khóa
hàm thuần `quota_capped_since(records, now)` và bước annotate/render, không đụng
đồng hồ hệ thống hay file thật."""
import pytest
from datetime import datetime, timedelta, timezone

from lib.states import VendorProbe, VendorState
from lib.state_store import build_state
from lib.doctor_quota import quota_capped_since, QUOTA_CAP_WINDOW
from doctor import annotate_quota_capped, render_table

NOW = "2026-08-19T12:00:00+00:00"


def _rec(vendor, status, ts, reason=None):
    return {"ts": ts, "vendor": vendor, "status": status, "reason": reason}


def _cap(vendor, ts):
    # dispatch ghi status="skipped" + reason="quota_capped" khi hết quota.
    return _rec(vendor, "skipped", ts, reason="quota_capped")


def _ready_state(name="codex", path="/usr/bin/codex"):
    return build_state([VendorProbe(name, path, True, False, "1.0")], NOW)


# --- 1. capped trong cửa sổ → phát hiện, kèm mốc thời gian làm căn cứ ----------

def test_capped_trong_cua_so_duoc_phat_hien():
    cap_ts = "2026-08-19T08:00:00+00:00"  # 4 giờ trước NOW → trong cửa sổ 5h
    records = [_cap("codex", cap_ts)]
    assert quota_capped_since(records, NOW) == {"codex": cap_ts}


def test_bang_doctor_in_moc_thoi_gian_khi_capped():
    cap_ts = "2026-08-19T08:00:00+00:00"
    state = _ready_state()
    annotate_quota_capped(state, [_cap("codex", cap_ts)], NOW)
    table = render_table(state)

    assert state["vendors"]["codex"]["state"] == "quota_capped"
    # Người đọc phải thấy TẠI SAO nói capped: mốc thời gian của bản ghi căn cứ.
    assert cap_ts in table
    assert "Hết quota" in table


# --- 2. capped nhưng đã quá cửa sổ → cap đã reset, không đóng băng vendor ------

def test_capped_qua_cua_so_khong_con_bi_bao():
    old_ts = "2026-08-19T06:00:00+00:00"  # 6 giờ trước NOW → ngoài cửa sổ 5h
    assert quota_capped_since([_cap("codex", old_ts)], NOW) == {}


def test_capped_qua_cua_so_van_ready_trong_bang():
    state = _ready_state()
    annotate_quota_capped(state, [_cap("codex", "2026-08-19T06:00:00+00:00")], NOW)
    assert state["vendors"]["codex"]["state"] == "ready"


# --- 3. capped rồi ok SAU đó → bản ghi mới (ok) thắng → không báo capped -------

def test_capped_roi_ok_sau_do_thi_ok_thang():
    records = [
        _cap("codex", "2026-08-19T08:00:00+00:00"),
        _rec("codex", "ok", "2026-08-19T09:00:00+00:00"),
    ]
    assert quota_capped_since(records, NOW) == {}


def test_ok_cu_hon_cap_thi_cap_moi_van_thang():
    # ok ĐỨNG TRƯỚC cap: cap mới hơn → vẫn báo capped.
    records = [
        _rec("codex", "ok", "2026-08-19T07:00:00+00:00"),
        _cap("codex", "2026-08-19T08:00:00+00:00"),
    ]
    assert quota_capped_since(records, NOW) == {"codex": "2026-08-19T08:00:00+00:00"}


# --- 4. ts hỏng/thiếu/không parse được → bỏ qua bản ghi, KHÔNG nổ -------------

def test_ts_hong_bi_bo_qua_khong_no():
    records = [
        _cap("codex", "khong-phai-ts"),       # parse hỏng
        _cap("codex", None),                  # thiếu ts
        {"vendor": "codex"},                  # không có key ts
        _cap("codex", "2026-08-19T08:00:00+00:00"),  # hợp lệ nhưng sau đó... 
    ]
    # ...vẫn là tín hiệu capped duy nhất hợp lệ → được phát hiện, không crash.
    assert quota_capped_since(records, NOW) == {"codex": "2026-08-19T08:00:00+00:00"}


def test_ts_hong_duy_nhat_khong_tao_ra_cap():
    records = [_cap("codex", "khong-phai-ts"), _cap("codex", None)]
    assert quota_capped_since(records, NOW) == {}


def test_cap_ghi_thang_status_quota_capped_cung_duoc_nhan():
    # Lane khác có thể ghi status="quota_capped" thay vì reason="quota_capped".
    records = [{"ts": "2026-08-19T08:00:00+00:00", "vendor": "codex",
                "status": "quota_capped", "reason": None}]
    assert quota_capped_since(records, NOW) == {"codex": "2026-08-19T08:00:00+00:00"}


# --- 5. vendor chưa cài / chưa auth KHÔNG bị hạ cấp thành capped --------------

def test_vendor_chua_cai_khong_bi_ha_cap_thanh_capped():
    state = build_state([VendorProbe("codex", None, False, False, None)], NOW)
    annotate_quota_capped(state, [_cap("codex", "2026-08-19T08:00:00+00:00")], NOW)
    assert state["vendors"]["codex"]["state"] == "not_installed"


def test_vendor_chua_auth_khong_bi_ha_cap_thanh_capped():
    state = build_state(
        [VendorProbe("codex", "/usr/bin/codex", False, False, "1.0")], NOW)
    annotate_quota_capped(state, [_cap("codex", "2026-08-19T08:00:00+00:00")], NOW)
    assert state["vendors"]["codex"]["state"] == "installed_not_authed"


# --- 6. log rỗng → không capped ------------------------------------------------

def test_log_rong_khong_cap_vendor_nao():
    state = _ready_state()
    annotate_quota_capped(state, [], NOW)
    assert state["vendors"]["codex"]["state"] == "ready"


def test_hang_so_cua_so_mac_dinh_la_5_gio():
    assert QUOTA_CAP_WINDOW.total_seconds() == 5 * 3600


# ── lỗ do review chỉ ra: cửa sổ đọc log quá hẹp ─────────────────────────────

def test_doc_du_rong_de_ban_ghi_cap_khong_bi_troi_ra_ngoai():
    """limit mặc định 20 là bẫy: vài lượt dispatch sau khi cap là bản ghi cap
    trôi khỏi cửa sổ đọc, doctor lại báo ready như trước khi vá."""
    import doctor
    assert doctor.EVIDENCE_LOOKBACK >= 200


# ── ba kiểu quota khác nhau (Codex review 20/08) ────────────────────────────

from lib.doctor_quota import quota_capped_since as _qcs, window_for


def _rec_gio(vendor, status, reason, gio_truoc):
    ts = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc) - timedelta(hours=gio_truoc)
    return {"ts": ts.isoformat(), "vendor": vendor, "status": status, "reason": reason}


NOW_KIEU = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc).isoformat()


def test_grok_402_het_tien_thi_KHONG_tu_xanh_lai_sau_vai_gio():
    """402 = hết số dư, không tự nạp lại. Để nó tự xanh là báo sai CHIỀU NGUY HIỂM."""
    out = _qcs([_rec_gio("grok", "skipped", "quota_capped", 30)], NOW_KIEU)
    assert "grok" in out


def test_gemini_quota_theo_ngay_nen_5h_la_qua_ngan():
    out = _qcs([_rec_gio("gemini", "skipped", "quota_capped", 8)], NOW_KIEU)
    assert "gemini" in out, "8 giờ trước vẫn trong ngày, chưa reset"


def test_codex_qua_cua_so_5h_thi_thoi_bao_capped():
    out = _qcs([_rec_gio("codex", "skipped", "quota_capped", 6)], NOW_KIEU)
    assert "codex" not in out


def test_ban_ghi_ok_xoa_cap_ke_ca_vendor_khong_tu_reset():
    out = _qcs([_rec_gio("grok", "skipped", "quota_capped", 30),
                _rec_gio("grok", "ok", None, 2)], NOW_KIEU)
    assert "grok" not in out


def test_vendor_la_dung_cua_so_mac_dinh():
    assert window_for("vendor_khong_biet") == timedelta(hours=5)
