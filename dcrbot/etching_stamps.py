"""Shared etching-stamp definitions and unlock helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


HIGHEST_CLEAR_EXTRA_KEY = "highest_cleared_difficulty"
NEGATIVE_MODIFIER_CLEAR_PREFIX = "negative_modifier_clear_"
NUMBER_SEARCHER2_NEGATIVE_MODIFIERS = (
    "顏色通膨",
    "圖形通膨",
    "數字通膨",
    "隨機通膨",
    "通膨王朝",
    "延遲線索",
    "通訊不良",
    "古老枷鎖",
)


@dataclass(frozen=True)
class EtchingStampDefinition:
    key: str
    title: str
    requirement: str
    asset_path: Path
    portfolio_filename: str
    unlock_kind: str
    threshold: int | None = None


NUMBER_SEARCHER2_STAMPS = (
    EtchingStampDefinition(
        key="N5",
        title="N5 通關",
        requirement="完成 N5 難度獲得",
        asset_path=Path("Resources/數字搜尋者2/mathN5.png"),
        portfolio_filename="portfolio_stamp_n5.png",
        unlock_kind="highest_difficulty",
        threshold=5,
    ),
    EtchingStampDefinition(
        key="N10",
        title="N10 通關",
        requirement="完成 N10 難度獲得",
        asset_path=Path("Resources/數字搜尋者2/mathN10.png"),
        portfolio_filename="portfolio_stamp_n10.png",
        unlock_kind="highest_difficulty",
        threshold=10,
    ),
    EtchingStampDefinition(
        key="N10_ALL_DEBUFF",
        title="全負面詞條",
        requirement="每個 N10+ 負面詞條都通關一次獲得",
        asset_path=Path("Resources/數字搜尋者2/mathN10Alldebuff.png"),
        portfolio_filename="portfolio_stamp_all_debuff.png",
        unlock_kind="all_negative_modifiers",
    ),
    EtchingStampDefinition(
        key="N15",
        title="N15 通關",
        requirement="完成 N15 難度獲得",
        asset_path=Path("Resources/數字搜尋者2/mathN15.png"),
        portfolio_filename="portfolio_stamp_n15.png",
        unlock_kind="highest_difficulty",
        threshold=15,
    ),
)


def number_searcher2_clear_extra_stats(difficulty: int, negative_modifier: str | None = None) -> dict[str, int]:
    extra_stats = {HIGHEST_CLEAR_EXTRA_KEY: int(difficulty)}
    if negative_modifier:
        extra_stats[f"{NEGATIVE_MODIFIER_CLEAR_PREFIX}{negative_modifier}"] = 1
    return extra_stats


def _extra(stats: dict | None) -> dict:
    return stats.get("extra", {}) if isinstance(stats, dict) and isinstance(stats.get("extra", {}), dict) else {}


def negative_modifier_clear_count(stats: dict | None) -> int:
    extra = _extra(stats)
    return sum(1 for name in NUMBER_SEARCHER2_NEGATIVE_MODIFIERS if int(extra.get(f"{NEGATIVE_MODIFIER_CLEAR_PREFIX}{name}", 0) or 0) > 0)


def stamp_unlocked(stats: dict | None, stamp: EtchingStampDefinition) -> bool:
    extra = _extra(stats)
    if stamp.unlock_kind == "highest_difficulty":
        return int(extra.get(HIGHEST_CLEAR_EXTRA_KEY, 0) or 0) >= int(stamp.threshold or 0)
    if stamp.unlock_kind == "all_negative_modifiers":
        return negative_modifier_clear_count(stats) == len(NUMBER_SEARCHER2_NEGATIVE_MODIFIERS)
    return False


def earned_stamp_keys(stats: dict | None) -> set[str]:
    return {stamp.key for stamp in NUMBER_SEARCHER2_STAMPS if stamp_unlocked(stats, stamp)}


def preview_stats_after_extra(stats: dict | None, extra_stats: dict) -> dict:
    preview = dict(stats or {})
    preview_extra = dict(_extra(preview))
    for key, value in extra_stats.items():
        if value is None:
            continue
        if key == HIGHEST_CLEAR_EXTRA_KEY:
            preview_extra[key] = max(int(preview_extra.get(key, 0) or 0), int(value))
        elif key.startswith(NEGATIVE_MODIFIER_CLEAR_PREFIX):
            preview_extra[key] = int(preview_extra.get(key, 0) or 0) + int(value)
    preview["extra"] = preview_extra
    return preview


def newly_earned_stamp_keys(before_stats: dict | None, extra_stats: dict) -> list[str]:
    before = earned_stamp_keys(before_stats)
    after = earned_stamp_keys(preview_stats_after_extra(before_stats, extra_stats))
    return [stamp.key for stamp in NUMBER_SEARCHER2_STAMPS if stamp.key in after - before]


def stamp_title(key: str) -> str:
    for stamp in NUMBER_SEARCHER2_STAMPS:
        if stamp.key == key:
            return stamp.title
    return key
