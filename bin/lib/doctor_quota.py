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
# `None` = không tự hết hạn; chỉ một bản ghi status=ok mới xoá được cap.
QUOTA_CAP_WINDOW_BY_VENDOR: dict[str, timedelta | None] = {
    "codex": timedelta(hours=5),
    "claude": timedelta(hours=5),
    "gemini": timedelta(hours=24),
    "agy": timedelta(hours=24),
    "dsh": None,        # trả theo lượt — hết tiền thì không tự đầy lại
    "grok": None,       # 402 balance exhausted
    "openrouter": None,
}


def window_for(vendor: str, default: timedelta | None = QUOTA_CAP_WINDOW):
    """Cửa sổ hiệu lực của một bản ghi quota_capped, theo KIỂU quota của vendor."""
    if vendor in QUOTA_CAP_WINDOW_BY_VENDOR:
        return QUOTA_CAP_WINDOW_BY_VENDOR[vendor]
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
    """
    now_dt = parse_ts(now)
    if now_dt is None:
        # Không biết "bây giờ" → không thể tính cửa sổ → an toàn: không kết luận capped.
        return {}

    latest: dict[str, tuple[datetime, bool, str]] = {}  # vendor -> (ts, is_cap, ts_iso)
    for record in records:
        if not isinstance(record, dict):
            continue
        vendor = record.get("vendor")
        if not isinstance(vendor, str):
            continue
        if is_ok_record(record):
            is_cap = False
        elif is_quota_capped_record(record):
            is_cap = True
        else:
            continue  # bản ghi không liên quan quota/ok → bỏ qua.
        ts_dt = parse_ts(record.get("ts"))
        if ts_dt is None:
            continue  # ts hỏng → bỏ qua bản ghi này.
        cur = latest.get(vendor)
        if cur is None or ts_dt > cur[0]:
            latest[vendor] = (ts_dt, is_cap, str(record.get("ts")))

    result: dict[str, str] = {}
    for vendor, (ts_dt, is_cap, ts_iso) in latest.items():
        if not is_cap:
            continue
        tuoi = now_dt - ts_dt
        if tuoi < timedelta(0):
            continue  # bản ghi ở tương lai → đồng hồ lệch, không kết luận.
        w = window_for(vendor, window)
        if w is None or tuoi <= w:
            result[vendor] = ts_iso
    return result
