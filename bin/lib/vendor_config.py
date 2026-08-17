"""Load vendor registry from config/vendors.json (v2 schema).

Cung cấp:
- load_vendor_config(): đọc + cache file JSON, trả dict đầy đủ.
- vendor_names():       danh sách tên vendor (dùng cho argparse choices).
- default_model(name):  default_model của vendor, None nếu không có.
- vendor_traps(name):   list[str] traps, [] nếu không có.
- vendor_verify_cmd(name): verify_cmd string, None nếu không có.
- vendor_zero_quota_cmds(name): list[str] zero_quota_cmds.

KHÔNG import module nào ngoài stdlib.
"""
from __future__ import annotations
import json
from pathlib import Path
from functools import lru_cache

# config/ nằm cùng cấp bin/ trong repo
_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
_VENDORS_JSON = _CONFIG_DIR / "vendors.json"


@lru_cache(maxsize=1)
def load_vendor_config(path: Path | None = None) -> dict:
    """Đọc vendors.json, trả về dict gốc. Cache sau lần đầu."""
    p = path or _VENDORS_JSON
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("schema_version") != 3:
        raise ValueError(f"vendors.json schema_version != 3 (got {data.get('schema_version')})")
    return data


def vendor_names(cfg: dict | None = None) -> list[str]:
    """Danh sách tên vendor, giữ nguyên thứ tự trong JSON."""
    if cfg is None:
        cfg = load_vendor_config()
    return list(cfg.get("vendors", {}).keys())


def default_model(name: str, cfg: dict | None = None) -> str | None:
    """default_model của vendor. None nếu vendor không có trường này."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    dm = vendor.get("default_model")
    # Không trả CHUA_KIEM — coi như None
    if dm and dm != "CHUA_KIEM":
        return dm
    return None


def vendor_traps(name: str, cfg: dict | None = None) -> list[str]:
    """Danh sách traps của vendor. [] nếu không có."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("traps", [])


def vendor_verify_cmd(name: str, cfg: dict | None = None) -> str | None:
    """verify_cmd string của vendor."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("verify_cmd")


def vendor_zero_quota_cmds(name: str, cfg: dict | None = None) -> list[str]:
    """zero_quota_cmds list."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("zero_quota_cmds", [])


def vendor_headless(name: str, cfg: dict | None = None) -> str | None:
    """headless command template."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("headless")


def vendor_model_flag(name: str, cfg: dict | None = None) -> str | None:
    """model_flag — None nếu vendor không có cờ --model."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("model_flag")


def vendor_auth_hint(name: str, cfg: dict | None = None) -> str | None:
    """auth_hint string."""
    if cfg is None:
        cfg = load_vendor_config()
    vendor = cfg.get("vendors", {}).get(name, {})
    return vendor.get("auth_hint")
