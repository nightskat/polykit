from __future__ import annotations
import json
import pytest
from pathlib import Path
from watcher import run_watch
import lib.watcher as watcher

@pytest.fixture(autouse=True)
def setup_tmp_paths(tmp_path, monkeypatch):
    base_p = tmp_path / "baseline.json"
    alert_p = tmp_path / "alert.json"
    lock_p = tmp_path / "lock.d"

    monkeypatch.setattr(watcher, "baseline_path", lambda: base_p)
    monkeypatch.setattr(watcher, "alert_state_path", lambda: alert_p)
    monkeypatch.setattr(watcher, "lock_path", lambda: lock_p)


# ==============================================================================
# 1. Snapshot catalog provenance/timestamp/stale/error additive metadata
# ==============================================================================

def test_snapshot_additive_metadata():
    state = {
        "generated_at": "2026-10-22T08:00:00Z",
        "vendors": {
            "opencode": {
                "state": "ready",
                "cli_version": "1.0.0",
                "models": ["deepseek-v4.1-flash", "glm-5.3-flash"],
                "error": None,
                "catalog_source": "cli:opencode models opencode-go",
                "catalog_timestamp": "2026-10-22T07:55:00Z",
                "stale": False,
            },
            "openrouter": {
                "state": "ready",
                "cli_version": None,
                "models": ["meta-llama/llama-3.3-70b-instruct:free"],
                "error": "rate_limit_probe",
                "source": "api",
                "probe_checked_at": "2026-10-22T07:50:00Z",
                "stale": True,
            }
        }
    }

    snap = watcher.snapshot_from_state(state)
    assert "opencode" in snap
    oc = snap["opencode"]
    assert oc["models"] == ["deepseek-v4.1-flash", "glm-5.3-flash"]
    assert oc["version"] == "1.0.0"
    assert oc["state"] == "ready"
    assert oc["error"] is None
    assert oc["catalog_source"] == "cli:opencode models opencode-go"
    assert oc["provenance"] == "cli:opencode models opencode-go"
    assert oc["catalog_timestamp"] == "2026-10-22T07:55:00Z"
    assert oc["stale"] is False

    or_snap = snap["openrouter"]
    assert or_snap["error"] == "rate_limit_probe"
    assert or_snap["catalog_source"] == "api"
    assert or_snap["provenance"] == "api"
    assert or_snap["catalog_timestamp"] == "2026-10-22T07:50:00Z"
    assert or_snap["stale"] is True


def test_render_snapshot_includes_additive_metadata_and_advisories():
    state = {
        "generated_at": "2026-10-22T10:00:00Z",
        "vendors": {
            "opencode": {
                "state": "ready",
                "cli_version": "0.1.2",
                "models": ["deepseek-v4.1-flash", "deepseek-v4.1-contributor", "glm-5.3-flash-free"],
                "error": None,
                "catalog_source": "cli",
                "catalog_timestamp": "2026-10-22T09:30:00Z",
                "stale": False,
            },
            "hermes": {
                "state": "ready",
                "cli_version": "0.4.0",
                "models": ["deepseek-v4.1-flash"],
                "error": "timeout_minor",
                "stale": True,
            }
        }
    }
    rendered = watcher.render_snapshot(state, now="2026-10-22T10:00:00Z")
    assert "# Snapshot vendor — MÁY SINH, ĐỪNG SỬA TAY" in rendered
    assert "`opencode`" in rendered
    assert "stale (last-known-good)" in rendered
    assert "banned: contributor" in rendered
    assert "advisory: free" in rendered
    assert "- `deepseek-v4.1-flash`" in rendered


# ==============================================================================
# 2. Fetch error / offline giữ last-known-good, không báo removed giả
# ==============================================================================

def test_fetch_error_preserves_last_known_good_no_false_removal():
    old_snap = {
        "opencode": {
            "models": ["deepseek-v4.1-flash", "glm-5.3-flash"],
            "version": "1.0",
            "state": "ready",
            "error": None,
            "catalog_source": "cli",
            "catalog_timestamp": "2026-10-20T10:00:00Z",
            "stale": False,
        }
    }

    # New snapshot có error (ví dụ timeout khi gọi models CLI)
    new_snap = {
        "opencode": {
            "models": [],  # Models rỗng do CLI lỗi
            "version": "1.0",
            "state": "ready",
            "error": "auth_probe_timeout — timeout sau 10s",
            "catalog_source": "cli",
            "catalog_timestamp": "2026-10-22T10:00:00Z",
            "stale": False,
        }
    }

    # Áp dụng last-known-good
    watcher.apply_last_known_good(new_snap, old_snap)

    # Models phải được phục hồi từ last-known-good
    assert new_snap["opencode"]["models"] == ["deepseek-v4.1-flash", "glm-5.3-flash"]
    # Đánh dấu stale
    assert new_snap["opencode"]["stale"] is True
    # Nguồn và ngày cũ được giữ
    assert new_snap["opencode"]["catalog_timestamp"] == "2026-10-20T10:00:00Z"
    assert new_snap["opencode"]["error"] == "auth_probe_timeout — timeout sau 10s"

    # diff_snapshots KHÔNG được báo model bị removed giả
    diff = watcher.diff_snapshots(old_snap, new_snap)
    model_diffs = [c for c in diff if c.get("type") == "models"]
    assert len(model_diffs) == 0


def test_genuine_model_removal_detected_when_no_error():
    old_snap = {
        "opencode": {
            "models": ["deepseek-v4.1-flash", "deprecated-model"],
            "version": "1.0",
            "state": "ready",
            "error": None,
        }
    }
    # CLI thành công không có error, model deprecated-model bị gỡ thật
    new_snap = {
        "opencode": {
            "models": ["deepseek-v4.1-flash"],
            "version": "1.0",
            "state": "ready",
            "error": None,
        }
    }
    watcher.apply_last_known_good(new_snap, old_snap)
    diff = watcher.diff_snapshots(old_snap, new_snap)
    assert len(diff) == 1
    assert diff[0]["type"] == "models"
    assert diff[0]["removed"] == ["deprecated-model"]


# ==============================================================================
# 3. Không watcher tự đổi defaults / effort / config
# ==============================================================================

def test_watcher_does_not_modify_vendor_config():
    config_path = Path(__file__).resolve().parents[1] / "config" / "vendors.json"
    if config_path.exists():
        original_content = config_path.read_text(encoding="utf-8")

        # Chạy watcher với dry-run
        state = {
            "vendors": {
                "opencode": {
                    "state": "ready",
                    "cli_version": "1.0",
                    "models": ["deepseek-v4.1-flash"],
                    "error": None,
                }
            }
        }
        run_watch(state=state, notifier=lambda m: False)

        # Đảm bảo file config không hề bị chạm tới
        after_content = config_path.read_text(encoding="utf-8")
        assert original_content == after_content


# ==============================================================================
# 4. Lọc contributor/free khỏi ROUTE recommendations & Catalog advisory
# ==============================================================================

def test_filter_route_recommendations():
    raw_models = [
        "deepseek-v4.1-flash",
        "deepseek-v4.1-contributor",
        "glm-5.3-flash",
        "glm-5.3-flash-free",
        "openrouter/auto:free",
        "mimo-v2.6-flash",
    ]

    filtered = watcher.filter_route_recommendations(raw_models)
    assert "deepseek-v4.1-flash" in filtered
    assert "glm-5.3-flash" in filtered
    assert "mimo-v2.6-flash" in filtered
    # Contributor bị loại
    assert "deepseek-v4.1-contributor" not in filtered
    # Free bị loại
    assert "glm-5.3-flash-free" not in filtered
    assert "openrouter/auto:free" not in filtered


def test_get_route_recommendations_snapshot():
    snap = {
        "opencode": {
            "models": ["deepseek-v4.1-flash", "deepseek-v4.1-contributor", "glm-5.3-flash-free"]
        },
        "hermes": {
            "models": ["glm-5.3-flash", "test-contributor-model"]
        }
    }
    routes = watcher.get_route_recommendations(snap)
    assert routes["opencode"] == ["deepseek-v4.1-flash"]
    assert routes["hermes"] == ["glm-5.3-flash"]

    single_route = watcher.get_route_recommendations(snap, vendor="opencode")
    assert single_route == ["deepseek-v4.1-flash"]


def test_catalog_preserves_banned_with_advisory():
    models = ["deepseek-v4.1-flash", "deepseek-v4.1-contributor", "glm-5.3-flash-free"]
    advisories = watcher.get_catalog_with_advisories(models)

    assert len(advisories) == 3

    contrib_adv = next(a for a in advisories if a["model"] == "deepseek-v4.1-contributor")
    assert contrib_adv["banned"] is True
    assert "banned: contributor" in contrib_adv["advisory"]
    assert contrib_adv["allowed_for_routing"] is False

    free_adv = next(a for a in advisories if a["model"] == "glm-5.3-flash-free")
    assert free_adv["banned"] is False
    assert "advisory: free" in free_adv["advisory"]
    assert free_adv["allowed_for_routing"] is False

    valid_adv = next(a for a in advisories if a["model"] == "deepseek-v4.1-flash")
    assert valid_adv["banned"] is False
    assert valid_adv["advisory"] is None
    assert valid_adv["allowed_for_routing"] is True


# ==============================================================================
# 5. Parse Codex JSON qua vendors.parse_codex_models nếu có, không import hard fail
# ==============================================================================

def test_parse_codex_models_with_vendors_function(monkeypatch):
    import lib.vendors as vendors
    # Giả lập doctor maker đã thêm vendors.parse_codex_models
    monkeypatch.setattr(vendors, "parse_codex_models", lambda raw: ["codex-parsed-1", "codex-parsed-2"], raising=False)

    res = watcher.parse_codex_models('{"dummy": "json"}')
    assert res == ["codex-parsed-1", "codex-parsed-2"]


def test_parse_codex_models_fallback_without_vendors_function(monkeypatch):
    import lib.vendors as vendors
    # Đảm bảo vendors KHÔNG có parse_codex_models
    if hasattr(vendors, "parse_codex_models"):
        monkeypatch.delattr(vendors, "parse_codex_models")

    # JSON dạng dict với models list
    raw_dict = json.dumps({
        "models": [
            {"id": "gpt-5-preview", "name": "GPT-5 Preview"},
            {"id": "codex-mini", "name": "Codex Mini"}
        ]
    })
    res = watcher.parse_codex_models(raw_dict)
    assert res == ["gpt-5-preview", "codex-mini"]

    # JSON dạng list of dicts
    raw_list = json.dumps([
        {"id": "model-a"},
        {"slug": "model-b"}
    ])
    res2 = watcher.parse_codex_models(raw_list)
    assert res2 == ["model-a", "model-b"]

    # JSONL
    raw_jsonl = '{"id": "jsonl-1"}\n{"id": "jsonl-2"}'
    res3 = watcher.parse_codex_models(raw_jsonl)
    assert res3 == ["jsonl-1", "jsonl-2"]

    # Rác hoặc rỗng không crash
    assert watcher.parse_codex_models("") == []
    assert watcher.parse_codex_models("not a json at all") == []


# ==============================================================================
# 6. DeepSeek ZDR expiry2026-10-31 soon/on/expired và renewal unverified
# ==============================================================================

def test_check_deepseek_zdr_soon():
    # 6 ngày trước hạn (<= 7 ngày)
    res = watcher.check_deepseek_zdr(now="2026-10-25", renewal_verified=False)
    assert res["state"] == "soon"
    assert res["days_left"] == 6
    assert res["should_alert"] is True
    assert "sắp hết hạn" in res["message"]
    assert "chưa được xác minh" in res["message"]


def test_check_deepseek_zdr_on():
    # Đúng ngày 2026-10-31
    res = watcher.check_deepseek_zdr(now="2026-10-31", renewal_verified=False)
    assert res["state"] == "on"
    assert res["days_left"] == 0
    assert res["should_alert"] is True
    assert "hết hạn HÔM NAY" in res["message"]


def test_check_deepseek_zdr_expired():
    # Sau ngày 2026-10-31
    res = watcher.check_deepseek_zdr(now="2026-11-01", renewal_verified=False)
    assert res["state"] == "expired"
    assert res["days_left"] < 0
    assert res["should_alert"] is True
    assert "ĐÃ HẾT HẠN" in res["message"]


def test_check_deepseek_zdr_renewal_unverified():
    # Còn xa hạn (ví dụ 2026-10-15, còn 16 ngày) nhưng renewal chưa xác minh
    res = watcher.check_deepseek_zdr(now="2026-10-15", renewal_verified=False)
    assert res["state"] == "renewal_unverified"
    assert res["days_left"] == 16
    assert res["should_alert"] is True
    assert "chưa được xác minh" in res["message"]


def test_check_deepseek_zdr_ok_when_renewal_verified():
    # Còn xa hạn và đã xác minh gia hạn
    res = watcher.check_deepseek_zdr(now="2026-10-15", renewal_verified=True)
    assert res["state"] == "ok"
    assert res["should_alert"] is False


# ==============================================================================
# 7. Dedupe alert theo state & Notify failure retry & Lock
# ==============================================================================

def test_zdr_dedupe_alert_by_state():
    state_go = {
        "vendors": {
            "opencode": {
                "state": "ready",
                "cli_version": "1.0",
                "models": ["deepseek-v4.1-flash"],
                "error": None,
            }
        }
    }

    calls = []
    def mock_notifier(msg):
        calls.append(msg)
        return True

    # 1. Chạy ngày 2026-10-25 (soon) -> gửi alert lần 1
    res1 = run_watch(state=state_go, now="2026-10-25", notifier=mock_notifier, check_zdr=True)
    assert res1["action"] == "alert"
    assert len(calls) == 1
    assert "sắp hết hạn" in res1["message"]

    # 2. Chạy tiếp ngày 2026-10-26 (vẫn là state soon) -> DEDUPE, 0 alert mới
    res2 = run_watch(state=state_go, now="2026-10-26", notifier=mock_notifier, check_zdr=True)
    assert res2["action"] == "noop"
    assert res2["reason"] == "already_alerted"
    assert len(calls) == 1

    # 3. Chạy đúng ngày 2026-10-31 (chuyển sang state 'on') -> State đổi nên gửi alert lần 2
    res3 = run_watch(state=state_go, now="2026-10-31", notifier=mock_notifier, check_zdr=True)
    assert res3["action"] == "alert"
    assert len(calls) == 2
    assert "hết hạn HÔM NAY" in res3["message"]

    # 4. Chạy lại ngày 2026-10-31 -> DEDUPE
    res4 = run_watch(state=state_go, now="2026-10-31", notifier=mock_notifier, check_zdr=True)
    assert res4["action"] == "noop"
    assert len(calls) == 2

    # 5. Chạy ngày 2026-11-01 (chuyển sang state 'expired') -> State đổi nên gửi alert lần 3
    res5 = run_watch(state=state_go, now="2026-11-01", notifier=mock_notifier, check_zdr=True)
    assert res5["action"] == "alert"
    assert len(calls) == 3
    assert "ĐÃ HẾT HẠN" in res5["message"]

    # 6. Chạy lại ngày 2026-11-02 (vẫn expired) -> DEDUPE
    res6 = run_watch(state=state_go, now="2026-11-02", notifier=mock_notifier, check_zdr=True)
    assert res6["action"] == "noop"
    assert len(calls) == 3


def test_notify_failure_retries():
    state_go = {
        "vendors": {
            "opencode": {
                "state": "ready",
                "cli_version": "1.0",
                "models": ["deepseek-v4.1-flash"],
                "error": None,
            }
        }
    }

    # Notifier bị lỗi mạng (raise exception)
    def failing_notifier(msg):
        raise ConnectionError("Telegram gateway timeout")

    res = run_watch(state=state_go, now="2026-10-25", notifier=failing_notifier, check_zdr=True)
    assert res["action"] == "alert"
    assert res["notified"] is False

    # Do notify fail, alert state chưa được lưu -> lần sau với notifier tốt sẽ retry thành công
    calls = []
    def good_notifier(msg):
        calls.append(msg)
        return True

    res2 = run_watch(state=state_go, now="2026-10-25", notifier=good_notifier, check_zdr=True)
    assert res2["action"] == "alert"
    assert res2["notified"] is True
    assert len(calls) == 1


def test_watch_lock_preserved_and_stale_reclaimed(tmp_path):
    lock_dir = tmp_path / "custom_lock.d"

    # 1. Chiếm lock
    lock1 = watcher.WatchLock(path=lock_dir, stale_sec=2)
    with lock1:
        # Lần 2 chiếm cùng lúc sẽ văng LockBusy
        lock2 = watcher.WatchLock(path=lock_dir, stale_sec=2)
        with pytest.raises(watcher.LockBusy):
            with lock2:
                pass

    # 2. Sau khi thoát with lock1, lock đã nhả, lock2 có thể chiếm bình thường
    with lock2:
        assert lock_dir.exists()


# ==============================================================================
# 8. Biên last-known-good: gỡ thật vẫn báo removed, catalog-auth giữ last-known-good
# ==============================================================================

def test_not_installed_reports_removal_not_masked_as_stale():
    old_snap = {
        "codex": {"models": ["model-a"], "version": "1.0", "state": "ready", "error": None},
    }
    # Gỡ vendor thật: not_installed, KHÔNG error → không phải lỗi fetch
    new_snap = watcher.snapshot_from_state({
        "vendors": {"codex": {"state": "not_installed", "cli_version": None, "models": [], "error": None}}
    })
    watcher.apply_last_known_good(new_snap, old_snap)
    assert new_snap["codex"]["models"] == []
    assert new_snap["codex"]["stale"] is False
    removed = [c for c in watcher.diff_snapshots(old_snap, new_snap) if c["type"] == "models"]
    assert removed and removed[0]["removed"] == ["model-a"]


def test_auth_unverified_keeps_last_known_good_and_old_source_date():
    old_snap = {
        "opencode": {
            "models": ["deepseek-v4.1-flash"],
            "version": "1.0",
            "state": "ready",
            "error": None,
            "catalog_source": "models_cmd",
            "catalog_timestamp": "2026-10-20T10:00:00Z",
        },
    }
    new_snap = {
        "opencode": {
            "models": [],
            "version": "1.0",
            "state": "auth_unverified",
            "error": None,
            "catalog_source": "none",
            "catalog_timestamp": "2026-10-22T10:00:00Z",
        },
    }
    watcher.apply_last_known_good(new_snap, old_snap)
    v = new_snap["opencode"]
    assert v["models"] == ["deepseek-v4.1-flash"]
    assert v["stale"] is True
    assert v["catalog_source"] == "models_cmd"
    assert v["catalog_timestamp"] == "2026-10-20T10:00:00Z"
    assert not [c for c in watcher.diff_snapshots(old_snap, new_snap) if c["type"] == "models"]


def test_error_with_partial_models_still_keeps_last_known_good():
    old_snap = {"opencode": {"models": ["a", "b"], "version": "1.0", "state": "ready", "error": None}}
    new_snap = {"opencode": {"models": ["a"], "version": "1.0", "state": "ready", "error": "models_cmd_stderr"}}
    watcher.apply_last_known_good(new_snap, old_snap)
    assert new_snap["opencode"]["models"] == ["a", "b"]
    assert new_snap["opencode"]["stale"] is True
    assert not [c for c in watcher.diff_snapshots(old_snap, new_snap) if c["type"] == "models"]


# ==============================================================================
# 9. Parse Codex: dùng parser thật của vendors, lỗi parser chuẩn không bịa slug
# ==============================================================================

def test_parse_codex_models_dung_parser_that_cua_vendors():
    raw = json.dumps({"models": [{"slug": "gpt-6.1-sol"}, {"slug": "gpt-6.1-terra"}]})
    assert watcher.parse_codex_models(raw) == ["gpt-6.1-sol", "gpt-6.1-terra"]


def test_parse_codex_models_parser_chuan_loi_tra_rong(monkeypatch):
    import lib.vendors as vendors

    def boom(raw):
        raise ValueError("codex models output is not valid JSON")

    monkeypatch.setattr(vendors, "parse_codex_models", boom, raising=False)
    # Parser chuẩn từ chối → [] chứ không lấy parser khác bịa slug
    assert watcher.parse_codex_models('{"models": [{"id": "bịa-slug"}]}') == []


# ==============================================================================
# 10. Không cảnh báo ZDR khi lane không dính DeepSeek
# ==============================================================================

def test_khong_canh_bao_zdr_khi_lane_khong_dinh_deepseek():
    state = {
        "vendors": {
            "codex": {"state": "ready", "cli_version": "1.0", "models": ["gpt-6.1-sol"], "error": None},
        }
    }
    calls = []
    res = run_watch(state=state, now="2026-10-25", notifier=lambda m: calls.append(m) or True)
    assert res["action"] == "noop"
    assert "zdr" not in res
    assert calls == []
