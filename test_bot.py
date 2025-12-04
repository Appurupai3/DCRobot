import asyncio
import sys
import types
from unittest.mock import Mock, patch

import pytest


def ensure_discord_and_riotwatcher_stubs():
    if "discord" not in sys.modules:
        class DummyEmbed:
            def __init__(self, *args, **kwargs):
                self.description = None

            def add_field(self, *args, **kwargs):
                return None

            def set_footer(self, *args, **kwargs):
                return None

        class DummyColor:
            @staticmethod
            def red():
                return 0

            @staticmethod
            def dark_red():
                return 0

            @staticmethod
            def green():
                return 0

        class DummyIntents:
            def __init__(self):
                self.message_content = False
                self.members = False

            @staticmethod
            def default():
                return DummyIntents()

        class DummyResponse:
            async def send_message(self, *args, **kwargs):
                return None

        class DummyInteraction:
            def __init__(self):
                self.response = DummyResponse()

        class DummyBot:
            def __init__(self, *args, **kwargs):
                self.user = None
                async def tree_sync():
                    return None

                self.tree = types.SimpleNamespace(
                    command=lambda *a, **k: (lambda func: func),
                    sync=tree_sync,
                )

            def run(self, *args, **kwargs):
                return None

            def command(self, *args, **kwargs):
                def decorator(func):
                    return func

                return decorator

            def event(self, func):
                return func

            async def fetch_user(self, *args, **kwargs):
                return Mock(id=0, mention="@user")

        class DummyCommands:
            Bot = DummyBot

        class DummyUIComponent:
            def __init__(self, *args, **kwargs):
                pass

            def __init_subclass__(cls, **kwargs):
                return super().__init_subclass__()

        class DummyView:
            def __init__(self, *args, **kwargs):
                pass

            def __init_subclass__(cls, **kwargs):
                return super().__init_subclass__()

        ui_namespace = types.SimpleNamespace(
            Button=DummyUIComponent,
            View=DummyView,
            Modal=DummyUIComponent,
            TextInput=DummyUIComponent,
            button=lambda *a, **k: (lambda func: func),
        )

        discord_module = types.SimpleNamespace(
            app_commands=types.SimpleNamespace(),
            Intents=DummyIntents,
            Color=DummyColor,
            Embed=DummyEmbed,
            ui=ui_namespace,
            Interaction=DummyInteraction,
            ButtonStyle=types.SimpleNamespace(green=None, blurple=None, red=None, gray=None, danger=None),
        )

        sys.modules["discord"] = discord_module
        sys.modules["discord.ext"] = types.SimpleNamespace(commands=DummyCommands())
        sys.modules["discord.ext.commands"] = DummyCommands()
        sys.modules["discord.ui"] = ui_namespace

    if "riotwatcher" not in sys.modules:
        class DummyWatcher:
            def __init__(self, *args, **kwargs):
                pass

        class DummyApiError(Exception):
            def __init__(self, status_code=500):
                self.response = types.SimpleNamespace(status_code=status_code)

        riotwatcher_module = types.SimpleNamespace(ValWatcher=DummyWatcher, RiotWatcher=DummyWatcher, ApiError=DummyApiError)
        sys.modules["riotwatcher"] = riotwatcher_module

    if "dotenv" not in sys.modules:
        sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda: None)

    if "requests" not in sys.modules:
        sys.modules["requests"] = types.SimpleNamespace(get=lambda *a, **k: Mock())


ensure_discord_and_riotwatcher_stubs()

import bot


def make_response(status_code, json_data=None):
    response = Mock()
    response.status_code = status_code
    response.json = Mock(return_value=json_data or {})
    return response


def test_format_alt_stat_sites_lists_known_domains():
    text = bot.format_alt_stat_sites()
    for name, _ in bot.ALT_VALORANT_STAT_SITES:
        assert name in text


def test_build_permission_error_message_includes_sites_and_extra():
    message = bot.build_permission_error_message("extra line")

    assert "VALORANT Match 查詢" in message
    assert "extra line" in message
    for name, _ in bot.ALT_VALORANT_STAT_SITES:
        assert name in message


def test_fetch_fallback_without_key_returns_error(monkeypatch):
    monkeypatch.delenv("HENRIK_API_KEY", raising=False)
    result, error = bot.fetch_fallback_valorant_stats("puuid")
    assert result is None
    assert "備援 API 需要有效的鑰匙" in error


def test_fetch_fallback_unauthorized(monkeypatch):
    monkeypatch.setenv("HENRIK_API_KEY", "dummy")
    with patch("bot.requests.get", return_value=make_response(401)):
        result, error = bot.fetch_fallback_valorant_stats("puuid")
    assert result is None
    assert "備援 API 需要有效的鑰匙" in error


def test_fetch_fallback_success(monkeypatch):
    monkeypatch.setenv("HENRIK_API_KEY", "dummy")
    sample_match = {
        "data": [
            {
                "players": {
                    "all_players": [
                        {
                            "puuid": "player-puuid",
                            "name": "TestPlayer",
                            "currenttier": 15,
                            "stats": {"kills": 10, "deaths": 5, "assists": 3},
                        }
                    ]
                }
            }
        ]
    }

    with patch("bot.requests.get", return_value=make_response(200, sample_match)):
        result, error = bot.fetch_fallback_valorant_stats("player-puuid", "TestPlayer#1234")

    assert error is None
    assert result == ("白金 (Platinum) 1", 10, 5, 3)


def test_testerror_command_returns_ephemeral_message():
    class DummyResponse:
        def __init__(self):
            self.sent = []

        async def send_message(self, content=None, ephemeral=None):
            self.sent.append((content, ephemeral))

    interaction = Mock()
    interaction.response = DummyResponse()

    asyncio.run(bot.testerror_command(interaction))

    assert interaction.response.sent
    message, ephemeral = interaction.response.sent[0]
    assert ephemeral is True
    assert "Riot API Key" in message
