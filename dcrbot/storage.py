"""Persistent storage helpers for the economy system."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Dict, Any


BANK_DATA_PATH = "bank.json"
LEADERBOARD_DIR = Path("leaderboard")
LEADERBOARD_INDEX_PATH = LEADERBOARD_DIR / "index.json"
MAX_GAME_RECORDS = 100
BANK_ALLOWED_KEYS = {"wallet", "bank", "number_searcher2_unlocked"}


def ensure_leaderboard_dir() -> None:
    """Create the categorized leaderboard directory used for per-game records."""

    LEADERBOARD_DIR.mkdir(parents=True, exist_ok=True)


def _safe_leaderboard_name(game_name: str) -> str:
    """Return a readable filesystem-safe filename stem for a game name."""

    cleaned = "".join(
        char if char.isalnum() or char in {"-", "_", " ", "："} else "_"
        for char in game_name.strip()
    ).strip()
    return (cleaned or "unknown_game").replace(" ", "_")[:80]



def _is_multiplayer_game_stat(game_name: str, value: Dict[str, Any] | None = None) -> bool:
    """Return True when a compact stat belongs to multiplayer battles hidden from bank views."""

    stat_game = str((value or {}).get("game", game_name))
    return game_name.startswith("多人遊戲：") or stat_game.startswith("多人遊戲：")


def _load_json_list(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _load_json_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)



def ensure_bank_data_file() -> None:
    """Create the local bank data file on first startup if it is missing."""

    if os.path.exists(BANK_DATA_PATH):
        return

    with open(BANK_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump({}, f, indent=4)


def _sanitize_bank_user_data(user_data: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = {
        "wallet": int(user_data.get("wallet", 0) or 0),
        "bank": int(user_data.get("bank", 0) or 0),
    }
    if "number_searcher2_unlocked" in user_data:
        cleaned["number_searcher2_unlocked"] = int(user_data.get("number_searcher2_unlocked", 0) or 0)
    return cleaned


def sanitize_bank_data(users: Dict[str, Any]) -> Dict[str, Any]:
    """Return a bank.json-safe copy containing only economy and unlock fields."""

    return {str(uid): _sanitize_bank_user_data(data if isinstance(data, dict) else {}) for uid, data in users.items()}


def load_data() -> Dict[str, Any]:
    """Load bank data from disk, migrating non-bank stats into leaderboard files."""

    ensure_bank_data_file()

    with open(BANK_DATA_PATH, "r", encoding="utf-8") as f:
        users = json.load(f)
    if not isinstance(users, dict):
        users = {}

    changed = migrate_bank_extras_to_leaderboard(users)
    cleaned = sanitize_bank_data(users)
    if changed or cleaned != users:
        save_data(cleaned)
    return cleaned


def save_data(users: Dict[str, Any]) -> None:
    """Persist only bank-safe economy fields to disk with indentation."""

    cleaned = sanitize_bank_data(users)
    with open(BANK_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=4, ensure_ascii=False)


def _empty_game_stat(game_name: str) -> Dict[str, Any]:
    return {
        "game": game_name,
        "plays": 0,
        "wins": 0,
        "losses": 0,
        "evens": 0,
        "total_delta": 0,
        "total_bet": 0,
        "max_profit": None,
        "max_loss": None,
        "last_played_at": "",
        "extra": {},
    }


def _is_win_result(result: str, delta: int) -> bool:
    return delta > 0 or any(keyword in result for keyword in ("勝利", "成功", "領獎"))


def _apply_game_stat(
    stats: Dict[str, Any],
    *,
    game_name: str,
    result: str,
    bet: int,
    delta: int,
    played_at: str,
    extra_stats: Dict[str, int | float] | None = None,
) -> Dict[str, Any]:
    game_stat = stats.setdefault(game_name, _empty_game_stat(game_name))
    game_stat.setdefault("game", game_name)
    game_stat.setdefault("plays", 0)
    game_stat.setdefault("wins", 0)
    game_stat.setdefault("losses", 0)
    game_stat.setdefault("evens", 0)
    game_stat.setdefault("total_delta", 0)
    game_stat.setdefault("total_bet", 0)
    game_stat.setdefault("max_profit", None)
    game_stat.setdefault("max_loss", None)
    game_stat.setdefault("last_played_at", "")
    game_stat.setdefault("extra", {})

    game_stat["plays"] = int(game_stat.get("plays", 0) or 0) + 1
    game_stat["total_delta"] = int(game_stat.get("total_delta", 0) or 0) + int(delta)
    game_stat["total_bet"] = int(game_stat.get("total_bet", 0) or 0) + int(bet)
    game_stat["last_played_at"] = played_at

    if _is_win_result(result, int(delta)):
        game_stat["wins"] = int(game_stat.get("wins", 0) or 0) + 1
    elif int(delta) < 0 or any(keyword in result for keyword in ("失敗", "爆炸", "逾時", "放棄")):
        game_stat["losses"] = int(game_stat.get("losses", 0) or 0) + 1
    else:
        game_stat["evens"] = int(game_stat.get("evens", 0) or 0) + 1

    if int(delta) > 0:
        max_profit = game_stat.get("max_profit")
        game_stat["max_profit"] = int(delta) if max_profit is None else max(int(max_profit), int(delta))
    elif int(delta) < 0:
        max_loss = game_stat.get("max_loss")
        game_stat["max_loss"] = int(delta) if max_loss is None else min(int(max_loss), int(delta))

    if extra_stats:
        extras = game_stat.setdefault("extra", {})
        for key, value in extra_stats.items():
            if value is None:
                continue
            current = extras.get(key, 0)
            extras[key] = float(current) + float(value) if isinstance(value, float) else int(current) + int(value)

    return game_stat


def _merge_compact_stat_to_leaderboard(uid: str, game_name: str, stat: Dict[str, Any]) -> None:
    """Copy a compact per-user game stat into leaderboard storage without duplicating it."""

    ensure_leaderboard_dir()
    record_path = LEADERBOARD_DIR / f"{_safe_leaderboard_name(game_name)}.json"
    game_stats = _load_json_dict(record_path)
    current = game_stats.get(uid)
    if isinstance(current, dict) and int(current.get("plays", 0) or 0) >= int(stat.get("plays", 0) or 0):
        return

    merged = _empty_game_stat(game_name)
    merged.update({key: value for key, value in stat.items() if key in merged or key == "game"})
    merged["game"] = str(merged.get("game") or game_name)
    game_stats[uid] = merged
    _write_json(record_path, game_stats)
    _update_leaderboard_index(game_name, record_path, game_stats, str(merged.get("last_played_at", "")))


def migrate_bank_extras_to_leaderboard(users: Dict[str, Any]) -> bool:
    """Move legacy game data out of bank.json and into leaderboard/*.json."""

    changed = False
    for uid, user_data in users.items():
        if not isinstance(user_data, dict):
            changed = True
            continue
        legacy_stats = user_data.get("game_stats")
        if isinstance(legacy_stats, dict):
            for game_name, stat in legacy_stats.items():
                if isinstance(stat, dict):
                    _merge_compact_stat_to_leaderboard(str(uid), str(game_name), stat)
            changed = True
        legacy_records = user_data.get("game_records")
        if isinstance(legacy_records, list):
            for record in legacy_records:
                if not isinstance(record, dict):
                    continue
                append_leaderboard_record(
                    {
                        "user_id": str(uid),
                        "played_at": str(record.get("played_at", "")),
                        "game": str(record.get("game", "未知遊戲")),
                        "result": str(record.get("result", "完成")),
                        "bet": int(record.get("bet", 0) or 0),
                        "delta": int(record.get("delta", 0) or 0),
                        "extra_stats": record.get("extra_stats") if isinstance(record.get("extra_stats"), dict) else {},
                    }
                )
            changed = True
        if any(key not in BANK_ALLOWED_KEYS for key in user_data):
            changed = True
    return changed


def _migrate_record_list_to_stats(user_data: Dict[str, Any]) -> None:
    """Convert legacy per-round rows into leaderboard statistics once."""

    records = user_data.pop("game_records", None)
    user_data.pop("game_records_migrated", None)
    if not records:
        return

    # Legacy rows are migrated by load_data(), before bank.json is sanitized.


def ensure_user_data(users: Dict[str, Any], uid: str) -> Dict[str, Any]:
    """Ensure an existing user dictionary has all economy/stat keys."""

    user_data = users.setdefault(uid, {})
    user_data.setdefault("wallet", 0)
    user_data.setdefault("bank", 0)
    if any(key not in BANK_ALLOWED_KEYS for key in user_data):
        migrate_bank_extras_to_leaderboard({uid: user_data})
    _migrate_record_list_to_stats(user_data)
    for key in list(user_data):
        if key not in BANK_ALLOWED_KEYS:
            user_data.pop(key, None)
    return user_data


def _update_leaderboard_index(game_name: str, record_path: Path, game_stats: Dict[str, Any], played_at: str | None) -> None:
    index_records = _load_json_list(LEADERBOARD_INDEX_PATH)
    index_by_game = {entry.get("game"): entry for entry in index_records if isinstance(entry, dict)}
    index_by_game[game_name] = {
        "game": game_name,
        "file": str(record_path),
        "players": len(game_stats),
        "updated_at": played_at,
    }
    _write_json(LEADERBOARD_INDEX_PATH, sorted(index_by_game.values(), key=lambda item: str(item.get("game", ""))))


def append_leaderboard_record(record: Dict[str, Any]) -> None:
    """Merge one result into leaderboard/<game>.json and update the index."""

    ensure_leaderboard_dir()
    game_name = str(record.get("game", "未知遊戲"))
    file_stem = _safe_leaderboard_name(game_name)
    record_path = LEADERBOARD_DIR / f"{file_stem}.json"
    uid = str(record.get("user_id", ""))

    game_stats = _load_json_dict(record_path)

    user_stats = game_stats.setdefault(uid, _empty_game_stat(game_name))
    _apply_game_stat(
        {game_name: user_stats},
        game_name=game_name,
        result=str(record.get("result", "完成")),
        bet=int(record.get("bet", 0) or 0),
        delta=int(record.get("delta", 0) or 0),
        played_at=str(record.get("played_at", "")),
        extra_stats=record.get("extra_stats") if isinstance(record.get("extra_stats"), dict) else None,
    )
    game_stats[uid] = user_stats
    _write_json(record_path, game_stats)

    _update_leaderboard_index(game_name, record_path, game_stats, record.get("played_at"))


def append_game_record(
    users: Dict[str, Any],
    uid: str,
    *,
    game_name: str,
    result: str,
    bet: int = 0,
    delta: int = 0,
    balance: int | None = None,
    details: str = "",
    extra_stats: Dict[str, int | float] | None = None,
) -> None:
    """Update compact game statistics; no per-round situation rows are stored."""

    ensure_user_data(users, uid)
    played_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    append_leaderboard_record(
        {
            "user_id": uid,
            "played_at": played_at,
            "game": game_name,
            "result": result,
            "bet": int(bet),
            "delta": int(delta),
            "extra_stats": extra_stats or {},
        }
    )


def _leaderboard_record_paths() -> list[Path]:
    if LEADERBOARD_INDEX_PATH.exists():
        paths = []
        for entry in _load_json_list(LEADERBOARD_INDEX_PATH):
            if not isinstance(entry, dict):
                continue
            path = Path(str(entry.get("file", "")))
            if path.exists():
                paths.append(path)
        if paths:
            return paths
    return sorted(LEADERBOARD_DIR.glob("*.json")) if LEADERBOARD_DIR.exists() else []


def load_user_leaderboard_stats(uid: str) -> dict[str, Dict[str, Any]]:
    """Load a user's compact per-game stats from leaderboard/*.json."""

    stats: dict[str, Dict[str, Any]] = {}
    for record_path in _leaderboard_record_paths():
        if record_path == LEADERBOARD_INDEX_PATH:
            continue
        game_stats = _load_json_dict(record_path)
        value = game_stats.get(str(uid))
        if not isinstance(value, dict):
            continue
        game_name = str(value.get("game") or record_path.stem.replace("_", " "))
        stats[game_name] = dict(value)
    return stats


def get_game_records(users: Dict[str, Any], uid: str, limit: int = 10) -> list[Dict[str, Any]]:
    """Return compact per-game statistics sorted by latest play time."""

    ensure_user_data(users, uid)
    records = [
        value
        for game_name, value in load_user_leaderboard_stats(uid).items()
        if isinstance(value, dict) and not _is_multiplayer_game_stat(str(game_name), value)
    ]
    records.sort(key=lambda item: str(item.get("last_played_at", "")), reverse=True)
    return records[:limit]


def summarize_game_records(users: Dict[str, Any], uid: str) -> dict[str, Dict[str, Any]]:
    """Return a user's compact per-game statistics for portfolio/stat views."""

    ensure_user_data(users, uid)
    return {
        str(game): dict(value)
        for game, value in load_user_leaderboard_stats(uid).items()
        if isinstance(value, dict) and not _is_multiplayer_game_stat(str(game), value)
    }


def get_profit_loss_records(users: Dict[str, Any], uid: str, limit: int = 5) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Return top profitable and loss-making game statistics."""

    records = list(summarize_game_records(users, uid).values())
    profits = sorted((record for record in records if int(record.get("total_delta", 0) or 0) > 0), key=lambda item: int(item.get("total_delta", 0) or 0), reverse=True)[:limit]
    losses = sorted((record for record in records if int(record.get("total_delta", 0) or 0) < 0), key=lambda item: int(item.get("total_delta", 0) or 0))[:limit]
    return profits, losses


async def open_account(user) -> bool:
    """Ensure a user has an account entry.

    Returns ``True`` when a new account is created so callers can branch on
    the first-use experience if desired.
    """

    users = load_data()
    uid = str(user.id)
    created = uid not in users
    before = json.dumps(users.get(uid, {}), sort_keys=True, ensure_ascii=False)
    ensure_user_data(users, uid)
    after = json.dumps(users.get(uid, {}), sort_keys=True, ensure_ascii=False)
    if created or before != after:
        save_data(users)
    return created


# 遊戲暫存冷卻（僅記憶體，重啟重置）
heist_blacklist: dict[str, float] = {}
