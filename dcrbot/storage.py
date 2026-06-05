"""Persistent storage helpers for the economy system."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Dict, Any


BANK_DATA_PATH = "bank.json"
MAX_GAME_RECORDS = 100


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


def ensure_user_data(users: Dict[str, Any], uid: str) -> Dict[str, Any]:
    """Ensure an existing user dictionary has all economy/game-history keys."""

    user_data = users.setdefault(uid, {})
    user_data.setdefault("wallet", 0)
    user_data.setdefault("bank", 0)
    user_data.setdefault("game_records", [])
    return user_data


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
) -> None:
    """Append one persistent game record for a user, keeping only recent entries."""

    user_data = ensure_user_data(users, uid)
    if balance is None:
        balance = int(user_data.get("wallet", 0))

    records = user_data.setdefault("game_records", [])
    records.append(
        {
            "played_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "game": game_name,
            "result": result,
            "bet": int(bet),
            "delta": int(delta),
            "balance": int(balance),
            "details": details,
        }
    )
    if len(records) > MAX_GAME_RECORDS:
        del records[:-MAX_GAME_RECORDS]


def get_game_records(users: Dict[str, Any], uid: str, limit: int = 10) -> list[Dict[str, Any]]:
    """Return recent game records for display, newest first."""

    records = ensure_user_data(users, uid).get("game_records", [])
    return list(reversed(records[-limit:]))


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
