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


def _load_json_list(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)



def ensure_bank_data_file() -> None:
    """Create the local bank data file on first startup if it is missing."""

    if os.path.exists(BANK_DATA_PATH):
        return

    with open(BANK_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump({}, f, indent=4)


def load_data() -> Dict[str, Any]:
    """Load bank data from disk, creating the file on first startup."""

    ensure_bank_data_file()

    with open(BANK_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(users: Dict[str, Any]) -> None:
    """Persist bank data to disk with indentation for readability."""

    with open(BANK_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4, ensure_ascii=False)


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


def _migrate_record_list_to_stats(user_data: Dict[str, Any]) -> None:
    """Convert legacy per-round rows into compact per-game statistics once."""

    records = user_data.get("game_records")
    if not records or user_data.get("game_records_migrated"):
        user_data.setdefault("game_records", [])
        return

    stats = user_data.setdefault("game_stats", {})
    for record in records:
        if not isinstance(record, dict):
            continue
        _apply_game_stat(
            stats,
            game_name=str(record.get("game", "未知遊戲")),
            result=str(record.get("result", "完成")),
            bet=int(record.get("bet", 0) or 0),
            delta=int(record.get("delta", 0) or 0),
            played_at=str(record.get("played_at", "")),
        )
    user_data["game_records"] = []
    user_data["game_records_migrated"] = True


def ensure_user_data(users: Dict[str, Any], uid: str) -> Dict[str, Any]:
    """Ensure an existing user dictionary has all economy/stat keys."""

    user_data = users.setdefault(uid, {})
    user_data.setdefault("wallet", 0)
    user_data.setdefault("bank", 0)
    user_data.setdefault("game_stats", {})
    _migrate_record_list_to_stats(user_data)
    return user_data


def append_leaderboard_record(record: Dict[str, Any]) -> None:
    """Merge one result into leaderboard/<game>.json and update the index."""

    ensure_leaderboard_dir()
    game_name = str(record.get("game", "未知遊戲"))
    file_stem = _safe_leaderboard_name(game_name)
    record_path = LEADERBOARD_DIR / f"{file_stem}.json"
    uid = str(record.get("user_id", ""))

    try:
        with record_path.open("r", encoding="utf-8") as f:
            game_stats = json.load(f)
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        game_stats = {}
    if not isinstance(game_stats, dict):
        game_stats = {}

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

    index_records = _load_json_list(LEADERBOARD_INDEX_PATH)
    index_by_game = {entry.get("game"): entry for entry in index_records if isinstance(entry, dict)}
    index_by_game[game_name] = {
        "game": game_name,
        "file": str(record_path),
        "players": len(game_stats),
        "updated_at": record.get("played_at"),
    }
    _write_json(LEADERBOARD_INDEX_PATH, sorted(index_by_game.values(), key=lambda item: str(item.get("game", ""))))


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

    user_data = ensure_user_data(users, uid)
    played_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stats = user_data.setdefault("game_stats", {})
    _apply_game_stat(
        stats,
        game_name=game_name,
        result=result,
        bet=int(bet),
        delta=int(delta),
        played_at=played_at,
        extra_stats=extra_stats,
    )
    user_data["game_records"] = []

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


def get_game_records(users: Dict[str, Any], uid: str, limit: int = 10) -> list[Dict[str, Any]]:
    """Return compact per-game statistics sorted by latest play time."""

    stats = ensure_user_data(users, uid).get("game_stats", {})
    records = [value for value in stats.values() if isinstance(value, dict)]
    records.sort(key=lambda item: str(item.get("last_played_at", "")), reverse=True)
    return records[:limit]


def summarize_game_records(users: Dict[str, Any], uid: str) -> dict[str, Dict[str, Any]]:
    """Return a user's compact per-game statistics for portfolio/stat views."""

    stats = ensure_user_data(users, uid).get("game_stats", {})
    return {str(game): dict(value) for game, value in stats.items() if isinstance(value, dict)}


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
