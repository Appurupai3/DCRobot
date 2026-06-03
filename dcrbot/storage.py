"""Persistent storage helpers for the economy system."""

from __future__ import annotations

import json
import os
from typing import Dict, Any


BANK_DATA_PATH = "bank.json"


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
        json.dump(users, f, indent=4)


async def open_account(user) -> bool:
    """Ensure a user has an account entry.

    Returns ``True`` when a new account is created so callers can branch on
    the first-use experience if desired.
    """

    users = load_data()
    if str(user.id) not in users:
        users[str(user.id)] = {"wallet": 0, "bank": 0}
        save_data(users)
        return True
    return False


# 遊戲暫存冷卻（僅記憶體，重啟重置）
heist_blacklist: dict[str, float] = {}
