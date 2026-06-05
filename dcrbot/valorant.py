"""Valorant-style tactics minigame UI and game logic."""

from __future__ import annotations

import asyncio
import math
import random
from typing import Any, Awaitable, Callable, Optional

import discord
from discord.ui import Button, View, Modal, TextInput


# === 特戰棋盤設定 ===
VALORANT_WIDTH = 15
VALORANT_HEIGHT = 13
VALORANT_ICONS = {
    "EMPTY": "⬜",
    "WALL": "⬛",
    "PLAYER": "🟦",
    "ENEMY": "🟥",
    "SPIKE": "💠",
    "SITE": "🟩",
    "SMOKE": "☁️",
    "SLOW": "❄️",
}


def clip_status(log_lines: list[str], max_lines: int = 14, max_chars: int = 950) -> str:
    """Clamp status output to Discord embed field limits."""
    recent = log_lines[-max_lines:]
    text = "\n".join(recent)
    if len(text) <= max_chars:
        return text
    # truncate from the front while preserving newest entries
    while len(recent) > 1 and len("\n".join(recent)) > max_chars:
        recent = recent[1:]
    text = "\n".join(recent)
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text


class VisibilityUtils:
    def __init__(self, grid, smoke_tiles: set[tuple[int, int]], width: int, height: int):
        self.grid = grid
        self.smoke_tiles = smoke_tiles
        self.width = width
        self.height = height

    def within_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def get_distance(self, p1, p2):
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def get_line_points(self, p1, p2):
        x1, y1 = p1
        x2, y2 = p2
        points = []

        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        err = dx - dy

        while True:
            points.append((x1, y1))
            if x1 == x2 and y1 == y2:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x1 += sx
            if e2 < dx:
                err += dx
                y1 += sy

        return points

    def has_los(self, start, end):
        line_points = self.get_line_points(start, end)
        if len(line_points) > 2:
            for px, py in line_points[1:-1]:
                if not self.within_bounds(px, py):
                    return False
                if self.grid[py][px] == "WALL" or (px, py) in self.smoke_tiles:
                    return False
        return True

    def check_attack_eligibility(self, attacker_pos, target_pos):
        dist = self.get_distance(attacker_pos, target_pos)
        if dist <= 1.5:
            return True
        return self.has_los(attacker_pos, target_pos)


class ValorantTacticsGame:
    def __init__(self, skills: list[str]):
        self.grid = [["EMPTY" for _ in range(VALORANT_WIDTH)] for _ in range(VALORANT_HEIGHT)]
        self.player_pos = [1, 1]
        self.player_facing = (1, 0)
        self.spike_pos: list[int] | None = None
        self.spike_planted = False
        self.plant_turn: int | None = None
        self.plant_sites: list[list[tuple[int, int]]] = []
        self.site_centers: list[tuple[int, int]] = []
        self.player_hp = 4
        self.enemies: list[dict[str, Any]] = []
        self.turn = 1
        self.moves_left = 3
        self.attack_used = False
        self.enemy_defuse_progress = 0
        self.defusing_enemy: int | None = None
        self.smoke_tiles: set[tuple[int, int]] = set()
        self.slow_tiles: set[tuple[int, int]] = set()
        self.skills = skills
        self.skill_charges = {name: 1 for name in ["smoke", "flash", "slow", "bind", "teleport"]}
        self.enemy_skill = random.choice(["molly", "recon"])
        self.generate_map()
        self.start_player_turn()

    def generate_map(self):
        self.generate_plant_sites()
        self.spawn_enemies()
        wall_count = random.randint(20, 30)
        forbidden = {tuple(self.player_pos)} | {tuple(e["pos"]) for e in self.enemies}
        for _ in range(wall_count):
            rx, ry = random.randint(0, VALORANT_WIDTH - 1), random.randint(0, VALORANT_HEIGHT - 1)
            if (rx, ry) in forbidden:
                continue
            self.grid[ry][rx] = "WALL"

        self.ensure_paths()

    def ensure_paths(self):
        def is_walkable(x: int, y: int) -> bool:
            return self.grid[y][x] != "WALL"

        def reachable() -> set[tuple[int, int]]:
            seen: set[tuple[int, int]] = set()
            q = [tuple(self.player_pos)]
            seen.add(tuple(self.player_pos))
            while q:
                cx, cy = q.pop(0)
                for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    nx, ny = cx + dx, cy + dy
                    if not self.within_bounds(nx, ny):
                        continue
                    if (nx, ny) in seen or not is_walkable(nx, ny):
                        continue
                    seen.add((nx, ny))
                    q.append((nx, ny))
            return seen

        targets = list(self.site_centers)
        attempts = 0
        while attempts < 300:
            seen = reachable()
            missing = [t for t in targets if t not in seen]
            if not missing:
                break

            # Pick walls adjacent to the reachable blob and open a corridor toward the closest missing target
            frontier: list[tuple[int, int]] = []
            for cx, cy in seen:
                for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    nx, ny = cx + dx, cy + dy
                    if self.within_bounds(nx, ny) and self.grid[ny][nx] == "WALL":
                        frontier.append((nx, ny))

            if not frontier:
                break

            target = random.choice(missing)
            best = min(frontier, key=lambda p: abs(p[0] - target[0]) + abs(p[1] - target[1]))
            self.grid[best[1]][best[0]] = "EMPTY"
            attempts += 1

    def within_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < VALORANT_WIDTH and 0 <= y < VALORANT_HEIGHT

    def generate_plant_sites(self):
        def random_site() -> tuple[int, int]:
            return random.randint(0, VALORANT_WIDTH - 5), random.randint(0, VALORANT_HEIGHT - 5)

        first = random_site()
        while True:
            second = random_site()
            if abs((first[0] + 2) - (second[0] + 2)) + abs((first[1] + 2) - (second[1] + 2)) >= 5:
                break

        for idx, top_left in enumerate([first, second]):
            tiles: list[tuple[int, int]] = []
            x0, y0 = top_left
            for dy in range(5):
                for dx in range(5):
                    tx, ty = x0 + dx, y0 + dy
                    tiles.append((tx, ty))
            self.plant_sites.append(list(tiles))
            self.site_centers.append((x0 + 2, y0 + 2))
            for tx, ty in tiles:
                if (tx, ty) != tuple(self.player_pos):
                    self.grid[ty][tx] = "SITE"

            rock_count = random.randint(6, 14)
            tiles_copy = tiles[:]
            random.shuffle(tiles_copy)
            rocks = 0
            for tx, ty in tiles_copy:
                if rocks >= rock_count:
                    break
                if (tx, ty) == tuple(self.player_pos):
                    continue
                self.grid[ty][tx] = "WALL"
                rocks += 1

            # carve at least one entrance so planting zones are never fully sealed
            edge_tiles = [t for t in tiles if t[0] in {x0, x0 + 4} or t[1] in {y0, y0 + 4}]
            random.shuffle(edge_tiles)
            for tx, ty in edge_tiles:
                outside_neighbors = [
                    (tx + dx, ty + dy)
                    for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]
                    if self.within_bounds(tx + dx, ty + dy) and (tx + dx, ty + dy) not in tiles
                ]
                if not outside_neighbors:
                    continue
                ox, oy = random.choice(outside_neighbors)
                self.grid[ty][tx] = "SITE"
                if self.grid[oy][ox] == "WALL":
                    self.grid[oy][ox] = "EMPTY"
                break

    def spawn_enemies(self):
        self.enemies = []
        for site_idx, site_tiles in enumerate(self.plant_sites):
            open_tiles = [pos for pos in site_tiles if self.grid[pos[1]][pos[0]] != "WALL"]
            target = open_tiles[0] if open_tiles else site_tiles[0]
            self.enemies.append(
                {"pos": list(target), "hp": 3, "facing": (0, -1), "blinded": 0, "bound": 0, "role": f"site-{site_idx}"}
            )

        corner_pos = [VALORANT_WIDTH - 2, VALORANT_HEIGHT - 2]
        if self.grid[corner_pos[1]][corner_pos[0]] == "WALL":
            self.grid[corner_pos[1]][corner_pos[0]] = "EMPTY"
        self.enemies.append(
            {"pos": corner_pos, "hp": 3, "facing": (-1, 0), "blinded": 0, "bound": 0, "role": "rotator"}
        )

    def render_map(self) -> str:
        rows: list[str] = []
        for y in range(VALORANT_HEIGHT):
            row_icons = []
            for x in range(VALORANT_WIDTH):
                if [x, y] == self.player_pos:
                    row_icons.append(VALORANT_ICONS["PLAYER"])
                    continue
                if any(enemy["hp"] > 0 and enemy["pos"] == [x, y] for enemy in self.enemies):
                    row_icons.append(VALORANT_ICONS["ENEMY"])
                    continue

                tile = self.grid[y][x]
                if [x, y] == self.spike_pos:
                    row_icons.append(VALORANT_ICONS["SPIKE"])
                    continue
                if (x, y) in self.smoke_tiles:
                    row_icons.append(VALORANT_ICONS["SMOKE"])
                elif (x, y) in self.slow_tiles:
                    row_icons.append(VALORANT_ICONS["SLOW"])
                elif tile == "SITE":
                    row_icons.append(VALORANT_ICONS["SITE"])
                else:
                    row_icons.append(VALORANT_ICONS.get(tile, VALORANT_ICONS["EMPTY"]))
            rows.append("".join(row_icons))
        return "\n".join(rows)

    def visibility(self) -> VisibilityUtils:
        return VisibilityUtils(self.grid, self.smoke_tiles, VALORANT_WIDTH, VALORANT_HEIGHT)

    def _enemies_in_range(self) -> list[int]:
        utils = self.visibility()
        indices: list[int] = []
        for idx, enemy in enumerate(self.enemies):
            if enemy["hp"] <= 0:
                continue
            if utils.check_attack_eligibility(self.player_pos, enemy["pos"]):
                indices.append(idx)
        return indices

    def player_can_attack(self) -> bool:
        return bool(self._enemies_in_range())

    def enemy_has_line_on_player(self) -> bool:
        utils = self.visibility()
        return any(utils.has_los(tuple(enemy["pos"]), tuple(self.player_pos)) for enemy in self.enemies if enemy["hp"] > 0)

    def enemy_can_attack(self, enemy: dict[str, Any]) -> bool:
        utils = self.visibility()
        return utils.check_attack_eligibility(enemy["pos"], self.player_pos)

    def apply_damage(self, target: str | int, amount: int) -> str:
        if target == "player":
            self.player_hp = max(0, self.player_hp - amount)
            return f"你受到 {amount} 傷害，剩餘 {self.player_hp} HP。"
        if isinstance(target, int) and 0 <= target < len(self.enemies):
            self.enemies[target]["hp"] = max(0, self.enemies[target]["hp"] - amount)
            return f"🟥 敵人 {target + 1} 受到 {amount} 傷害，剩餘 {self.enemies[target]['hp']} HP。"
        return ""

    def move_player(self, dx: int, dy: int) -> tuple[str, bool]:
        if self.moves_left <= 0:
            return "❌ 本回合移動力已耗盡。", False
        nx, ny = self.player_pos[0] + dx, self.player_pos[1] + dy
        if not self.within_bounds(nx, ny):
            return "❌ 超出地圖邊界。", False
        if self.grid[ny][nx] == "WALL":
            return "❌ 前方有掩體，無法前進。", False
        self.player_pos = [nx, ny]
        if dx or dy:
            self.player_facing = (dx, dy)
        self.moves_left -= 1
        status = "👣 你移動了一步。"
        return status, self.moves_left == 0

    def player_attack(self) -> str:
        if self.attack_used:
            return "❌ 本回合已經攻擊過了。"
        targets = self._enemies_in_range()
        if not targets:
            return "❌ 視線被掩體或煙霧阻擋。"
        target_idx = targets[0]
        self.attack_used = True
        self.moves_left = 0
        self.enemy_defuse_progress = 0
        damage_text = self.apply_damage(target_idx, 2)
        return f"🔫 你開火！{damage_text}"

    def player_attack_target(self, target_idx: int) -> str:
        if self.attack_used:
            return "❌ 本回合已經攻擊過了。"
        if target_idx < 0 or target_idx >= len(self.enemies):
            return "❌ 目標不存在。"
        enemy = self.enemies[target_idx]
        if enemy["hp"] <= 0:
            return "❌ 目標已經倒下。"
        if target_idx not in self._enemies_in_range():
            return "❌ 視線被掩體或煙霧阻擋。"

        self.attack_used = True
        self.moves_left = 0
        self.enemy_defuse_progress = 0
        damage_text = self.apply_damage(target_idx, 2)
        return f"🔫 你開火！{damage_text}"

    def can_plant_here(self) -> bool:
        if self.spike_planted:
            return False
        x, y = self.player_pos
        if not (any((x, y) in site for site in self.plant_sites) and self.grid[y][x] != "WALL"):
            return False
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            nx, ny = x + dx, y + dy
            if self.within_bounds(nx, ny) and self.grid[ny][nx] != "WALL":
                return True
        return False

    def plant_spike(self) -> str:
        if self.spike_planted:
            return "❌ 爆能器已經部署。"
        if not self.can_plant_here():
            return "❌ 只能在綠色下包區域內下包。"
        self.spike_pos = list(self.player_pos)
        self.spike_planted = True
        self.plant_turn = self.turn
        self.grid[self.spike_pos[1]][self.spike_pos[0]] = "SPIKE"
        self.moves_left = 0
        self.attack_used = True
        self.enemy_defuse_progress = 0
        return "💠 成功下包！撐過 10 回合或擊殺敵人即可獲勝。"

    def use_skill(self, name: str, target: tuple[int, int] | None = None) -> str:
        if name not in self.skills:
            return "❌ 你未裝備此技能。"
        if self.skill_charges.get(name, 0) <= 0:
            return "❌ 技能已用盡。"

        msg = ""
        px, py = self.player_pos
        if name == "smoke":
            if target is None:
                return "❌ 請選擇煙霧中心座標。"
            tx, ty = target
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    gx, gy = tx + dx, ty + dy
                    if self.within_bounds(gx, gy) and self.grid[gy][gx] != "WALL":
                        self.smoke_tiles.add((gx, gy))
            msg = "💨 已部署 3x3 煙霧，阻擋視線！"
            self.skill_charges[name] -= 1
        elif name == "flash":
            for enemy in self.enemies:
                if enemy["hp"] > 0:
                    enemy["blinded"] = max(enemy["blinded"], 1)
            msg = "💥 閃光命中！敵人下回合無法攻擊。"
            self.skill_charges[name] -= 1
        elif name == "slow":
            if target is None:
                return "❌ 請選擇緩速中心座標。"
            tx, ty = target
            for dy in range(-2, 4):
                for dx in range(-2, 4):
                    gx, gy = tx + dx, ty + dy
                    if self.within_bounds(gx, gy) and self.grid[gy][gx] != "WALL":
                        self.slow_tiles.add((gx, gy))
            msg = "❄️ 已鋪設 6x6 緩速區域，敵人移速減半。"
            self.skill_charges[name] -= 1
        elif name == "bind":
            for enemy in self.enemies:
                if enemy["hp"] > 0:
                    enemy["bound"] = max(enemy["bound"], 1)
            msg = "⛓️ 束縛成功！敵人下回合無法移動。"
            self.skill_charges[name] -= 1
        elif name == "teleport":
            if target is None:
                return "❌ 請先選擇傳送目標格。"
            tx, ty = target
            if not self.within_bounds(tx, ty):
                return "❌ 傳送目標超出地圖。"
            if abs(tx - px) > 3 or abs(ty - py) > 3:
                return "❌ 目標需位於 6x6 範圍內。"
            occupied = any(enemy["hp"] > 0 and enemy["pos"] == [tx, ty] for enemy in self.enemies)
            if self.grid[ty][tx] == "WALL" or self.grid[ty][tx] == "SPIKE" or (tx, ty) in self.smoke_tiles or occupied:
                return "❌ 目標格不可用。"
            self.player_pos = [tx, ty]
            self.skill_charges[name] -= 1
            msg = "🌀 你選擇位置完成瞬移！"
        return msg

    def enemy_can_see_player(self) -> bool:
        return self.enemy_has_line_on_player()

    def _enemy_step_toward(self, enemy_idx: int, target: list[int], steps: int) -> str:
        enemy = self.enemies[enemy_idx]
        if enemy["hp"] <= 0:
            return "🟥 敵人已被擊倒。"
        if steps <= 0:
            return "🟥 敵人原地觀望。"
        queue: deque[tuple[int, int, list[tuple[int, int]]]] = deque()
        visited = set()
        queue.append((enemy["pos"][0], enemy["pos"][1], []))
        visited.add(tuple(enemy["pos"]))
        found_path: list[tuple[int, int]] | None = None
        while queue:
            x, y, path = queue.popleft()
            if [x, y] == target:
                found_path = path
                break
            for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                nx, ny = x + dx, y + dy
                if not self.within_bounds(nx, ny):
                    continue
                if (nx, ny) in visited:
                    continue
                if self.grid[ny][nx] == "WALL":
                    continue
                visited.add((nx, ny))
                queue.append((nx, ny, path + [(nx, ny)]))

        if not found_path:
            return "🟥 敵人被地形卡住了。"

        path_taken = found_path[:steps]
        if path_taken:
            dx = path_taken[0][0] - enemy["pos"][0]
            dy = path_taken[0][1] - enemy["pos"][1]
            if dx or dy:
                enemy["facing"] = (dx, dy)
            self.enemies[enemy_idx]["pos"] = list(path_taken[-1])
        return "🟥 敵人向目標推進。"

    def enemy_attack(self, log: list[str]):
        if self.player_hp <= 0:
            return
        attacked = False
        for idx, enemy in enumerate(self.enemies):
            if enemy["hp"] <= 0:
                continue
            if enemy["blinded"] > 0:
                continue
            if not self.enemy_can_attack(enemy):
                continue
            attacked = True
            self.enemy_defuse_progress = 0
            self.defusing_enemy = None
            log.append(f"🟥 敵人 {idx + 1} 對你開火！")
            log.append(self.apply_damage("player", 1))
        if not attacked:
            log.append("👀 敵人沒有找到你的身影。")

    def enemy_special(self, log: list[str]):
        alive = [e for e in self.enemies if e["hp"] > 0]
        if not alive:
            return
        caster = alive[0]
        if self.enemy_skill == "molly":
            if self.spike_pos and caster["pos"] == self.spike_pos:
                log.append("🔥 敵人投擲燃燒彈守點，你不敢靠近中心。")
                self.player_hp = max(0, self.player_hp - 1)
                log.append("你被餘焰灼傷 -1 HP！")
        elif self.enemy_skill == "recon":
            if random.random() < 0.4:
                log.append("📡 敵人啟動尋敵箭，暫時無視煙霧。")
                self.smoke_tiles.clear()

    def _site_guard_target(self, enemy: dict[str, Any]) -> list[int]:
        if enemy["role"].startswith("site"):
            idx = int(enemy["role"].split("-")[-1])
            return list(self.site_centers[idx])
        return list(self.site_centers[0] if self.site_centers else [0, 0])

    def resolve_enemy_turn(self, log: list[str]):
        if not self.spike_planted:
            self.enemy_defuse_progress = 0
            self.defusing_enemy = None

        # 保證未下包時至少有一名敵人積極追擊玩家
        chaser_idx: int | None = None
        if not self.spike_planted:
            for idx, enemy in enumerate(self.enemies):
                if enemy["hp"] > 0 and enemy["role"] == "rotator":
                    chaser_idx = idx
                    break
            if chaser_idx is None:
                for idx, enemy in enumerate(self.enemies):
                    if enemy["hp"] > 0:
                        chaser_idx = idx
                        break

        contact = False
        for idx, enemy in enumerate(self.enemies):
            if enemy["hp"] <= 0:
                continue
            on_spike = self.spike_planted and self.spike_pos and enemy["pos"] == self.spike_pos
            if enemy["bound"] > 0:
                log.append(f"⛓️ 敵人 {idx + 1} 被束縛，無法移動。")
                if on_spike and enemy["blinded"] <= 0:
                    if self.enemy_defuse_progress and self.defusing_enemy == idx:
                        self.enemy_defuse_progress += 1
                    else:
                        self.enemy_defuse_progress = 1
                        self.defusing_enemy = idx
                    contact = True
                    log.append(f"💠 敵人正在拆包（{self.enemy_defuse_progress}/2）！")
            else:
                steps = 2
                if tuple(enemy["pos"]) in self.slow_tiles:
                    steps = 1
                target: list[int] = []
                if self.spike_planted and self.spike_pos:
                    target = self.spike_pos
                elif idx == chaser_idx:
                    target = list(self.player_pos)
                elif enemy["role"].startswith("site"):
                    if any(enemy["pos"] == pos for pos in self.plant_sites[int(enemy["role"].split("-")[-1])]):
                        target = enemy["pos"]
                    else:
                        target = self._site_guard_target(enemy)
                else:
                    target = self._site_guard_target(enemy)

                log.append(self._enemy_step_toward(idx, target, steps))
                on_spike = self.spike_planted and self.spike_pos and enemy["pos"] == self.spike_pos
                if on_spike and enemy["blinded"] <= 0:
                    if self.enemy_defuse_progress and self.defusing_enemy == idx:
                        self.enemy_defuse_progress += 1
                    else:
                        self.enemy_defuse_progress = 1
                        self.defusing_enemy = idx
                    contact = True
                    log.append(f"💠 敵人正在拆包（{self.enemy_defuse_progress}/2）！")
                else:
                    if self.defusing_enemy == idx:
                        self.defusing_enemy = None

        if self.spike_planted and not contact:
            self.enemy_defuse_progress = 0
            self.defusing_enemy = None

        self.enemy_attack(log)
        if random.random() < 0.35:
            self.enemy_special(log)

        for enemy in self.enemies:
            if enemy["hp"] <= 0:
                continue
            enemy["blinded"] = max(0, enemy["blinded"] - 1)
            enemy["bound"] = max(0, enemy["bound"] - 1)

    def start_player_turn(self):
        if self.player_hp <= 0:
            self.moves_left = 0
            self.attack_used = True
        else:
            self.moves_left = 3
            self.attack_used = False

    def check_end(self) -> tuple[bool, str | None]:
        alive_enemies = [e for e in self.enemies if e["hp"] > 0]
        if not alive_enemies:
            return True, "🎉 你擊敗敵人，成功保護爆能器！"
        if self.player_hp <= 0 and not self.spike_planted:
            return True, "💀 你倒下了，任務失敗。"
        if not self.spike_planted and self.turn > 20:
            return True, "⏰ 20 回合內未下包，任務失敗。"
        if self.spike_planted and self.plant_turn is not None and self.turn - self.plant_turn >= 10:
            return True, "⏱️ 成功撐過 10 回合，爆能器引爆！"
        if self.enemy_defuse_progress >= 2:
            return True, "💥 敵人成功拆除爆能器，你輸了。"
        return False, None

    async def complete_turn(
        self, log: list[str], update_cb: Callable[[str], Awaitable[None]] | None = None
    ) -> tuple[str, bool, str | None]:
        end, reason = self.check_end()
        if end:
            return clip_status(log), end, reason
        self.resolve_enemy_turn(log)
        if update_cb:
            clipped = clip_status(log)
            await update_cb(clipped)
            log[:] = clipped.split("\n")
        self.turn += 1
        end, reason = self.check_end()
        if not end and self.player_hp <= 0 and self.spike_planted:
            safety_steps = 0
            while not end and safety_steps < 15:
                if not any(enemy["hp"] > 0 for enemy in self.enemies):
                    break
                await asyncio.sleep(5)
                self.resolve_enemy_turn(log)
                if update_cb:
                    clipped = clip_status(log)
                    await update_cb(clipped)
                    log[:] = clipped.split("\n")
                self.turn += 1
                end, reason = self.check_end()
                safety_steps += 1
        if not end:
            self.start_player_turn()
        return clip_status(log), end, reason


def build_valorant_embed(game: ValorantTacticsGame, status_text: str) -> discord.Embed:
    status_text = clip_status(status_text.split("\n"))
    embed = discord.Embed(title="🎯 特戰棋盤：1v3", color=discord.Color.teal())
    embed.description = game.render_map()
    embed.add_field(name="狀態", value=status_text or "--", inline=False)
    plant_status = "未下包"
    if game.spike_planted and game.plant_turn is not None:
        plant_status = f"已下包（經過 {max(0, game.turn - game.plant_turn)} 回合）"
    elif not game.spike_planted:
        plant_status = f"未下包（{max(0, 21 - game.turn)} 回合內必須下包）"
    skill_names = []
    label_map = {
        "smoke": "☁️ 煙霧",
        "flash": "💥 閃光",
        "slow": "❄️ 緩速",
        "bind": "⛓️ 束縛",
        "teleport": "🌀 傳送",
    }
    for skill in game.skills:
        skill_names.append(label_map.get(skill, skill))
    enemy_hp_line = "、".join(
        [f"{idx + 1}:{max(0, enemy['hp'])}HP" for idx, enemy in enumerate(game.enemies)]
    )
    embed.add_field(
        name="資訊",
        value=(
            f"你 {game.player_hp} HP｜敵人存活 {len([e for e in game.enemies if e['hp']>0])}/{len(game.enemies)} ({enemy_hp_line})｜移動力 {game.moves_left} / 3\n"
            f"回合 {game.turn}｜{plant_status}｜技能一次性使用\n"
            f"裝備技能：{', '.join(skill_names)}\n"
            f"視野：{'可直接攻擊' if game.player_can_attack() else '暫時看不到敵人'}"
        ),
        inline=False,
    )
    embed.add_field(
        name="下包區域",
        value="、".join(
            [
                f"({tiles[0][0] + 1}-{tiles[-1][0] + 1}, {tiles[0][1] + 1}-{tiles[-1][1] + 1})"
                for tiles in game.plant_sites
            ]
        )
        if game.plant_sites
        else "--",
        inline=False,
    )
    return embed


class ValorantGameView(View):
    def __init__(self, user: discord.User, game: ValorantTacticsGame, menu_builder: Callable | None = None):
        super().__init__(timeout=420)
        self.author_id = user.id
        self.game = game
        self.menu_builder = menu_builder
        self.ended = False
        self.message: discord.Message | None = None
        self.skill_select = SkillUseSelect(self)
        self.add_item(self.skill_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的遊戲面板！", ephemeral=True)
            return False
        if self.ended:
            return True
        if self.game.player_hp <= 0:
            await interaction.response.send_message("💀 你已倒下，無法再行動，只能等待爆能器結果。", ephemeral=True)
            return False
        return True

    def show_post_game_controls(self) -> None:
        self.clear_items()
        replay_btn = Button(label="再來一次", style=discord.ButtonStyle.primary, emoji="🔁", row=0)
        lobby_btn = Button(label="返回主畫面", style=discord.ButtonStyle.secondary, emoji="🎮", row=0)

        async def replay_callback(interaction: discord.Interaction):
            await self.replay(interaction)

        async def lobby_callback(interaction: discord.Interaction):
            await self.return_to_main(interaction)

        replay_btn.callback = replay_callback
        lobby_btn.callback = lobby_callback
        self.add_item(replay_btn)
        self.add_item(lobby_btn)

    async def replay(self, interaction: discord.Interaction) -> None:
        new_select = ValorantSkillSelectView(interaction.user, self.menu_builder)
        intro = build_valorant_intro_embed()
        await interaction.response.edit_message(embed=intro, view=new_select)
        self.stop()

    async def return_to_main(self, interaction: discord.Interaction) -> None:
        if self.menu_builder is None:
            await interaction.response.send_message("❌ 目前無法返回主畫面，請重新使用 /opengame。", ephemeral=True)
            return
        menu_payload = self.menu_builder(interaction.user)
        await interaction.response.edit_message(embed=menu_payload.get("embed"), view=menu_payload.get("view"))
        self.stop()

    async def finalize(self, interaction: discord.Interaction, reason: str):
        self.ended = True
        self.show_post_game_controls()
        embed = build_valorant_embed(self.game, reason)
        if interaction.response.is_done():
            if self.message:
                await interaction.followup.edit_message(message_id=self.message.id, embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    async def resolve_action(self, interaction: discord.Interaction, log: list[str], consume_turn: bool):
        if not interaction.response.is_done():
            await interaction.response.defer()

        status_preview = "\n".join(log)
        if status_preview.startswith("❌"):
            consume_turn = False
        else:
            if self.game.player_can_attack():
                log.append("🎯 你已鎖定敵人，隨時可以攻擊！")
        if consume_turn:
            status_text, ended, reason = await self.game.complete_turn(log, self.live_refresh)
        else:
            status_text = clip_status(log)
            ended, reason = self.game.check_end()

        if ended:
            await self.finalize(interaction, reason or status_text)
            return

        embed = build_valorant_embed(self.game, status_text)
        if interaction.response.is_done():
            if self.message:
                await interaction.followup.edit_message(message_id=self.message.id, embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    async def live_refresh(self, status_text: str):
        embed = build_valorant_embed(self.game, status_text)
        if self.message:
            await self.message.edit(embed=embed, view=self)

    @discord.ui.button(label="⬆️", style=discord.ButtonStyle.secondary, row=0)
    async def move_up(self, interaction: discord.Interaction, button: Button):
        status, end_turn = self.game.move_player(0, -1)
        await self.resolve_action(interaction, [status], end_turn)

    @discord.ui.button(label="⬇️", style=discord.ButtonStyle.secondary, row=0)
    async def move_down(self, interaction: discord.Interaction, button: Button):
        status, end_turn = self.game.move_player(0, 1)
        await self.resolve_action(interaction, [status], end_turn)

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def move_left(self, interaction: discord.Interaction, button: Button):
        status, end_turn = self.game.move_player(-1, 0)
        await self.resolve_action(interaction, [status], end_turn)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary, row=1)
    async def move_right(self, interaction: discord.Interaction, button: Button):
        status, end_turn = self.game.move_player(1, 0)
        await self.resolve_action(interaction, [status], end_turn)

    @discord.ui.button(label="攻擊", style=discord.ButtonStyle.danger, row=2)
    async def attack(self, interaction: discord.Interaction, button: Button):
        targets = self.game._enemies_in_range()
        if not targets:
            await interaction.response.send_message("❌ 視線被掩體或煙霧阻擋，沒有可攻擊的敵人。", ephemeral=True)
            return
        picker = AttackTargetPicker(self, targets)
        await interaction.response.send_message("🎯 選擇要攻擊的敵人 (x,y)", view=picker, ephemeral=True)

    @discord.ui.button(label="💠 下包", style=discord.ButtonStyle.success, row=2)
    async def plant(self, interaction: discord.Interaction, button: Button):
        status = self.game.plant_spike()
        await self.resolve_action(interaction, [status], not status.startswith("❌"))

    @discord.ui.button(label="⏭️ 結束回合", style=discord.ButtonStyle.secondary, row=3)
    async def end_turn(self, interaction: discord.Interaction, button: Button):
        status = "⏭️ 你結束了本回合。"
        self.game.moves_left = 0
        self.game.attack_used = True
        await self.resolve_action(interaction, [status], True)
    @classmethod
    def build(cls, user: discord.User, game: ValorantTacticsGame, menu_builder: Callable | None = None):
        return cls(user, game, menu_builder)


class AttackTargetPicker(View):
    def __init__(self, parent: ValorantGameView, targets: list[int]):
        super().__init__(timeout=20)
        self.parent_view = parent
        self.author_id = parent.author_id
        self.add_item(AttackTargetSelect(self, targets))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 這不是你的遊戲。", ephemeral=True)
            return False
        if self.parent_view.game.player_hp <= 0:
            await interaction.response.send_message("💀 你已倒下，無法攻擊。", ephemeral=True)
            return False
        return True

    async def handle_selection(self, interaction: discord.Interaction, target_idx: int):
        await interaction.response.defer(ephemeral=True, thinking=False)
        status = self.parent_view.game.player_attack_target(target_idx)
        await self.parent_view.resolve_action(interaction, [status], not status.startswith("❌"))

        for child in self.children:
            child.disabled = True
        if interaction.message:
            await interaction.followup.edit_message(
                message_id=interaction.message.id,
                content="✅ 攻擊目標已選擇。",
                view=self,
            )
        self.stop()


class AttackTargetSelect(discord.ui.Select):
    def __init__(self, picker: AttackTargetPicker, targets: list[int]):
        self.picker = picker
        options: list[discord.SelectOption] = []
        for idx in targets:
            enemy = picker.parent_view.game.enemies[idx]
            ex, ey = enemy["pos"]
            options.append(
                discord.SelectOption(
                    label=f"敵人 {idx + 1}",
                    description=f"座標 ({ex + 1}, {ey + 1})",
                    value=str(idx),
                )
            )
        super().__init__(placeholder="選擇攻擊目標", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await self.picker.handle_selection(interaction, int(self.values[0]))


class AreaSkillModal(Modal):
    def __init__(self, view: ValorantGameView, skill_name: str):
        title_map = {
            "teleport": "🌀 選擇傳送座標 (x,y)",
            "smoke": "☁️ 煙霧中心座標 (x,y)",
            "slow": "❄️ 緩速中心座標 (x,y)",
        }
        super().__init__(title=title_map.get(skill_name, "技能座標"))
        self.view_ref = view
        self.skill_name = skill_name
        placeholder = "例如：8,7 (x=1-15, y=1-13)"
        self.coord = TextInput(label="目標座標", placeholder=placeholder, required=True, max_length=12)
        self.add_item(self.coord)

    async def on_submit(self, interaction: discord.Interaction):
        view = self.view_ref
        if interaction.user.id != view.author_id:
            await interaction.response.send_message("❌ 這不是你的遊戲。", ephemeral=True)
            return
        raw = self.coord.value.replace("，", ",")
        try:
            x_str, y_str = raw.split(",", 1)
            tx, ty = int(x_str.strip()) - 1, int(y_str.strip()) - 1
        except ValueError:
            await interaction.response.send_message("❌ 請輸入有效的 x,y。", ephemeral=True)
            return

        status = view.game.use_skill(self.skill_name, (tx, ty))
        view.skill_select.refresh()
        await view.resolve_action(interaction, [status], False)


class SkillUseSelect(discord.ui.Select):
    def __init__(self, view: ValorantGameView):
        self.view_ref = view
        super().__init__(
            placeholder="🎒 使用道具/技能",
            min_values=1,
            max_values=1,
            options=self._build_options(),
            row=4,
        )

    def _build_options(self) -> list[discord.SelectOption]:
        mapping = {
            "smoke": ("☁️ 煙霧", "任意 3x3 阻擋視線"),
            "flash": ("💥 閃光", "敵人下回合無法攻擊"),
            "slow": ("❄️ 緩速", "任意 6x6 減速"),
            "bind": ("⛓️ 束縛", "敵人下回合無法移動"),
            "teleport": ("🌀 傳送", "6x6 範圍選點")
        }
        options: list[discord.SelectOption] = []
        for skill in self.view_ref.game.skills:
            emoji, desc = mapping.get(skill, (skill, ""))
            charges = self.view_ref.game.skill_charges.get(skill, 0)
            options.append(
                discord.SelectOption(
                    label=f"{emoji} (剩 {charges})",
                    value=skill,
                    description=desc,
                    emoji=emoji[0] if emoji and emoji[0] != skill else None,
                )
            )
        return options

    def refresh(self):
        self.options = self._build_options()

    async def callback(self, interaction: discord.Interaction):
        view = self.view_ref
        if interaction.user.id != view.author_id:
            await interaction.response.send_message("❌ 這不是你的遊戲。", ephemeral=True)
            return
        skill_name = self.values[0]
        if view.game.skill_charges.get(skill_name, 0) <= 0:
            await interaction.response.send_message("❌ 此技能已用完。", ephemeral=True)
            return
        if skill_name in {"teleport", "smoke", "slow"}:
            await interaction.response.send_modal(AreaSkillModal(view, skill_name))
            return
        result = view.game.use_skill(skill_name)
        self.refresh()
        await view.resolve_action(interaction, [result], False)


def build_valorant_intro_embed() -> discord.Embed:
    intro = discord.Embed(
        title="🎯 特戰棋盤：1v3",
        description=(
            "15x13 戰術棋盤，選擇 3 個技能後與三名電腦對戰。\n"
            "兩名敵人防守兩個下包點，右下還有一名支援。勝利：擊殺全部或下包後撐 10 回合；"
            "失敗：未下包超過 20 回合或爆能器遭拆除（你倒下後仍可等待爆炸/拆除結果）。"
        ),
        color=discord.Color.teal(),
    )
    intro.add_field(
        name="圖例",
        value="⬜ 地面｜⬛ 掩體｜🟦 你｜🟥 敵人｜💠 爆能器｜☁️ 煙霧｜❄️ 緩速",
        inline=False,
    )
    intro.add_field(
        name="技能",
        value="煙霧阻擋視線｜閃光讓敵人下回合無法攻擊｜緩速 6x6 減速｜束縛讓敵人無法移動｜傳送可在 6x6 內選點位移（技能一次性）",
        inline=False,
    )
    return intro


class ValorantSkillSelectView(View):
    def __init__(self, user: discord.User, menu_builder: Callable | None = None):
        super().__init__(timeout=180)
        self.author_id = user.id
        self.menu_builder = menu_builder

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ 請不要操作別人的技能配置。", ephemeral=True)
            return False
        return True

    @discord.ui.select(
        placeholder="選擇 3 個戰術技能...",
        min_values=3,
        max_values=3,
        options=[
            discord.SelectOption(label="☁️ 煙霧彈", value="smoke", description="任意位置 3x3 阻擋視線"),
            discord.SelectOption(label="💥 閃光彈", value="flash", description="敵人下回合無法攻擊"),
            discord.SelectOption(label="❄️ 緩速球", value="slow", description="任意位置 6x6 區域減速"),
            discord.SelectOption(label="⛓️ 束縛", value="bind", description="敵人下回合無法移動"),
            discord.SelectOption(label="🌀 傳送", value="teleport", description="選點傳送 6x6 範圍"),
        ],
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        game = ValorantTacticsGame(list(select.values))
        view = ValorantGameView.build(interaction.user, game, self.menu_builder)
        embed = build_valorant_embed(game, "✅ 技能已配置，開始行動！")
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()
