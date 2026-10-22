"""BUG-4: doctor phải đọc log evidence để biết vendor ĐANG bị quota_capped.

Trước đây doctor chỉ đo "binary có chạy --version được không" → vendor hết quota
vẫn hiện `ready` xanh, dispatch chết ngay. Module này tách phần suy luận quota
thành hàm THUẦN (nhận `records`, `now`, không đụng đồng hồ/file thật) để test được.

Quy tắc cốt lõi:
- Bản ghi mới thắng bản ghi cũ. Với mỗi vendor, tín hiệu MỚI NHẤT trong
  {quota_capped, ok} quyết định trạng thái.
- quota_capped chỉ có hiệu lực trong một cửa sổ thời gian (cap có RESET) —
  bản ghi cũ quá hạn không được đóng băng vendor.
- status=ok xuất hiện SAU quota_capped nghĩa là cap đã hết → không báo capped.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

# Cap có RESET: bản ghi quota_capped quá hạn này không được đóng băng vendor mãi mãi.
QUOTA_CAP_WINDOW = timedelta(hours=5)

# MỘT cửa sổ cho mọi vendor là SAI — ba kiểu quota khác hẳn nhau (Codex review 20/08):
#   • codex  : hẹn mốc tuyệt đối ("try again at Aug 20th 10:58") — thường trong ngày.
#   • gemini : quota theo NGÀY, reset nửa đêm giờ Thái Bình Dương → 5h là quá ngắn,
#              vendor vẫn đang cạn mà bảng đã xanh trở lại.
#   • grok / openrouter : 402 "balance exhausted" — HẾT TIỀN, KHÔNG tự reset.
#              Chỉ nạp thêm mới hết; để nó tự xanh sau vài giờ là báo sai chiều nguy hiểm.
#   • opencode / hermes : OpenCode Go quota chung (5h / weekly / monthly) — KHÔNG tự xanh
#              sau default 5h nếu chưa tới reset_at xác minh hoặc full-window snapshot healthy.
# `None` = không tự hết hạn; chỉ một bản ghi status=ok mới xoá được cap.
QUOTA_CAP_WINDOW_BY_VENDOR: dict[str, timedelta | None] = {
    "codex": timedelta(hours=5),
    "claude": timedelta(hours=5),
    "gemini": timedelta(hours=24),
    "agy": timedelta(hours=24),
    "dsh": None,        # trả theo lượt — hết tiền thì không tự đầy lại
    "grok": None,       # 402 balance exhausted
    "openrouter": None,
    "opencode": None,   # Go cap không tự xanh sau default 5h
    "hermes": None,     # Go cap không tự xanh sau default 5h
}


def is_go_vendor(vendor: str) -> bool:
    """Kiểm tra vendor có thuộc nhóm Go adapter (quota_group 'opencode-go') hay không."""
    if not isinstance(vendor, str):
        return False
    v = vendor.strip().lower()
    if v in ("opencode", "hermes", "opencode-go"):
        return True
    try:
        from lib.vendor_config import vendor_quota_group
        return vendor_quota_group(v) == "opencode-go"
    except Exception:
        return False


def is_free_record(record: dict) -> bool:
    """Kiểm tra bản ghi có phải lượt gọi model free hay không."""
    if not isinstance(record, dict):
        return False
    if record.get("is_free") is True:
        return True
    m = record.get("model") or ""
    if isinstance(m, str):
        m_clean = m.strip().lower()
        if m_clean.endswith("-free") or ":free" in m_clean or m_clean == "free":
            return True
        try:
            from lib.model_policy import is_free_model
            if is_free_model(m_clean):
                return True
        except Exception:
            pass
    return False


def is_full_window_snapshot_healthy(record: dict) -> bool:
    """Kiểm tra bản ghi có phải bằng chứng snapshot lành mạnh toàn bộ 3 cửa sổ hay không."""
    if not isinstance(record, dict):
        return False
    if (
        record.get("full_window_healthy") is True
        or record.get("snapshot_healthy") is True
        or record.get("windows_healthy") is True
    ):
        return True
    windows = record.get("windows")
    if isinstance(windows, (dict, list)):
        try:
            from lib.quota import evaluate_quota_windows
            eval_res = evaluate_quota_windows(windows)
            return eval_res.get("status") == "ok"
        except Exception:
            pass
    return False


def window_for(vendor: str, default: timedelta | None = QUOTA_CAP_WINDOW):
    """Cửa sổ hiệu lực của một bản ghi quota_capped, theo KIỂU quota của vendor."""
    if vendor in QUOTA_CAP_WINDOW_BY_VENDOR:
        return QUOTA_CAP_WINDOW_BY_VENDOR[vendor]
    if is_go_vendor(vendor):
        return None
    return default


def parse_ts(value) -> datetime | None:
    """ISO ts → datetime aware (UTC). Hỏng/thiếu/không parse được → None (bỏ qua, không nổ)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_quota_capped_record(record) -> bool:
    """Bản ghi evidence báo hết quota: reason='quota_capped' (dispatch ghi cùng
    status='skipped') hoặc status='quota_capped' (lane khác ghi thẳng status)."""
    if not isinstance(record, dict):
        return False
    return record.get("reason") == "quota_capped" or record.get("status") == "quota_capped"


def is_ok_record(record) -> bool:
    """Bản ghi chứng minh vendor gọi ĐƯỢC → bằng chứng cap đã hết."""
    if not isinstance(record, dict):
        return False
    return record.get("status") == "ok"


def quota_capped_since(
    records: list[dict],
    now: str,
    window: timedelta | None = QUOTA_CAP_WINDOW,
) -> dict[str, str]:
    """Hàm THUẦN: {vendor → ts căn cứ} cho các vendor ĐANG bị quota_capped.

    Không đọc datetime.now(), không đọc file — chỉ từ `records` + `now`.

    Luật:
      1. Bỏ qua bản ghi ts hỏng/thiếu/không parse được (không nổ).
      2. Tín hiệu mới nhất thắng: với mỗi vendor, xét bản ghi mới nhất trong
         {quota_capped, ok}. ok đứng sau quota_capped → cap đã hết.
      3. quota_capped chỉ tính khi nằm trong cửa sổ của CHÍNH vendor đó
         (xem QUOTA_CAP_WINDOW_BY_VENDOR) và không ở tương lai. Vendor có cửa sổ
         `None` (hết tiền, không tự reset) thì cap giữ mãi tới khi có bản ghi ok.
      4. OpenCode Go (quota_group 'opencode-go' dùng chung opencode & hermes):
         - Bất kỳ harness nào capped đều chặn cả nhóm (cả opencode & hermes).
         - Go cap evidence không tự xanh sau default 5h (window=None).
         - Thành công của free model hoặc khác model KHÔNG xoá paid cap.
         - Giữ cap tới reset_at xác minh hoặc explicit full-window snapshot healthy,
           không infer từ ok đơn lẻ và không coi harness đổi là reset.
    """
    now_dt = parse_ts(now)
    if now_dt is None:
        # Không biết "bây giờ" → không thể tính cửa sổ → an toàn: không kết luận capped.
        return {}

    latest_legacy: dict[str, tuple[datetime, bool, str]] = {}  # vendor -> (ts, is_cap, ts_iso)
    go_records: list[tuple[datetime, dict]] = []

    for record in records:
        if not isinstance(record, dict):
            continue
        vendor = record.get("vendor")
        if not isinstance(vendor, str):
            continue
        ts_dt = parse_ts(record.get("ts"))
        if ts_dt is None:
            continue  # ts hỏng → bỏ qua bản ghi này.

        if is_go_vendor(vendor):
            go_records.append((ts_dt, record))
        else:
            if is_ok_record(record):
                is_cap = False
            elif is_quota_capped_record(record):
                is_cap = True
            else:
                continue  # bản ghi không liên quan quota/ok → bỏ qua.
            cur = latest_legacy.get(vendor)
            if cur is None or ts_dt > cur[0]:
                latest_legacy[vendor] = (ts_dt, is_cap, str(record.get("ts")))

    result: dict[str, str] = {}

    # 1. Vendor legacy theo quy tắc cửa sổ từng vendor
    for vendor, (ts_dt, is_cap, ts_iso) in latest_legacy.items():
        if not is_cap:
            continue
        tuoi = now_dt - ts_dt
        if tuoi < timedelta(0):
            continue  # bản ghi ở tương lai → đồng hồ lệch, không kết luận.
        w = window_for(vendor, window)
        if w is None or tuoi <= w:
            result[vendor] = ts_iso

    # 2. Xử lý nhóm OpenCode Go (quota_group 'opencode-go' dùng chung opencode & hermes)
    if go_records:
        go_records.sort(key=lambda x: x[0])
        go_capped = False
        go_cap_dt: datetime | None = None
        go_cap_iso: str | None = None
        go_reset_at: str | None = None
        go_cap_model: str | None = None

        for t_dt, record in go_records:
            if is_quota_capped_record(record):
                go_capped = True
                go_cap_dt = t_dt
                go_cap_iso = str(record.get("ts"))
                go_reset_at = record.get("reset_at")
                go_cap_model = record.get("model")
            elif is_ok_record(record):
                if not go_capped:
                    continue
                # Thành công free model không xoá paid monthly cap
                if is_free_record(record):
                    continue
                # Thành công khác model không xoá paid monthly cap
                rec_model = record.get("model")
                if go_cap_model and rec_model and rec_model != go_cap_model:
                    continue
                # Giữ cap tới reset_at xác minh hoặc explicit full-window snapshot healthy,
                # không infer từ ok đơn lẻ và không coi harness đổi là reset.
                if is_full_window_snapshot_healthy(record):
                    go_capped = False
                    go_cap_dt = None
                    go_cap_iso = None
                    go_reset_at = None
                    go_cap_model = None

        if go_capped and go_cap_dt is not None:
            tuoi = now_dt - go_cap_dt
            if tuoi >= timedelta(0):
                cap_expired = False
                if go_reset_at:
                    r_dt = parse_ts(go_reset_at)
                    if r_dt is not None and now_dt >= r_dt:
                        cap_expired = True

                if not cap_expired:
                    # Cả hai harness opencode và hermes đều bị chặn ("bất kỳ capped chặn group")
                    result["opencode"] = go_cap_iso
                    result["hermes"] = go_cap_iso

    return result
