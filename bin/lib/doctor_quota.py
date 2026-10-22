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

Chính sách bằng chứng auth (BUG-14) — hai quyết định phải giữ nguyên, không nới:

1. Mốc thời gian TƯƠNG LAI (`evaluate_auth_evidence`):
   - Cửa sổ lệch đồng hồ cho phép: AUTH_FUTURE_SKEW = 5s. Quá ±skew → BỎ bản ghi.
     Bỏ (không kết luận) là cố ý: một ts rác ở tương lai xa sẽ "thắng" mọi bằng chứng
     thật mãi mãi và ghim vendor vào not_authed vĩnh viễn — poison không tự hết.
   - Trong skew: thành công ở tương lai KHÔNG BAO GIỜ promote (không có bằng chứng
     tương lai nào đáng nâng trạng thái); lỗi auth tường minh trong skew thì TÍNH và
     fail-closed (thắng ok hợp lệ cũ) — thà báo not_authed còn hơn báo ready rồi chết.
   - Không có "future hơi hơi thì ok": chỉ đúng một ngưỡng 5s, không nới rộng.

2. Bản ghi legacy KHÔNG có metadata provider/quota_group (đúng shape
   `lib.evidence.make_record` hiện tại: ts/vendor/model/served_model/status/reason/
   latency_ms): bằng chứng THÀNH CÔNG chỉ được tính khi `model` thuộc catalog Go đang
   cấu hình (GO_APPROVED_PROFILES + config/vendors.json). Model lạ/thiếu model →
   không promote. Có metadata thì metadata phải là chuỗi khác rỗng, đúng giá trị;
   metadata sai kiểu là bản ghi hỏng → từ chối, không crash.
"""
from __future__ import annotations
from functools import lru_cache
import re
from typing import Any
from datetime import datetime, timedelta, timezone

# Cap có RESET: bản ghi quota_capped quá hạn này không được đóng băng vendor mãi mãi.
QUOTA_CAP_WINDOW = timedelta(hours=5)

# TTL cho bằng chứng auth từ live dispatch thành công gần đây (BUG-14)
AUTH_PROBE_TTL: timedelta = timedelta(hours=1)

# Độ lệch đồng hồ tối đa còn tin được một bản ghi có ts ở TƯƠNG LAI (xem docstring
# module). Đây là ngưỡng DUY NHẤT — không có "future nhưng gần đúng thì ok".
AUTH_FUTURE_SKEW: timedelta = timedelta(seconds=5)

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


def normalize_now_iso(now) -> str | None:
    """Mốc `now` → ISO string UTC để so TTL evidence.

    None = chưa ai truyền mốc thời gian (dispatcher gọi detect(spec) trực tiếp) →
    lấy giờ hệ thống. Giá trị hỏng/không hiểu → None để caller BỎ QUA evidence thay
    vì đoán bừa. Tuyệt đối không gọi .isoformat() trên None: BUG-14 lô 5a nổ
    AttributeError ở đúng chỗ này và làm CLI mất cả result JSON.
    """
    if now is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(now, str):
        return now.strip() or None
    if isinstance(now, datetime):
        dt = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return None


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


# ---------------------------------------------------------------------------
# Bằng chứng auth: nhận diện lỗi auth + khớp metadata bản ghi
# ---------------------------------------------------------------------------

# Dấu hiệu lỗi auth, viết dạng CỤM TỪ. `_` và `-` được coi là dấu phân cách nên
# "login_required", "login-required", "login required" cùng khớp MỘT mẫu — đây đúng
# là lỗi Grok finding 1: bản ghi reason "login required" (có dấu cách) bị bỏ qua vì
# code cũ so sánh CHUỖI BẰNG NHAU với marker "login_required".
_AUTH_FAILURE_PHRASES: tuple[tuple[str, ...], ...] = (
    ("auth", "failure"),
    ("auth", "failed"),
    ("authentication", "failure"),
    ("authentication", "failed"),
    ("authentication", "required"),
    ("auth", "required"),
    ("unauthenticated",),
    ("unauthorized",),
    ("login", "required"),
    ("not", "logged", "in"),
    ("not", "authenticated"),
)

# Từ phủ định đứng NGAY TRƯỚC một marker khẳng định ("not unauthorized",
# "no unauthorized access") → câu phủ định, không phải bằng chứng lỗi auth.
_NEGATION_BEFORE_RE = re.compile(r"(?:\bnot|\bno|\bnever|\bwithout)\s+$")

_SEPARATOR_RE = re.compile(r"[_\-]+")
_WHITESPACE_RE = re.compile(r"\s+")

# \b ở hai đầu = BIÊN TỪ, không phải substring tuỳ tiện: "preauthorized" hay
# "unauthorizedness" không khớp "unauthorized"; "not_unauthorized" khớp marker
# nhưng bị luật phủ định ở trên loại.
_AUTH_FAILURE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(r"\b" + r"\s+".join(words) + r"\b") for words in _AUTH_FAILURE_PHRASES
)

# Các trường tự do có thể chứa thông điệp lỗi auth của CLI/vendor.
_AUTH_TEXT_FIELDS = ("status", "reason", "error", "stderr", "summary")


def _normalize_auth_text(value) -> str:
    """Chuẩn hoá text để so marker: lowercase, `_`/`-` → dấu cách, gộp khoảng trắng.

    Không phải chuỗi (None, số, list, bytes…) → "" (bỏ qua, không crash).
    """
    if not isinstance(value, str):
        return ""
    s = _SEPARATOR_RE.sub(" ", value.strip().lower())
    return _WHITESPACE_RE.sub(" ", s).strip()


def _text_has_auth_failure(text: str) -> bool:
    if not text:
        return False
    for pat in _AUTH_FAILURE_PATTERNS:
        for match in pat.finditer(text):
            if _NEGATION_BEFORE_RE.search(text[:match.start()]):
                continue  # "not unauthorized" / "no unauthorized access"
            return True
    return False


def is_explicit_auth_failure_record(record: dict) -> bool:
    """Bản ghi có phải lỗi auth TƯỜNG MINH hay không.

    Quét cả 5 trường mà CLI/vendor thật sự dùng: status, reason, error, stderr,
    summary — với marker dạng cụm từ, biên từ, chấp nhận `_`/`-`/dấu cách làm dấu
    phân cách. Nhờ vậy "login required", "login_required", "unauthorized: token
    expired", "Auth error: not_logged_in" đều nhận; còn "preauthorized",
    "unauthorizedness", "not unauthorized" thì không.

    Bất kỳ trường nào khớp → coi là lỗi auth (fail-closed): thà báo not_authed còn
    hơn promote vendor lên ready bằng một bản ghi tự mâu thuẫn.
    """
    if not isinstance(record, dict):
        return False
    for field in _AUTH_TEXT_FIELDS:
        if _text_has_auth_failure(_normalize_auth_text(record.get(field))):
            return True
    return False


def _clean_meta(value) -> str | None:
    """Metadata chuỗi (vendor/provider/quota_group/model): rỗng hoặc sai kiểu → None.

    Metadata evidence là JSON máy ghi; gặp `provider: 42` hay `quota_group: []` thì
    đó là bản ghi HỎNG, phải từ chối — không được `.strip()` trên int/list (crash).
    """
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    return s or None


def _base_model_slug(value) -> str:
    """Slug model đã bỏ provider prefix, variant (`:high`) và hậu tố `-free`."""
    if not isinstance(value, str):
        return ""
    s = value.strip().lower()
    if ":" in s:
        s = s.split(":", 1)[0].strip()
    if "/" in s:
        s = s.rsplit("/", 1)[-1].strip()
    if s.endswith("-free"):
        s = s[:-5]
    return s


_GO_CATALOG_FALLBACK = frozenset({"deepseek-v4.1-flash", "glm-5.3-flash"})


@lru_cache(maxsize=1)
def _known_go_models() -> frozenset[str]:
    """Catalog Go đang cấu hình: GO_APPROVED_PROFILES + config/vendors.json.

    Dùng cho bản ghi legacy (không có provider/quota_group) — bằng chứng thành công
    chỉ có giá trị nếu model là model Go thật, không phải model lạ do router/harness
    khác ghi vào cùng file log.
    """
    slugs: set[str] = set()
    try:
        from lib.model_policy import GO_APPROVED_PROFILES

        slugs.update(_base_model_slug(k) for k in GO_APPROVED_PROFILES)
    except Exception:
        pass
    try:
        from lib.vendor_config import load_vendor_config

        vendors = (load_vendor_config() or {}).get("vendors") or {}
        for name in ("opencode", "hermes"):
            info = vendors.get(name) or {}
            slugs.add(_base_model_slug(info.get("default_model")))
            models_list = info.get("models")
            if isinstance(models_list, list):
                slugs.update(_base_model_slug(m) for m in models_list)
            profiles = info.get("profiles")
            if isinstance(profiles, dict):
                for key, val in profiles.items():
                    slugs.add(_base_model_slug(key))
                    if isinstance(val, dict):
                        slugs.add(_base_model_slug(val.get("model")))
    except Exception:
        pass
    slugs.discard("")
    return frozenset(slugs) or _GO_CATALOG_FALLBACK


def matches_vendor_criteria(
    record: dict,
    vendor: str,
    provider: str | None = None,
    quota_group: str | None = None,
    model: str | None = None,
) -> bool:
    """Bản ghi evidence có khớp đúng vendor/provider/model/quota group hay không.

    Luật (fail-closed, không nhận vơ, không crash trên metadata hỏng):
    - `vendor` phải là chuỗi khác rỗng, khớp đúng tên vendor.
    - `provider` / `quota_group`: CÓ khai thì phải là chuỗi khác rỗng và (nếu caller
      có yêu cầu) đúng giá trị. Khai sai kiểu (int/list/dict) → từ chối bản ghi.
    - `model`: có khai thì phải là chuỗi khác rỗng; sai kiểu → từ chối.
    - Bản ghi LEGACY (không khai provider lẫn quota_group — shape dispatch hiện tại)
      chỉ được tính khi `model` thuộc catalog Go đang cấu hình. Thiếu model hoặc model
      lạ → từ chối, để log của harness/router khác không promote lane Go. Ngoại lệ có
      chủ ý: bản ghi LỖI AUTH tường minh vẫn tính dù thiếu model — đó là bằng chứng
      mức credential, khác mức model, và bỏ nó đi sẽ là nới lỏng theo hướng nguy hiểm.
    """
    if not isinstance(record, dict):
        return False
    if not isinstance(vendor, str) or not vendor.strip():
        return False
    rec_vendor = _clean_meta(record.get("vendor"))
    if rec_vendor is None or rec_vendor != vendor.strip().lower():
        return False

    expect_provider = None
    if provider is not None:
        expect_provider = _clean_meta(provider)
        if expect_provider is None:
            return False  # caller yêu cầu provider nhưng truyền giá trị không hợp lệ

    rec_provider = None
    if record.get("provider") is not None:
        rec_provider = _clean_meta(record.get("provider"))
        if rec_provider is None:
            return False  # metadata sai kiểu/rỗng → bản ghi hỏng
        if expect_provider is not None and rec_provider != expect_provider:
            return False

    expect_qgroup = None
    if quota_group is not None:
        expect_qgroup = _clean_meta(quota_group)
        if expect_qgroup is None:
            return False

    rec_qgroup = None
    if record.get("quota_group") is not None:
        rec_qgroup = _clean_meta(record.get("quota_group"))
        if rec_qgroup is None:
            return False
        if expect_qgroup is not None and rec_qgroup != expect_qgroup:
            return False

    expect_model = None
    if model is not None:
        expect_model = _clean_meta(model)
        if expect_model is None:
            return False

    rec_model = None
    if record.get("model") is not None:
        rec_model = _clean_meta(record.get("model"))
        if rec_model is None:
            return False  # model sai kiểu (vd: 42) → từ chối

    if expect_model is not None:
        if rec_model is None:
            return False
        if rec_model != expect_model and _base_model_slug(rec_model) != _base_model_slug(expect_model):
            return False
        return True

    # Model khai prefix provider khác họ đã biết → không phải model của lane này.
    if rec_model is not None and rec_provider and "/" in rec_model:
        prefix = rec_model.split("/")[0]
        if prefix in ("openai", "anthropic", "google", "mistral") and prefix != rec_provider:
            return False

    # Legacy (không có provider/quota_group): phải là model Go thật.
    if rec_provider is None and rec_qgroup is None:
        # Lỗi auth tường minh là bằng chứng ở mức CREDENTIAL, dùng chung cho mọi
        # model của lane → không đòi model Go ở đây. Bỏ nó đi mới là nới lỏng theo
        # hướng nguy hiểm (vendor mất auth mà doctor vẫn để ready/auth_unverified).
        if is_explicit_auth_failure_record(record):
            return True
        if rec_model is None or _base_model_slug(rec_model) not in _known_go_models():
            return False

    return True



def evaluate_auth_evidence(
    records: list[dict],
    vendor: str,
    now: str | datetime,
    ttl: timedelta | None = AUTH_PROBE_TTL,
    provider: str | None = None,
    quota_group: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Hàm THUẦN đánh giá bằng chứng auth từ records cho một vendor tại mốc `now`.

    Quy tắc cốt lõi:
    1. Lọc các bản ghi khớp đúng vendor/provider/quota_group/model (không nhận vơ).
    2. Bỏ qua bản ghi ts hỏng/thiếu; bản ghi ở tương lai quá AUTH_FUTURE_SKEW → bỏ
       (không kết luận, tránh ghim not_authed vĩnh viễn vì ts rác).
    3. Tín hiệu mới nhất thắng giữa {ok, explicit_auth_failure}.
       - Thành công ở TƯƠNG LAI (dù trong skew) KHÔNG BAO GIỜ promote.
       - Lỗi auth tường minh trong skew vẫn tính → fail-closed, thắng ok hợp lệ cũ.
    4. Bản ghi 'ok' chỉ có hiệu lực trong cửa sổ TTL (mặc định AUTH_PROBE_TTL=1h).
       Quá hạn -> unverified (stale).
    5. Explicit auth failure mới nhất -> authed=False (không bị override bởi ok cũ).
    6. Trả về dict:
       {
           "authed": bool | None,  # True (ready), False (not authed), None (unverified)
           "evidence_ts": str | None,
           "reason": str | None,
           "record": dict | None,
       }
    """
    now_dt = parse_ts(now) if isinstance(now, str) else now
    if now_dt is None:
        return {"authed": None, "evidence_ts": None, "reason": "invalid_now", "record": None}
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    else:
        now_dt = now_dt.astimezone(timezone.utc)

    valid_events: list[tuple[datetime, int, str, dict]] = []  # (ts_dt, priority, event_type, record)

    for rec in records:
        if not matches_vendor_criteria(rec, vendor, provider=provider, quota_group=quota_group, model=model):
            continue
        ts_dt = parse_ts(rec.get("ts"))
        if ts_dt is None:
            continue
        lech = ts_dt - now_dt  # > 0: ts ở tương lai (lệch đồng hồ)
        if lech > AUTH_FUTURE_SKEW:
            # Lệch quá xa: bỏ hẳn. Giữ lại thì một ts rác tương lai sẽ luôn "mới nhất"
            # và đóng băng trạng thái → poison không tự hết. Thà không kết luận.
            continue

        if is_explicit_auth_failure_record(rec):
            # Ưu tiên auth_failure hơn ok khi cùng timestamp. Trong skew, lỗi auth
            # vẫn tính: fail-closed (not_authed) hơn là ready rồi chết lúc dispatch.
            valid_events.append((ts_dt, 1, "auth_failure", rec))
        elif is_ok_record(rec):
            if lech > timedelta(0):
                continue  # thành công ở tương lai KHÔNG BAO GIỜ promote
            valid_events.append((ts_dt, 0, "ok", rec))

    if not valid_events:
        return {"authed": None, "evidence_ts": None, "reason": "no_evidence", "record": None}

    # Sắp xếp theo thời gian tăng dần, tie-breaker priority (auth_failure=1 thắng ok=0)
    valid_events.sort(key=lambda x: (x[0], x[1]))
    latest_ts, _, latest_type, latest_rec = valid_events[-1]

    if latest_type == "auth_failure":
        return {
            "authed": False,
            "evidence_ts": latest_rec.get("ts"),
            "reason": latest_rec.get("reason") or "explicit_auth_failure",
            "record": latest_rec,
        }

    # latest_type == "ok"
    age = now_dt - latest_ts
    if ttl is not None and age > ttl:
        return {
            "authed": None,
            "evidence_ts": latest_rec.get("ts"),
            "reason": f"stale_evidence (quá TTL {ttl})",
            "record": latest_rec,
        }

    return {
        "authed": True,
        "evidence_ts": latest_rec.get("ts"),
        "reason": "recent_dispatch_success",
        "record": latest_rec,
    }
