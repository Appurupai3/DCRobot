"""Birthday firework animation helpers."""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Awaitable, Callable

import discord


FIREWORK_CANVAS = (21, 9)
FIREWORK_SPARKS = ["✨", "💥", "🌟", "🔥", "🎇", "🎆", "⭐", "✦"]
FIREWORK_BACKDROP = "·"


def render_firework_frame(name: str, remaining: int) -> discord.Embed:
    width, height = FIREWORK_CANVAS
    grid = [[FIREWORK_BACKDROP for _ in range(width)] for _ in range(height)]

    bursts = random.randint(5, 8)
    for _ in range(bursts):
        x = random.randint(1, width - 2)
        y = random.randint(1, height - 2)
        spark = random.choice(FIREWORK_SPARKS)
        grid[y][x] = spark
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height and grid[ny][nx] == FIREWORK_BACKDROP:
                grid[ny][nx] = random.choice([spark, "✧", "・"])

    art = "\n".join("".join(row) for row in grid)
    embed = discord.Embed(
        title="🎉 BirthFire 生日煙火",
        description=(
            f"🎆 為 **{name}** 點亮專屬煙火！\n"
            f"```{art}```\n"
            f"⏳ 倒數 {remaining:02d} 秒"
        ),
        color=random.choice(
            [discord.Color.blue(), discord.Color.purple(), discord.Color.gold(), discord.Color.orange()]
        ),
    )
    return embed


async def run_birthfire_animation(message: discord.Message, name: str, duration: int = 30):
    start = time.monotonic()
    remaining = duration
    try:
        while remaining > 0:
            await message.edit(embed=render_firework_frame(name, remaining))
            await asyncio.sleep(2)
            elapsed = int(time.monotonic() - start)
            remaining = max(duration - elapsed, 0)

        finale = discord.Embed(
            title="🎇 生日快樂！",
            description=(
                f"為 **{name}** 的 30 秒煙火謝幕！\n"
                "願新的旅程閃耀繽紛，每一天都像煙火般精彩。"
            ),
            color=discord.Color.magenta(),
        )
        await message.edit(embed=finale)
    except discord.HTTPException:
        return


async def launch_birthfire(
    channel_send: Callable[..., Awaitable[Any]],
    fetch_message: Callable[[], Awaitable[discord.Message]],
    name: str,
    user: discord.abc.User,
):
    display_name = name or user.display_name
    initial = await channel_send(embed=render_firework_frame(display_name, 30))
    message = initial if isinstance(initial, discord.Message) else await fetch_message()
    asyncio.create_task(run_birthfire_animation(message, display_name))
