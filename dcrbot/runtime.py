"""Runtime bootstrap helpers for the Discord bot."""

from __future__ import annotations

import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from dcrbot.storage import ensure_bank_data_file


ENV_FILE = ".env"
TOKEN_ENV_VAR = "DISCORD_TOKEN"
COMMAND_PREFIX = "!"


def ensure_env_file(path: str = ENV_FILE) -> None:
    """Create a local .env template on first startup if it is missing."""

    if os.path.exists(path):
        return

    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Add your Discord bot token here\n{TOKEN_ENV_VAR}=\n")


def ensure_runtime_files() -> None:
    """Create local runtime files needed by the bot before it starts."""

    ensure_env_file()
    ensure_bank_data_file()


def load_discord_token() -> str | None:
    """Load the Discord token from the local environment configuration."""

    ensure_runtime_files()
    load_dotenv(ENV_FILE)
    return os.getenv(TOKEN_ENV_VAR)


def create_discord_bot() -> commands.Bot:
    """Build the Discord bot with the intents required by all commands."""

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    return commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)


def patch_discord_test_stubs() -> None:
    """Patch lightweight Discord stubs used by tests to look like discord.py."""

    # Ensure ButtonStyle works when running with lightweight stubs in tests.
    if hasattr(discord, "ButtonStyle"):
        button_style = discord.ButtonStyle
        style_fallbacks = {"primary": "blurple", "secondary": "gray", "success": "green"}
        for attr, fallback in style_fallbacks.items():
            if not hasattr(button_style, attr):
                setattr(button_style, attr, getattr(button_style, fallback, None))

    if not hasattr(app_commands, "describe"):
        def _noop_describe(**_kwargs):
            def decorator(func):
                return func

            return decorator

        app_commands.describe = _noop_describe

    if not hasattr(app_commands, "choices"):
        def _noop_choices(**_kwargs):
            def decorator(func):
                return func

            return decorator

        app_commands.choices = _noop_choices

    if not hasattr(app_commands, "Choice"):
        class _DummyChoice:
            def __init__(self, name: str, value):
                self.name = name
                self.value = value

        app_commands.Choice = _DummyChoice
