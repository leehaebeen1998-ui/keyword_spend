"""
Reads and writes config.json.
Deep-merges with DEFAULT_CONFIG so keys added in future versions
always exist even on older config files.
"""
from __future__ import annotations
import copy
import json
import logging
from pathlib import Path

from config_schema import DEFAULT_CONFIG, LEGACY_MEDIA_ALIASES

CONFIG_PATH = Path(__file__).parent.parent / "config.json"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (in-place). Returns base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _migrate_to_brands(saved: dict) -> None:
    """기존 flat config -> brands 배열 구조로 마이그레이션."""
    if saved.get("brands"):
        return
    brand_name = (saved.get("brand_name") or "기본").strip() or "기본"
    media = saved.get("media", {})
    saved["brands"] = [{"name": brand_name, "media": copy.deepcopy(media)}]
    saved["active_brand"] = brand_name


def _migrate_legacy_media(saved: dict) -> None:
    """Move old media keys to the current split media keys."""
    media = saved.get("media")
    if not isinstance(media, dict):
        return

    for old_key, new_key in LEGACY_MEDIA_ALIASES.items():
        old_cfg = media.get(old_key)
        if not isinstance(old_cfg, dict):
            continue

        new_cfg = media.get(new_key)
        new_has_accounts = bool(isinstance(new_cfg, dict) and new_cfg.get("accounts"))
        if not new_has_accounts:
            copied = dict(old_cfg)
            copied["enabled"] = False
            media[new_key] = copied


def load() -> dict:
    """Load config from disk, merged with defaults."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            raw = CONFIG_PATH.read_bytes().rstrip(b"\x00").decode("utf-8")
            saved = json.loads(raw)
            _migrate_legacy_media(saved)
            _migrate_to_brands(saved)
            _deep_merge(cfg, saved)
        except Exception as e:
            logging.warning("config.json 읽기 실패, 기본값 사용: %s", e)
    cfg["overwrite_existing_file"] = False
    return cfg


def save(cfg: dict) -> None:
    """Write config to disk (only on explicit user action).
    _ 로 시작하는 키(런타임 전용 비밀 등)는 저장에서 제외한다."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    safe = {k: v for k, v in cfg.items() if not k.startswith("_")}
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(safe, f, ensure_ascii=False, indent=2)
