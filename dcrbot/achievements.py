"""Achievement catalogue and Discord UI for economy games."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Callable

import discord
from discord.ui import View

from Multiplayer.games import BATTLE_GAMES
from dcrbot.storage import LEADERBOARD_INFO_DIR, load_data, summarize_game_records


StatCheck = Callable[[dict], bool]
ACHIEVEMENT_RECORD_PATH = LEADERBOARD_INFO_DIR / "achievements.json"


@dataclass(frozen=True)
class Achievement:
    icon: str
    title: str
    description: str
    check: StatCheck

    @property
    def key(self) -> str:
        return self.title


def _plays(n: int) -> StatCheck:
    return lambda s: int(s.get("plays", 0) or 0) >= n


def _wins(n: int) -> StatCheck:
    return lambda s: int(s.get("wins", 0) or 0) >= n


def _profit(n: int) -> StatCheck:
    return lambda s: int(s.get("total_delta", 0) or 0) >= n


def _best(n: int) -> StatCheck:
    return lambda s: s.get("max_profit") is not None and int(s.get("max_profit", 0) or 0) >= n


def _losses(n: int) -> StatCheck:
    return lambda s: int(s.get("losses", 0) or 0) >= n


def _extra(key: str, n: int | float) -> StatCheck:
    return lambda s: float((s.get("extra") if isinstance(s.get("extra"), dict) else {}).get(key, 0) or 0) >= float(n)


def _highest_clear(n: int) -> StatCheck:
    def check(s: dict) -> bool:
        extra = s.get("extra") if isinstance(s.get("extra"), dict) else {}
        if "highest_cleared_difficulty" not in extra:
            return False
        return int(extra.get("highest_cleared_difficulty", 0) or 0) >= n

    return check


def _unlocked(n: int) -> StatCheck:
    return lambda s: int(s.get("unlocked_level", 0) or 0) >= n


def _win_rate(percent: float, min_plays: int) -> StatCheck:
    def check(s: dict) -> bool:
        plays = int(s.get("plays", 0) or 0)
        return plays >= min_plays and int(s.get("wins", 0) or 0) / max(1, plays) * 100 >= percent

    return check


def _total_bet(n: int) -> StatCheck:
    return lambda s: int(s.get("total_bet", 0) or 0) >= n


def _even(n: int) -> StatCheck:
    return lambda s: int(s.get("evens", 0) or 0) >= n


def _base(game_word: str) -> list[Achievement]:
    return [
        Achievement("🎮", f"{game_word}初體驗", "遊玩 1 場。", _plays(1)),
        Achievement("🔁", f"{game_word}常客", "遊玩 5 場。", _plays(5)),
        Achievement("🧭", f"{game_word}熟手", "遊玩 10 場。", _plays(10)),
        Achievement("🏆", f"{game_word}首勝", "取得 1 勝。", _wins(1)),
        Achievement("🥇", f"{game_word}五連捷報", "累計 5 勝。", _wins(5)),
        Achievement("👑", f"{game_word}十勝王", "累計 10 勝。", _wins(10)),
        Achievement("📈", f"{game_word}正收益", "累計盈虧達 +$1,000。", _profit(1000)),
        Achievement("💎", f"{game_word}大豐收", "單局獲利達 +$5,000。", _best(5000)),
        Achievement("🧱", f"{game_word}抗壓者", "累計 3 敗仍繼續挑戰。", _losses(3)),
        Achievement("🎯", f"{game_word}穩定派", "至少 10 場且勝率達 60%。", _win_rate(60, 10)),
        Achievement("📚", f"{game_word}研究員", "遊玩 25 場。", _plays(25)),
        Achievement("🔥", f"{game_word}百戰熱身", "遊玩 50 場。", _plays(50)),
        Achievement("🌟", f"{game_word}傳奇玩家", "遊玩 100 場。", _plays(100)),
        Achievement("🏅", f"{game_word}二十五勝", "累計 25 勝。", _wins(25)),
        Achievement("💯", f"{game_word}五十勝", "累計 50 勝。", _wins(50)),
        Achievement("💰", f"{game_word}資金流", "累計下注達 $10,000。", _total_bet(10000)),
        Achievement("🏦", f"{game_word}高額投入", "累計下注達 $100,000。", _total_bet(100000)),
        Achievement("📊", f"{game_word}高勝率", "至少 25 場且勝率達 70%。", _win_rate(70, 25)),
        Achievement("🪙", f"{game_word}平局記錄", "累計 3 次平手/無盈虧。", _even(3)),
        Achievement("🧨", f"{game_word}巨額單局", "單局獲利達 +$50,000。", _best(50000)),
    ]


def _any_extra(keys: tuple[str, ...], n: int | float = 1) -> StatCheck:
    return lambda s: any(_extra(key, n)(s) for key in keys)


def _all_extra(keys: tuple[str, ...], n: int | float = 1) -> StatCheck:
    return lambda s: all(_extra(key, n)(s) for key in keys)


ACHIEVEMENTS: dict[str, list[Achievement]] = {
    "骰子決鬥": [
        Achievement("🎲", "命運的起點", "首次參與骰子決鬥。稱號：新手賭徒", _plays(1)),
        Achievement("🤝", "平分秋色", "累計達成 5 次平手並退回本金。稱號：握手言和", _even(5)),
        Achievement("🪙", "微薄之利", "贏得一次點數差僅為 1 的對決。稱號：險勝", _extra("dice_diff_1_win", 1)),
        Achievement("🌈", "壓倒性勝利", "贏得一次點數差高達 10 以上的對決。稱號：氣勢如虹", _extra("dice_diff_10_win", 1)),
        Achievement("📉", "大起大落", "累計出現一場大勝與一場大敗（以差值 6+ 記錄）。稱號：心臟大顆", lambda s: _extra("dice_big_win", 1)(s) and _extra("dice_big_loss", 1)(s)),
        Achievement("✨", "傳奇掠奪者", "觸發 20 倍特例：用 12 痛擊對手的 2。稱號：【天選之人】", _extra("special_20_win_count", 1)),
        Achievement("🕳️", "深淵凝視", "觸發 20 倍特例懲罰：自己的 2 被對手的 12 粉碎。稱號：【悲慘世界】", _extra("special_20_loss_count", 1)),
        Achievement("🍀", "幸運女神的微笑", "累計透過 20 倍特例賺取超過 500 倍收益。稱號：莊家殺手", _extra("special_20_reward_multiplier", 500)),
        Achievement("📊", "這就是數學", "累計進行 100 場骰子決鬥。稱號：統計學家", _plays(100)),
        Achievement("🧊", "不賺不賠", "累計 3 次平手。稱號：絕對零度", _even(3)),
    ],
    "海盜寶藏2": [
        Achievement("🏴‍☠️", "重返加勒比", "首次遊玩《海盜寶藏2》。稱號：實習水手", _plays(1)),
        Achievement("🪢", "繩索上的芭蕾", "只剩最後一次猜錯機會時成功猜出單字。稱號：命懸一線", _extra("pirate_last_chance_win", 1)),
        Achievement("🧭", "完美的航行", "沒有猜錯任何字母，完美通關。稱號：領航員", _extra("pirate_perfect_win", 1)),
        Achievement("🦈", "鯊魚的點心", "挑戰失敗，被大鯊魚吃成碎片。稱號：咔嚓！", _losses(1)),
        Achievement("🍖", "鯊魚老熟人", "累計失敗 20 次。稱號：固定飼料", _losses(20)),
        Achievement("📚", "博學的海盜", "成功猜出長度大於 9 個字母的超長單字。稱號：讀書人", _extra("pirate_long_word_win", 1)),
        Achievement("🔮", "盲猜大師", "在沒有故事分類提示輔助的情況下通關。稱號：靈媒", _extra("pirate_blind_win", 1)),
        Achievement("💰", "這也在你的算計之中嗎", "累計猜對 50 個單字。稱號：寶藏獵人", _wins(50)),
        Achievement("💥", "碎片美學", "最後一次容錯用盡而失敗。稱號：藝術就是爆炸", _extra("pirate_final_miss_loss", 1)),
        Achievement("👑", "海之霸主", "累計贏得 5 場《海盜寶藏2》。稱號：傳奇船長", _wins(5)),
    ],
    "解謎挑戰": [
        Achievement("🧠", "解碼新手", "首次完成一場 2A2B 挑戰。稱號：密碼學徒", _plays(1)),
        Achievement("🕵️", "福爾摩斯降臨", "前 3 次嘗試內猜中密碼。稱號：【神之直覺】", _extra("puzzle_solve_within_3", 1)),
        Achievement("💣", "壓線拆彈", "第 8 次才成功猜中密碼。稱號：驚險擦邊", _extra("puzzle_solve_attempt_8", 1)),
        Achievement("🔄", "完美的交錯", "獲得 0A4B 提示。稱號：擦肩而過", _extra("puzzle_0a4b", 1)),
        Achievement("🚫", "全面封鎖", "獲得 0A0B 提示。稱號：有效情報", _extra("puzzle_0a0b", 1)),
        Achievement("🧮", "精密計算", "累計猜中 30 次密碼。稱號：密碼破譯專家", _wins(30)),
        Achievement("⌛", "遺憾超時", "8 次機會用盡仍未猜中密碼。稱號：邏輯打結", _losses(1)),
        Achievement("🛡️", "倍率守護者", "累計 5 場在第 5 次嘗試內猜中密碼。稱號：高效特工", _extra("puzzle_solve_within_5", 5)),
        Achievement("🎰", "盲打誤撞", "第一次猜測就獲得 2A2B 或以上。稱號：這是運氣", _extra("puzzle_first_2a2b", 1)),
        Achievement("🌐", "矩陣主宰", "累計找出 100 次正確密碼。稱號：矩陣革命家", _wins(100)),
    ],
    "賽馬競速": [
        Achievement("🐎", "馬場新人", "首次下注並觀看賽馬競速。稱號：觀賽嘉賓", _plays(1)),
        Achievement("👁️", "慧眼獨具", "押中 3.0 倍以上獎勵的黑馬。稱號：伯樂", _extra("horse_3x_win", 1)),
        Achievement("🩹", "雖敗猶榮", "馬匹落敗但領取 20% 安慰金。稱號：保險受益人", _losses(1)),
        Achievement("🏆", "常勝將軍", "累計押中 3 場冠軍馬。稱號：馬場大亨", _wins(3)),
        Achievement("🌧️", "全軍覆沒", "累計 5 場沒押中冠軍馬。稱號：非酋騎士", _losses(5)),
        Achievement("⚡", "終點線的逆襲", "所選馬匹在最後階段反超奪冠。稱號：心跳加速", _extra("horse_final_comeback_win", 1)),
        Achievement("💞", "忠實粉絲", "同一號馬累計下注 10 場。稱號：單推人", _any_extra(("horse_pick_1", "horse_pick_2", "horse_pick_3"), 10)),
        Achievement("💸", "賠率控制大師", "累計贏取超過 200 倍的總獎勵。稱號：黃金馬主", _extra("horse_reward_multiplier_total", 200)),
        Achievement("🥾", "跌跌撞撞", "累計領取安慰金 50 次。稱號：屢敗屢戰", _losses(50)),
        Achievement("👑", "三冠王", "1、2、3 號馬都至少押中 5 次冠軍。稱號：全能教練", _all_extra(("horse_pick_1_win", "horse_pick_2_win", "horse_pick_3_win"), 5)),
    ],
    "打氣球": [
        Achievement("🎈", "第一口空氣", "首次點擊打氣讓頭像變大。稱號：膨脹的開始", _extra("pump_total", 1)),
        Achievement("🧠", "見好就收", "打氣 3 次後安全領取倍率。稱號：謹慎行事", _extra("balloon_cashout_3", 1)),
        Achievement("💼", "理財大師", "累計成功領取倍率達 30 次。稱號：穩健收益", _extra("cashout_count", 30)),
        Achievement("🏥", "天價醫藥費", "爆炸並抽中 8~10 倍醫藥費。稱號：傾家蕩產", _extra("medical_fee_8x_count", 1)),
        Achievement("🍵", "微糖去冰", "爆炸但追加 0 倍醫藥費。稱號：醫保全額理賠", _extra("medical_fee_0x_count", 1)),
        Achievement("💓", "與死神擦肩", "爆炸機率 30% 以上時成功完成一次打氣。稱號：玩的就是心跳", _extra("pump_30_percent_survive", 1)),
        Achievement("🗿", "大頭症", "頭像成功放大 8 次且未爆炸。稱號：大頭大頭下雨不愁", _extra("balloon_cashout_8", 1)),
        Achievement("📐", "黃金比例", "累計 3 場在 25% 風險附近收手。稱號：風險精算師", _extra("balloon_cashout_25_percent", 3)),
        Achievement("🌌", "氣球王國的傳奇", "成功打氣 11 次並贏取 500 倍終極大獎。稱號：【宇宙大爆炸】", _extra("cashout_500x_count", 1)),
        Achievement("🦴", "醫療所VIP", "累計支付醫藥費達下注本金 100 倍。稱號：骨折常客", _extra("medical_fee_multiplier_total", 100)),
    ],
}

_ns2_requested = [
    ("🔍", "重啟搜尋", "首次開始《數字搜尋者2》。", _plays(1)),
    ("✅", "初試啼聲", "成功通關 N0 難度。", _highest_clear(0)),
    ("📈", "漸入佳境", "成功通關 N1~N3 任意難度。", _highest_clear(1)),
    ("🔓", "進階探員", "解鎖 N4 難度。", _unlocked(4)),
    ("💸", "預算吃緊", "在 N5 以上難度中單局花費超過 50 猜測費用。", _extra("ns2_high_spend_n5", 1)),
    ("🏙️", "中產階級", "成功通關 N7 難度。", _highest_clear(7)),
    ("🧩", "規格之外", "解鎖 N8 難度。", _unlocked(8)),
    ("🌌", "超越常理", "首次成功猜中 N8 的額外規格。", _extra("extra_guess_success", 1)),
    ("🎮", "高端玩家", "解鎖 N10 難度。", _unlocked(10)),
    ("☠️", "痛苦洗禮", "首次在帶有負面詞條的 N10+ 通關。", _any_extra(("negative_clear_數字通膨", "negative_clear_延遲線索", "negative_clear_通訊不良", "negative_clear_古老枷鎖"))),
    ("🎨", "色彩斑斕", "解鎖 N11 難度。", _unlocked(11)),
    ("🌈", "色相大師", "N11+ 中完美解讀一次複合顏色線索。", _extra("composite_color_clear", 1)),
    ("🔥", "高壓環境", "解鎖 N14 難度。", _unlocked(14)),
    ("🏅", "終極挑戰", "解鎖 N15 難度。", _unlocked(15)),
    ("👑", "真理搜尋者", "成功通關 N15 難度。", _highest_clear(15)),
    ("📜", "完美通關紀錄", "N0 到 N15 所有難度皆至少通關一次。", _all_extra(tuple(f"ns2_clear_n{i}" for i in range(16)))),
    ("📡", "撥雲見日", "受到雜訊攻擊干擾仍猜中答案。", _extra("noise_clear", 1)),
    ("📶", "雜訊滿載", "單局遭遇 5 次以上雜訊攻擊。", _extra("noise_5_single", 1)),
    ("❓", "真假難辨", "被雜訊線索誤導而猜錯答案。", _extra("noise_wrong_guess", 1)),
    ("🟣", "紫色警戒", "首次獲得紫色線索。", _extra("purple_clue_count", 1)),
    ("💜", "神秘紫光", "利用紫色線索成功破案。", _extra("purple_clear", 1)),
    ("🔷", "幾何學家", "首次利用圖形線索破譯數字。", _extra("shape_clue_count", 1)),
    ("🔶", "形狀矩陣", "單局內連續/累計出現 3 次圖形線索。", _extra("shape_clue_count", 3)),
    ("💰", "高額情報費", "在線索/猜測費用提高難度下花費大量預算。", _extra("ns2_high_spend_n5", 1)),
    ("🆓", "免費是最好的", "沒有購買額外線索通關 N4+。", _extra("no_clue_clear_n4", 1)),
    ("🛒", "情報販子", "累計購買 50 次隨機線索。", _extra("random_clue_count", 50)),
    ("🎯", "盲點偵查", "雜訊覆蓋率高時精準命中。", _extra("noise_clear", 3)),
    ("🧹", "數據濾網", "累計看穿並過濾掉 100 個雜訊線索。", _extra("noise_filtered_total", 100)),
    ("⚠️", "負重前行", "在數字通膨詞條下通關。", _extra("negative_clear_數字通膨", 1)),
    ("⏳", "限時營救", "在延遲線索詞條下通關。", _extra("negative_clear_延遲線索", 1)),
    ("🏝️", "信息孤島", "在通訊不良詞條下通關 N10+。", _extra("negative_clear_通訊不良", 1)),
    ("🙈", "致盲射擊", "在古老枷鎖詞條下通關。", _extra("negative_clear_古老枷鎖", 1)),
    ("☄️", "雙重打擊", "單局內同時抽中 2 個負面詞條並通關。", _extra("double_negative_clear", 1)),
    ("🌈", "七彩霓虹", "N11+ 同局處理紫色與複合顏色。", _extra("composite_color_clear", 3)),
    ("📐", "規格大師", "累計 3 局 N8+ 猜對額外規格。", _extra("extra_guess_success", 3)),
    ("🧾", "精準控帳", "通關時剩餘猜測費用剛好為 0。", _extra("zero_budget_clear", 1)),
    ("🆘", "絕境逢生", "剩最後一次猜測機會時通關。", _extra("last_guess_clear", 1)),
    ("🥶", "冷酷邏輯", "N12+ 不犯邏輯錯誤通關。", _extra("clean_logic_n12_clear", 1)),
    ("🌀", "混亂主宰", "雜訊與負面詞條雙重拉滿獲勝。", lambda s: _extra("noise_clear", 1)(s) and _any_extra(("negative_clear_數字通膨", "negative_clear_延遲線索", "negative_clear_通訊不良", "negative_clear_古老枷鎖"))(s)),
    ("💸", "破產邊緣", "因猜測費用不足而失敗。", _extra("budget_fail", 1)),
    ("🏅", "【蝕刻章：初試真金】", "首次踏入 N15 蝕刻章挑戰關卡。", _unlocked(15)),
    ("🛡️", "【蝕刻章：鋼鐵意志】", "不觸發雜訊清除道具通關 N15。", _extra("n15_clear_count", 1)),
    ("🔬", "【蝕刻章：精密解構】", "N15 僅用不到一半回合數通關。", _extra("n15_fast_clear", 1)),
    ("🌟", "【蝕刻章：逆境微光】", "帶著 3 個負面詞條通關 N15。", _extra("n15_all_debuff_clear", 1)),
    ("🎨", "【蝕刻章：斑駁色彩】", "N15 完美破解複合顏色與紫色線索。", _extra("n15_color_master_clear", 1)),
    ("🖐️", "【蝕刻章：巨匠之手】", "通關 N15 且達到最高評價。", _extra("n15_fast_clear", 1)),
    ("🌠", "【鍍金蝕刻章：造物主】", "未錯、無雜訊、滿血通關 N15。", _extra("n15_perfect_clear", 1)),
    ("🏁", "搜尋終焉", "累計通關 N15 難度 10 次。", _extra("n15_clear_count", 10)),
    ("🔢", "數字刻印", "N15 中累積猜對 50 次額外規格。", _extra("n15_extra_success", 50)),
    ("🎖️", "【大滿貫蝕刻章：全能智者】", "解鎖其餘所有 49 個數字搜尋者2成就。", _highest_clear(15)),
]
ACHIEVEMENTS["數字搜尋者2"] = [Achievement(icon, title, desc, check) for icon, title, desc, check in _ns2_requested]

for battle in BATTLE_GAMES.values():
    battle_name = f"多人遊戲：{battle['name']}"
    ACHIEVEMENTS.setdefault(battle_name, _base(battle["name"][:4]))


def _load_achievement_records() -> dict:
    if not ACHIEVEMENT_RECORD_PATH.exists():
        return {}
    try:
        with ACHIEVEMENT_RECORD_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_achievement_records(records: dict) -> None:
    ACHIEVEMENT_RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ACHIEVEMENT_RECORD_PATH.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=4, ensure_ascii=False)


def sync_user_achievement_records(uid: str, summary: dict[str, dict]) -> dict:
    """Persist newly unlocked achievements to leaderboard/info/achievements.json."""

    records = _load_achievement_records()
    user_records = records.setdefault(str(uid), {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    changed = False
    for game_name, achievements in ACHIEVEMENTS.items():
        stats = summary.get(game_name, {})
        game_records = user_records.setdefault(game_name, {})
        for achievement in achievements:
            if achievement.key in game_records or not achievement.check(stats):
                continue
            game_records[achievement.key] = {
                "title": achievement.title,
                "description": achievement.description,
                "icon": achievement.icon,
                "unlocked_at": now,
            }
            changed = True
    if changed:
        _save_achievement_records(records)
    return user_records


def build_achievement_embed(user: discord.User, game_name: str | None = None) -> discord.Embed:
    uid = str(user.id)
    summary = summarize_game_records(load_data(), uid)
    records = sync_user_achievement_records(uid, summary)
    display_name = getattr(user, "display_name", getattr(user, "name", "玩家"))
    if game_name is None:
        total = sum(len(v) for v in ACHIEVEMENTS.values())
        unlocked = sum(sum(1 for a in achievements if a.check(summary.get(game, {}))) for game, achievements in ACHIEVEMENTS.items())
        embed = discord.Embed(title=f"🏆 {display_name} 的 Achievement", description=f"總進度 **{unlocked}/{total}**。已解鎖成就會寫入 `leaderboard/info/achievements.json`。", color=discord.Color.gold())
        lines = []
        for game, achievements in ACHIEVEMENTS.items():
            done = sum(1 for a in achievements if a.check(summary.get(game, {})))
            lines.append(f"**{game}**：{done}/{len(achievements)}")
        embed.add_field(name="遊戲進度", value="\n".join(lines)[:1024], inline=False)
        return embed
    stats = summary.get(game_name, {})
    achievements = ACHIEVEMENTS.get(game_name, [])
    done = sum(1 for a in achievements if a.check(stats))
    embed = discord.Embed(title=f"🏆 {display_name}｜{game_name} Achievement", description=f"進度 **{done}/{len(achievements)}**", color=discord.Color.blurple())
    chunks = []
    for achievement in achievements:
        ok = achievement.check(stats)
        saved = records.get(game_name, {}).get(achievement.key, {}) if isinstance(records.get(game_name, {}), dict) else {}
        unlocked_at = f"（{saved.get('unlocked_at')}）" if ok and saved.get("unlocked_at") else ""
        chunks.append(f"{'✅' if ok else '⬛'} {achievement.icon} **{achievement.title}**｜{achievement.description}{unlocked_at}")
    for index in range(0, len(chunks), 10):
        embed.add_field(name=f"成就 {index + 1}-{min(index + 10, len(chunks))}", value="\n".join(chunks[index:index + 10])[:1024], inline=False)
    return embed


class AchievementGameSelect(discord.ui.Select):
    def __init__(self, user: discord.User):
        self.user = user
        options = [discord.SelectOption(label="全部遊戲", value="__all__", emoji="🏆")]
        options += [discord.SelectOption(label=game[:100], value=game[:100], emoji="🎮") for game in ACHIEVEMENTS]
        super().__init__(placeholder="選擇成就頁面", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ 這不是你的成就選單。", ephemeral=True)
            return
        selected = self.values[0]
        await interaction.response.edit_message(embed=build_achievement_embed(self.user, None if selected == "__all__" else selected), view=AchievementView(self.user))


class AchievementView(View):
    def __init__(self, user: discord.User):
        super().__init__(timeout=180)
        self.add_item(AchievementGameSelect(user))
