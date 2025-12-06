"""Persistent storage helpers for the economy system."""

from __future__ import annotations

import json
import os
from typing import Dict, Any


def load_data() -> Dict[str, Any]:
    """Load bank data from disk if present.

    Returns an empty dict when the file does not exist to keep callers simple.
    """

    if not os.path.exists("bank.json"):
        return {}

    with open("bank.json", "r") as f:
        return json.load(f)


def save_data(users: Dict[str, Any]) -> None:
    """Persist bank data to disk with indentation for readability."""

    with open("bank.json", "w") as f:
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
