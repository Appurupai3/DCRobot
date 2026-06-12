from __future__ import annotations

import random

from dcrbot.battle import BattleMatch


def score_greedy_roll(rolls: list[int]) -> tuple[int, int, int]:
    """Return gained score, scoring dice count, and multiplier placeholder for a greedy dice roll."""

    add_values = {1: 100, 5: 50}
    counts = {i: rolls.count(i) for i in range(1, 7)}

    add_sum = sum(add_values.get(face, 0) * count for face, count in counts.items())

    set_bonus = 0
    scoring_dice = sum(count for face, count in counts.items() if add_values.get(face, 0) > 0)

    for face, count in counts.items():
        if count >= 3:
            if count == 3:
                set_bonus += 300
            elif count == 4:
                set_bonus += 500
            elif count == 5:
                set_bonus += 1500
            elif count >= 6:
                set_bonus += 3000
            scoring_dice += count if face not in add_values else 0

    gained = add_sum + set_bonus

    return gained, scoring_dice, 1


def resolve_random_contest(match: BattleMatch) -> tuple[list[int], str]:
    scores = {}
    higher_is_better = True
    details = []
    target_score = 3000 if match.game_key == "dice_duel" else None

    for uid in match.participants:
        if match.game_key == "dice_duel":
            total = 0
            dice_pool = 6
            steps = []

            while True:
                roll = [random.randint(1, 6) for _ in range(dice_pool)]
                gained, scoring_dice, multiplier = score_greedy_roll(roll)

                if gained == 0:
                    steps.append(
                        f"第 {len(steps) + 1} 擲 {roll} → 無得分，爆掉本回合！總分歸零。"
                    )
                    total = 0
                    break

                total += gained
                steps.append(
                    f"第 {len(steps) + 1} 擲 {roll} → +{gained} 分，累積 {total} 分。"
                )

                if target_score and total >= target_score:
                    steps.append(f"衝破 {target_score} 分門檻，收分等待結算。")
                    break

                remaining = dice_pool - scoring_dice
                dice_pool = 6 if remaining == 0 else max(remaining, 1)
                risk_tolerance = 0.6 if total < 3500 else 0.4
                if random.random() > risk_tolerance:
                    steps.append("見好就收，結束回合。")
                    break

            scores[uid] = total
            detail_block = "\n".join([f"<@{uid}> 貪婪骰總分 {total}:"] + steps)
            details.append(detail_block)
        elif match.game_key == "archery":
            scores = {pid: 3 for pid in match.participants}
            order = match.participants.copy()
            random.shuffle(order)
            chamber = [True] * 3 + [False] * 2
            random.shuffle(chamber)
            turn_idx = 0
            logs: list[str] = []
            while len([pid for pid, hp in scores.items() if hp > 0]) > 1 and chamber:
                shooter = order[turn_idx % len(order)]
                turn_idx += 1
                if scores[shooter] <= 0:
                    continue
                self_shot = random.random() < 0.35
                target_candidates = [pid for pid in order if pid != shooter and scores[pid] > 0]
                if not target_candidates:
                    target_candidates = [pid for pid in order if pid != shooter]
                target = shooter if self_shot else random.choice(target_candidates)
                live = chamber.pop(0)
                damage = 2 if random.random() < 0.4 else 1
                if live:
                    scores[target] = max(0, scores[target] - damage)
                    logs.append(
                        f"<@{shooter}> 射向 {'自己' if self_shot else '<@'+str(target)+'>'} 實彈，造成 {damage} 傷害"
                    )
                else:
                    extra = " 並獲得加行動" if self_shot else ""
                    logs.append(f"<@{shooter}> {'自射' if self_shot else '射擊'}空包彈{extra}")
                    if self_shot:
                        turn_idx -= 1

            best_hp = max(scores.values()) if scores else 0
            winners = [pid for pid, hp in scores.items() if hp == best_hp]
            details.append("\n".join(["命運左輪模擬："] + logs))
            return winners, "\n".join(details)
        elif match.game_key == "cookoff":
            taste = random.randint(1, 10)
            creative = random.randint(1, 10)
            score = taste + creative
            scores[uid] = score
            details.append(f"<@{uid}> 味覺 {taste} + 創意 {creative} = {score}")
        elif match.game_key == "quiz":
            score = random.randint(40, 100)
            scores[uid] = score
            details.append(f"<@{uid}> 搶答速度 {score}")
        elif match.game_key == "sprint":
            reaction = random.uniform(0.05, 0.3)
            sprint_speed = random.uniform(8.5, 11.5)
            finish = sprint_speed + reaction
            higher_is_better = False
            scores[uid] = finish
            details.append(f"<@{uid}> 完賽 {finish:.2f}s (反應 {reaction:.2f}s)")
        elif match.game_key == "space":
            quality = random.uniform(50, 100)
            fuel = random.uniform(1.0, 5.0)
            distance = quality * fuel
            scores[uid] = distance
            details.append(f"<@{uid}> 航程 {distance:.1f} 單位 (品質 {quality:.1f}, 燃料 {fuel:.2f})")

    if not scores:
        return [], "沒有有效的參與者。"

    comparator = max if higher_is_better else min
    if match.game_key == "dice_duel" and target_score:
        qualified = [val for val in scores.values() if val >= target_score]
        if qualified:
            best_value = max(qualified)
        else:
            best_value = comparator(scores.values())
    else:
        best_value = comparator(scores.values())

    winners = [uid for uid, val in scores.items() if val == best_value]

    return winners, "\n".join(details)
