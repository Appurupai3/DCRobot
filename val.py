import random
import math
import os
import sys

# === ANSI 顏色代碼 (背景色) ===
class Colors:
    RESET = "\033[0m"
    BG_BLUE = "\033[44m"    # 藍色背景 (可攻擊區域)
    BG_RED = "\033[41m"     # 紅色背景 (備用)

# === 跨平台按鍵讀取工具 ===
class _Getch:
    def __init__(self):
        try:
            self.impl = _GetchWindows()
        except ImportError:
            self.impl = _GetchUnix()
    def __call__(self): return self.impl()

class _GetchUnix:
    def __init__(self): import tty, sys
    def __call__(self):
        import sys, tty, termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

class _GetchWindows:
    def __init__(self): import msvcrt
    def __call__(self): import msvcrt; return msvcrt.getwch()

get_key = _Getch()

# === 常數設定 ===
VALORANT_WIDTH = 15
VALORANT_HEIGHT = 13
VALORANT_ICONS = {
    "EMPTY": "⬜", "WALL": "⬛", "PLAYER": "🟦", "ENEMY": "🟥",
    "SPIKE": "💠", "SITE": "🟩", "SMOKE": "☁️", "SLOW": "❄️",
}

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

# === 視野工具 ===
class VisibilityUtils:
    def __init__(self, grid, smoke_tiles, width, height):
        self.grid = grid; self.smoke_tiles = smoke_tiles; self.width = width; self.height = height

    def within_bounds(self, x, y): return 0 <= x < self.width and 0 <= y < self.height
    def get_distance(self, p1, p2): return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def get_line_points(self, p1, p2):
        x1, y1 = p1; x2, y2 = p2; points = []
        dx = abs(x2 - x1); dy = abs(y2 - y1)
        sx = 1 if x1 < x2 else -1; sy = 1 if y1 < y2 else -1
        err = dx - dy
        while True:
            points.append((x1, y1))
            if x1 == x2 and y1 == y2: break
            e2 = 2 * err
            if e2 > -dy: err -= dy; x1 += sx
            if e2 < dx: err += dx; y1 += sy
        return points

    def has_los(self, start, end):
        line_points = self.get_line_points(start, end)
        if len(line_points) > 2:
            for px, py in line_points[1:-1]:
                if not self.within_bounds(px, py): return False
                # 視線會被牆壁或煙霧阻擋
                if self.grid[py][px] == "WALL" or (px, py) in self.smoke_tiles: return False
        return True

    def check_attack_eligibility(self, attacker_pos, target_pos):
        dist = self.get_distance(attacker_pos, target_pos)
        # 1.5格內無視障礙(近戰/穿牆)，否則需視線
        if dist <= 1.5: return True
        return self.has_los(attacker_pos, target_pos)

# === 遊戲核心邏輯 ===
class ValorantTacticsGame:
    def __init__(self, skills):
        self.grid = [["EMPTY" for _ in range(VALORANT_WIDTH)] for _ in range(VALORANT_HEIGHT)]
        self.player_pos = [1, 1]
        self.spike_pos = None; self.spike_planted = False; self.plant_turn = None
        self.plant_sites = []; self.site_centers = []
        self.player_hp = 4
        self.enemies = []
        self.turn = 1; self.moves_left = 3; self.attack_used = False
        self.enemy_defuse_progress = 0
        self.smoke_tiles = set(); self.slow_tiles = set()
        self.skills = skills
        self.skill_charges = {name: 1 for name in ["smoke", "flash", "slow", "bind", "teleport"]}
        self.enemy_skill = random.choice(["molly", "recon"])
        self.generate_map()
        self.start_player_turn()

    def generate_map(self):
        self.generate_plant_sites(); self.spawn_enemies()
        wall_count = random.randint(20, 30)
        forbidden = {tuple(self.player_pos)} | {tuple(e["pos"]) for e in self.enemies}
        for _ in range(wall_count):
            rx, ry = random.randint(0, VALORANT_WIDTH - 1), random.randint(0, VALORANT_HEIGHT - 1)
            if (rx, ry) in forbidden: continue
            self.grid[ry][rx] = "WALL"
        self.ensure_paths()

    def ensure_paths(self):
        def is_walkable(x, y): return self.grid[y][x] != "WALL"
        def reachable():
            seen = set(); q = [tuple(self.player_pos)]; seen.add(tuple(self.player_pos))
            while q:
                cx, cy = q.pop(0)
                for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    nx, ny = cx + dx, cy + dy
                    if not self.within_bounds(nx, ny): continue
                    if (nx, ny) in seen or not is_walkable(nx, ny): continue
                    seen.add((nx, ny))
                    q.append((nx, ny))
            return seen
        targets = list(self.site_centers)
        for _ in range(300):
            seen = reachable()
            missing = [t for t in targets if t not in seen]
            if not missing: break
            frontier = []
            for cx, cy in seen:
                for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    nx, ny = cx + dx, cy + dy
                    if self.within_bounds(nx, ny) and self.grid[ny][nx] == "WALL": frontier.append((nx, ny))
            if not frontier: break
            target = random.choice(missing)
            best = min(frontier, key=lambda p: abs(p[0]-target[0]) + abs(p[1]-target[1]))
            self.grid[best[1]][best[0]] = "EMPTY"

    def within_bounds(self, x, y): return 0 <= x < VALORANT_WIDTH and 0 <= y < VALORANT_HEIGHT

    def generate_plant_sites(self):
        def random_site(): return random.randint(0, VALORANT_WIDTH - 5), random.randint(0, VALORANT_HEIGHT - 5)
        first = random_site(); 
        while True:
            second = random_site()
            if abs((first[0]+2)-(second[0]+2)) + abs((first[1]+2)-(second[1]+2)) >= 5: break
        for top_left in [first, second]:
            tiles = []; x0, y0 = top_left
            for dy in range(5):
                for dx in range(5): tiles.append((x0+dx, y0+dy))
            self.plant_sites.append(list(tiles)); self.site_centers.append((x0+2, y0+2))
            for tx, ty in tiles:
                if (tx, ty) != tuple(self.player_pos): self.grid[ty][tx] = "SITE"
            rock_count = random.randint(6, 14); tiles_copy = tiles[:]; random.shuffle(tiles_copy); rocks = 0
            for tx, ty in tiles_copy:
                if rocks >= rock_count: break
                if (tx, ty) == tuple(self.player_pos): continue
                self.grid[ty][tx] = "WALL"; rocks += 1
            edge_tiles = [t for t in tiles if t[0] in {x0, x0+4} or t[1] in {y0, y0+4}]
            random.shuffle(edge_tiles)
            for tx, ty in edge_tiles:
                neighbors = [(tx+dx, ty+dy) for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)]]
                outside = [n for n in neighbors if self.within_bounds(*n) and n not in tiles]
                if outside:
                    ox, oy = random.choice(outside)
                    self.grid[ty][tx] = "SITE"
                    if self.grid[oy][ox] == "WALL": self.grid[oy][ox] = "EMPTY"
                    break

    def spawn_enemies(self):
        self.enemies = []
        for site_idx, site_tiles in enumerate(self.plant_sites):
            open_tiles = [pos for pos in site_tiles if self.grid[pos[1]][pos[0]] != "WALL"]
            target = open_tiles[0] if open_tiles else site_tiles[0]
            self.enemies.append({"pos": list(target), "hp": 3, "blinded": 0, "bound": 0})
        corner = [VALORANT_WIDTH-2, VALORANT_HEIGHT-2]
        if self.grid[corner[1]][corner[0]] == "WALL": self.grid[corner[1]][corner[0]] = "EMPTY"
        self.enemies.append({"pos": corner, "hp": 3, "blinded": 0, "bound": 0})

    def render_map(self, highlights=None):
        if highlights is None: highlights = set()
        else: highlights = set(highlights)

        rows = []
        rows.append("   " + "".join([f"{x%10} " for x in range(VALORANT_WIDTH)]))
        for y in range(VALORANT_HEIGHT):
            row_icons = [f"{y:<2} "]
            for x in range(VALORANT_WIDTH):
                icon = None
                if [x, y] == self.player_pos: icon = VALORANT_ICONS["PLAYER"]
                else:
                    enemy_here = False
                    for e in self.enemies:
                        if e["hp"] > 0 and e["pos"] == [x, y]: 
                            icon = VALORANT_ICONS["ENEMY"]; enemy_here = True; break
                    if not enemy_here:
                        tile = self.grid[y][x]
                        if [x, y] == self.spike_pos: icon = VALORANT_ICONS["SPIKE"]
                        elif (x, y) in self.smoke_tiles: icon = VALORANT_ICONS["SMOKE"]
                        elif (x, y) in self.slow_tiles: icon = VALORANT_ICONS["SLOW"]
                        elif tile == "SITE": icon = VALORANT_ICONS["SITE"]
                        else: icon = VALORANT_ICONS.get(tile, VALORANT_ICONS["EMPTY"])

                # 如果該座標在高亮清單中，加上藍色背景
                if (x, y) in highlights:
                    row_icons.append(f"{Colors.BG_BLUE}{icon}{Colors.RESET}")
                else:
                    row_icons.append(icon)
            rows.append("".join(row_icons))
        return "\n".join(rows)

    def visibility(self): return VisibilityUtils(self.grid, self.smoke_tiles, VALORANT_WIDTH, VALORANT_HEIGHT)

    def apply_damage(self, target, amount):
        if target == "player":
            self.player_hp = max(0, self.player_hp - amount)
            return f"你受到 {amount} 傷害，剩餘 {self.player_hp} HP。"
        if isinstance(target, int) and 0 <= target < len(self.enemies):
            self.enemies[target]["hp"] = max(0, self.enemies[target]["hp"] - amount)
            return f"敵人 {target + 1} 受到 {amount} 傷害，剩餘 {self.enemies[target]['hp']} HP。"
        return ""

    def enemies_in_range(self):
        utils = self.visibility()
        indices = []
        for idx, enemy in enumerate(self.enemies):
            if enemy["hp"] <= 0: continue
            if utils.check_attack_eligibility(self.player_pos, enemy["pos"]): indices.append(idx)
        return indices

    def player_attack_target(self, target_idx):
        if self.attack_used: return "❌ 本回合已攻擊。"
        if target_idx not in self.enemies_in_range(): return "❌ 無法攻擊該目標 (無視野)。"
        self.attack_used = True; self.moves_left = 0; self.enemy_defuse_progress = 0
        base_damage = 2
        return f"🔫 開火！" + self.apply_damage(target_idx, base_damage)

    def move_player(self, dx, dy):
        if self.moves_left <= 0: return "❌ 移動力耗盡。"
        nx, ny = self.player_pos[0] + dx, self.player_pos[1] + dy
        if not self.within_bounds(nx, ny): return "❌ 撞牆。"
        if self.grid[ny][nx] == "WALL": return "❌ 撞牆。"
        self.player_pos = [nx, ny]; self.moves_left -= 1
        return "👣 移動一步。"

    def plant_spike(self):
        if self.spike_planted: return "❌ 已下包。"
        x, y = self.player_pos
        in_site = any((x, y) in site for site in self.plant_sites) and self.grid[y][x] != "WALL"
        has_space = any(self.within_bounds(x+dx, y+dy) and self.grid[y+dy][x+dx] != "WALL" for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)])
        if not (in_site and has_space): return "❌ 必須在綠色據點下包。"
        self.spike_pos = list(self.player_pos); self.spike_planted = True; self.plant_turn = self.turn
        self.grid[y][x] = "SPIKE"; self.moves_left = 0; self.attack_used = True; self.enemy_defuse_progress = 0
        return "💠 下包成功！"

    def use_skill(self, name, target=None):
        if self.skill_charges.get(name, 0) <= 0: return "❌ 技能用盡。"
        self.skill_charges[name] -= 1
        if name == "smoke":
            tx, ty = target
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    if self.within_bounds(tx+dx, ty+dy) and self.grid[ty+dy][tx+dx] != "WALL":
                        self.smoke_tiles.add((tx+dx, ty+dy))
            return "💨 煙霧彈部署。"
        elif name == "flash":
            for e in self.enemies: e["blinded"] = 1
            return "💥 全體致盲。"
        elif name == "slow":
            tx, ty = target
            for dy in range(-2, 4):
                for dx in range(-2, 4):
                    if self.within_bounds(tx+dx, ty+dy) and self.grid[ty+dy][tx+dx] != "WALL":
                        self.slow_tiles.add((tx+dx, ty+dy))
            return "❄️ 緩速場部署。"
        elif name == "bind":
            for e in self.enemies: e["bound"] = 1
            return "⛓️ 束縛敵人。"
        elif name == "teleport":
            self.player_pos = list(target)
            return "🌀 傳送成功。"
        return "❌ 技能錯誤。"

    def resolve_enemy_turn(self, log):
        if random.random() < 0.35 and self.enemy_skill == "recon":
            log.append("📡 敵人啟動尋敵箭，清除煙霧！"); self.smoke_tiles.clear()
        for idx, enemy in enumerate(self.enemies):
            if enemy["hp"] <= 0: continue
            if enemy["blinded"] > 0: enemy["blinded"] -= 1; continue
            if enemy["bound"] > 0: enemy["bound"] -= 1; continue
            target = self.spike_pos if self.spike_planted else self.player_pos
            if not target: target = self.player_pos
            dx = target[0] - enemy["pos"][0]; dy = target[1] - enemy["pos"][1]
            mx = 1 if dx > 0 else -1 if dx < 0 else 0; my = 1 if dy > 0 else -1 if dy < 0 else 0
            nx, ny = enemy["pos"][0] + mx, enemy["pos"][1] + my
            if self.within_bounds(nx, ny) and self.grid[ny][nx] != "WALL": enemy["pos"] = [nx, ny]
            utils = self.visibility()
            if utils.check_attack_eligibility(enemy["pos"], self.player_pos):
                log.append(f"🟥 敵人 {idx+1} 看見你了！"); log.append(self.apply_damage("player", 1))
            if self.spike_planted and enemy["pos"] == self.spike_pos:
                self.enemy_defuse_progress += 1; log.append(f"💠 敵人 {idx+1} 正在拆包 ({self.enemy_defuse_progress}/2)！")

    def check_end(self):
        alive = [e for e in self.enemies if e["hp"] > 0]
        if not alive: return True, "🎉 殲滅敵人，勝利！"
        if self.player_hp <= 0 and not self.spike_planted: return True, "💀 你死了，失敗。"
        if not self.spike_planted and self.turn > 20: return True, "⏰ 時間到，防守方勝利。"
        if self.spike_planted and self.turn - self.plant_turn >= 10: return True, "⏱️ 炸彈引爆，勝利！"
        if self.enemy_defuse_progress >= 2: return True, "💥 炸彈被拆除，失敗。"
        return False, None

    def end_turn(self):
        log = []; self.resolve_enemy_turn(log); self.turn += 1
        end, reason = self.check_end()
        if not end: self.start_player_turn()
        return log, end, reason
    
    def start_player_turn(self):
        self.moves_left = 3; self.attack_used = False

# === 終端機介面 (CLI) 重寫版 ===

def draw_interface(game, logs, extra_prompt="", highlights=None):
    clear_screen()
    print(f"=== 回合 {game.turn} ===")
    print(game.render_map(highlights=highlights))
    print("-" * 30)
    alive_enemies = len([e for e in game.enemies if e['hp'] > 0])
    print(f"HP: {game.player_hp} | AP: {game.moves_left}/3 | 剩餘敵人: {alive_enemies}")
    plant_status = "未下包"
    if game.spike_planted:
        plant_status = f"已下包 (爆炸倒數 {10 - (game.turn - game.plant_turn)})"
    print(f"狀態: {plant_status}")
    print("\n[戰況紀錄]")
    for l in logs[-5:]: print(f"> {l}")
    print("-" * 30)
    print("【操作】[W/A/S/D]移動  [F]攻擊  [K]技能  [P]下包  [N]結束回合  [Q]退出")
    if extra_prompt:
        print(f"\n👉 {extra_prompt}")

def get_coordinates_input():
    try:
        x_str = input("輸入 X 座標 (0-14): ")
        y_str = input("輸入 Y 座標 (0-12): ")
        return int(x_str), int(y_str)
    except: return None

def main():
    print("歡迎來到 特戰棋盤 CLI 版 (按鍵版)")
    print("請輸入 3 個技能 (smoke, flash, slow, bind, teleport)")
    print("直接按 Enter 使用預設: smoke flash slow")
    
    raw_skills = input("技能 > ").strip().split()
    if len(raw_skills) < 3: skills = ["smoke", "flash", "slow"]
    else: skills = raw_skills[:3]

    game = ValorantTacticsGame(skills)
    logs = ["遊戲開始！按鍵操作生效。"]

    while True:
        draw_interface(game, logs)
        
        end, reason = game.check_end()
        if end:
            print(f"\n{reason}")
            break

        key = get_key().lower()
        result = ""
        
        if key == 'w': result = game.move_player(0, -1)
        elif key == 's': result = game.move_player(0, 1)
        elif key == 'a': result = game.move_player(-1, 0)
        elif key == 'd': result = game.move_player(1, 0)
        
        # --- 攻擊 (修改重點：掃描全圖高亮) ---
        elif key == 'f':
            # 1. 計算全圖所有可被攻擊的格子 (包含敵人、空地、牆壁等)
            attackable_tiles = []
            utils = game.visibility()
            for y in range(VALORANT_HEIGHT):
                for x in range(VALORANT_WIDTH):
                    # 檢查該座標是否可被玩家攻擊 (符合距離或 LOS)
                    if utils.check_attack_eligibility(game.player_pos, [x, y]):
                        attackable_tiles.append((x, y))
            
            # 2. 獲取可攻擊的敵人資訊 (用於提示玩家輸入)
            valid_targets = game.enemies_in_range()
            target_info = []
            for i in valid_targets:
                enemy = game.enemies[i]
                target_info.append(f"{i+1}:敵人(HP:{enemy['hp']})")
            
            # 3. 繪製介面：傳入 attackable_tiles 讓全圖藍色高亮
            if not valid_targets:
                # 雖然視野內沒敵人，但還是顯示藍色格子讓玩家知道視野範圍
                prompt = "視野範圍內無敵人 (按任意鍵取消)"
                draw_interface(game, logs, extra_prompt=prompt, highlights=attackable_tiles)
                get_key() # 暫停
                continue
            else:
                prompt = f"選擇攻擊目標 (輸入數字 1, 2, 3...): [{' '.join(target_info)}]"
                draw_interface(game, logs, extra_prompt=prompt, highlights=attackable_tiles)
                
                target_key = get_key()
                if target_key.isdigit():
                    idx = int(target_key) - 1
                    result = game.player_attack_target(idx)
                    if not result.startswith("❌"):
                        logs.append(result)
                        turn_logs, end, reason = game.end_turn()
                        logs.extend(turn_logs)
                else:
                    logs.append("❌ 取消攻擊")

        elif key == 'p':
            result = game.plant_spike()
            if not result.startswith("❌"): logs.append(result)
            else: logs.append(result)

        elif key == 'k':
            draw_interface(game, logs, "選擇技能: [S]moke [F]lash [L]slow [B]ind [T]eleport")
            skill_key = get_key().lower()
            skill_map = {'s': 'smoke', 'f': 'flash', 'l': 'slow', 'b': 'bind', 't': 'teleport'}
            
            if skill_key in skill_map:
                skill_name = skill_map[skill_key]
                target = None
                if skill_name in ["smoke", "slow", "teleport"]:
                    print(f"\n技能 {skill_name} 需要座標:")
                    target = get_coordinates_input()
                    if not target:
                        logs.append("❌ 座標輸入錯誤")
                        continue
                result = game.use_skill(skill_name, target)
                logs.append(result)
            else:
                logs.append("❌ 無效的技能按鍵")

        elif key == 'n':
            turn_logs, end, reason = game.end_turn()
            logs.extend(turn_logs)
            result = "回合結束。"

        elif key == 'q':
            print("\n遊戲退出。")
            break

        if result and not result.startswith("❌") and key not in ['n', 'f']:
            pass
        elif result:
            logs.append(result)

if __name__ == "__main__":
    main()