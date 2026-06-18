"""Achievement catalogue and Discord UI for economy games."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable

import discord
from discord.ui import View

from Multiplayer.games import BATTLE_GAMES
from dcrbot.storage import load_data, summarize_game_records


StatCheck = Callable[[dict], bool]
ACHIEVEMENT_RECORD_PATH = Path("json") / "achievements.json"
LEGACY_ACHIEVEMENT_RECORD_PATH = Path("leaderboard") / "info" / "achievements.json"


@dataclass(frozen=True)
class AchievementUnlock:
    game_name: str
    title: str
    description: str
    icon: str
    unlocked_at: str


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


ACHIEVEMENTS["骰子決鬥"] += [
    Achievement("🚪", "開門大吉", "第一把對決就以點數差 >3 獲勝。稱號：好的開始", _extra("dice_first_big_win", 1)),
    Achievement("😵", "大意失荊州", "大比分領先期望下被逆轉。稱號：大意了", _extra("dice_big_loss", 1)),
    Achievement("🎛️", "穩健流派", "連續 5 場差值都在 ±2 內。稱號：控盤大師", _extra("dice_close_game", 5)),
    Achievement("🪓", "差值極值", "贏得點數差剛好 11 的對決。稱號：降維打擊", _extra("dice_diff_11_win", 1)),
    Achievement("🍀", "命運的微笑", "連續 3 場贏得最高上限收益。稱號：幸運星", _extra("dice_diff_10_win", 3)),
    Achievement("⚖️", "天平兩端", "至少 50 場且總盈虧回到 0。稱號：絕對中立", lambda s: _plays(50)(s) and int(s.get("total_delta", 0) or 0) == 0),
    Achievement("😮‍💨", "死裡逃生", "差點觸發 10 倍懲罰。稱號：擦汗", _extra("dice_near_10x_penalty", 1)),
    Achievement("🪨", "幸運滾石", "累計投出 50 次 12 點。稱號：滿點狂熱", _extra("dice_total_12_count", 50)),
    Achievement("✝️", "黃金交叉", "輸掉 X 後下一把剛好贏回 X。稱號：完美對沖", _extra("dice_hedge_pair", 1)),
    Achievement("👥", "雙雄對峙", "連續兩把與 AI 擲出相同總點數。稱號：複製人", _extra("dice_same_total_pair", 1)),
    Achievement("💸", "豪賭客", "累計投入超過 5000 本金。稱號：揮金如土", _total_bet(5000)),
    Achievement("🚑", "10倍的痛", "累積承受 5 次 10 倍懲罰。稱號：擔架隊抬走", _extra("special_20_loss_count", 5)),
    Achievement("☄️", "天譴之人", "累計投出 50 次 2 點。稱號：霉運纏身", _extra("dice_total_2_count", 50)),
    Achievement("🧮", "計算機靈魂", "淨收益符合 0.5 倍精算結果達 10 次。稱號：精算大師", _extra("dice_half_step_profit", 10)),
    Achievement("🔥", "連擊大師", "達成 5 連勝。稱號：戰神", _extra("dice_win_streak_5", 1)),
    Achievement("🧗", "永不言棄", "10 倍懲罰後下一把 50 倍收益。稱號：絕地反擊", _extra("dice_punish_then_jackpot", 1)),
    Achievement("🎲", "骰子狂熱", "總計擲出 1000 顆骰子。稱號：骰子不離手", _extra("dice_roll_count", 1000)),
    Achievement("😭", "莊家流眼淚", "單局贏取超過 100 倍收益。稱號：賭神", _extra("dice_100x_profit", 1)),
    Achievement("🎁", "慈善家", "連續 6 把輸且差值皆大於 4。稱號：送財童子", _extra("dice_loss_streak_6_big", 1)),
    Achievement("👑", "至高榮譽", "同時解鎖傳奇掠奪者與深淵凝視。稱號：命運的主宰", lambda s: _extra("special_20_win_count", 1)(s) and _extra("special_20_loss_count", 1)(s)),
]

ACHIEVEMENTS["海盜寶藏2"] += [Achievement("🏴‍☠️", name, desc, check) for name, desc, check in [
    ("初學走路", "猜對 3 字母單字。稱號：幼兒班", _extra("pirate_short_word_win", 1)), ("字典搬運工", "累計猜對 100 個不同單字。稱號：行走的字典", _wins(100)),
    ("最後一根稻草", "下一次必死時填入正確字母。稱號：驚險脫身", _extra("pirate_last_chance_win", 1)), ("摸透套路", "累積看過 50 次分類故事提示。稱號：故事聆聽者", _plays(50)),
    ("亂槍打鳥", "連續 4 個錯誤字母。稱號：空網捕魚", _extra("pirate_wrong_4", 1)), ("連鎖效應", "一局連續猜對 4 個字母。稱號：靈感爆發", _extra("pirate_correct_4", 1)),
    ("碎片收集者", "累積 1000 片死亡碎片。稱號：拼圖大師", _losses(63)), ("水手長認證", "連勝 3 場高難故事。稱號：資深水手", _wins(3)),
    ("秒殺對局", "30 秒內猜出單字。稱號：速讀狂人", _extra("pirate_fast_win", 1)), ("這字真臭", "含 X/Z/Q 冷門字母且通關。稱號：冷門知識王", _extra("pirate_rare_letter_win", 1)),
    ("海面漫步", "被吊著累計 1 小時。稱號：耐力驚人", _plays(60)), ("鯊魚減肥日記", "連續 4 場完美通關。稱號：護航專家", _extra("pirate_perfect_win", 4)),
    ("分類專家", "通關多個故事分類。稱號：全知讀者", _extra("pirate_category_clear", 10)), ("一字千金", "高額下注完美通關。稱號：豪門海盜", lambda s: _extra("pirate_perfect_win", 1)(s) and _best(5000)(s)),
    ("字母陷阱", "同坑跌兩次。稱號：同坑跌兩次", _extra("pirate_repeat_trap", 1)), ("教科書式通關", "母音順序開局並通關。稱號：學院派", _extra("pirate_vowel_opening_win", 1)),
    ("最後的晚餐", "第 5 錯時查看提示。稱號：臨終遺言", _extra("pirate_wrong_total", 5)), ("逆風翻盤", "錯 4 字母後成功。稱號：鯊口生還", _extra("pirate_wrong_4_win", 1)),
    ("航海傳奇", "累計通關 200 次。稱號：加勒比之王", _wins(200)), ("鯊魚的怨念", "10 分鐘無操作。稱號：釣魚執法", _extra("pirate_timeout_10m", 1)),
]]

ACHIEVEMENTS["解謎挑戰"] += [Achievement("🧠", name, desc, check) for name, desc, check in [
    ("密碼初體驗", "第一次獲得 1A1B。稱號：摸索中", _extra("puzzle_1a1b", 1)), ("漸漸對齊", "連續三次 A 數遞增。稱號：精準校準", _extra("puzzle_bulls_rising_3", 1)),
    ("位置強迫症", "連續三次 1A0B。稱號：釘子戶", _extra("puzzle_1a0b", 3)), ("數字流浪記", "數字從第 1 位流浪到第 4 位。稱號：深度旅遊", _extra("puzzle_digit_travel", 1)),
    ("雙子星", "獲得 2A0B 提示 5 次。稱號：半壁江山", _extra("puzzle_2a0b", 5)), ("高嶺之花", "第 6～8 次成功。稱號：低保領取者", _extra("puzzle_late_solve", 1)),
    ("差之毫釐", "3A0B 後變 2A1B。稱號：反向操作", _extra("puzzle_3a_then_2a1b", 1)), ("破譯狂人", "一局輸入 8 次不重複組合。稱號：窮舉法大師", _extra("puzzle_full_8_unique", 1)),
    ("邏輯漏洞", "輸入重複數字。稱號：恍神", _extra("puzzle_duplicate_rejected", 1)), ("閃電密碼", "15 秒內成功。稱號：超頻大腦", _extra("puzzle_fast_win", 1)),
    ("完美絕緣", "連續兩局第一發 0A0B。稱號：乾淨溜溜", _extra("puzzle_0a0b", 2)), ("中流砥柱", "第 4 次成功。稱號：黃金分割", _extra("puzzle_solve_attempt_4", 1)),
    ("數字矩陣", "累計使用 1000 個數字。稱號：數值狂熱", _extra("puzzle_digit_used_total", 1000)), ("全場焦點", "獲得 1A3B。稱號：差點就對了", _extra("puzzle_1a3b", 1)),
    ("理智線斷裂", "3A 優勢下最後猜錯。稱號：痛失好局", _extra("puzzle_3a_final_loss", 1)), ("密碼守門員", "連續 10 場成功。稱號：不破之牆", _wins(10)),
    ("盲點清除者", "0A0B 後下一次 2A2B。稱號：情報最大化", _extra("puzzle_0a0b_then_2a2b", 1)), ("資本家破譯", "高額下注 4 次內通關。稱號：高風險高回報", lambda s: _extra("puzzle_solve_within_5", 1)(s) and _best(5000)(s)),
    ("終極密碼", "猜中包含 0 和 9 的密碼。稱號：兩極通吃", _extra("puzzle_extreme_secret_win", 1)), ("圖靈傳人", "累計通關 150 次。稱號：機械腦袋", _wins(150)),
]]

ACHIEVEMENTS["賽馬競速"] += [Achievement("🐎", name, desc, check) for name, desc, check in [
    ("馬廄常客", "觀看賽馬 20 場。稱號：核心車迷", _plays(20)), ("低空飛過", "極小優勢奪冠。稱號：險勝一馬鼻", _extra("horse_close_win", 1)),
    ("強烈推薦", "全程領先奪冠。稱號：明星馬王", _extra("horse_wire_to_wire", 1)), ("翻車現場", "高倍率熱門馬跑最後。稱號：世紀泡沫", _extra("horse_bubble_loss", 1)),
    ("安慰金富豪", "安慰金總額突破 1000。稱號：專業回血", _extra("horse_consolation_total", 1000)), ("黑馬觀察家", "押中 2.8 倍以上 10 次。稱號：銳利鷹眼", _extra("horse_28x_win", 10)),
    ("風水輪流轉", "1/2/3 號連續奪冠。稱號：完美的輪迴", _all_extra(("horse_pick_1_win", "horse_pick_2_win", "horse_pick_3_win"), 1)), ("全押是不可能的", "試圖同時押兩匹馬。稱號：貪心鬼", _extra("horse_multi_bet_rejected", 1)),
    ("一馬當先", "開局領先保持到終點。稱號：火箭起跑", _extra("horse_wire_to_wire", 1)), ("冷門奇蹟", "連續兩場最高倍率馬奪冠。稱號：天地異變", _extra("horse_28x_win", 2)),
    ("長線投資", "連續 15 場下注。稱號：鐵桿馬迷", _plays(15)), ("最後衝刺", "最後彎道倒一反超。稱號：奇蹟再現", _extra("horse_final_comeback_win", 1)),
    ("買定離手", "壓線下注並獲勝。稱號：壓線狂魔", _extra("horse_late_bet_win", 1)), ("命運的三分之一", "冠軍馬號 1→2→3。稱號：順數大師", _all_extra(("horse_pick_1_win", "horse_pick_2_win", "horse_pick_3_win"), 1)),
    ("天選伯樂", "贏得最高隨機上限。稱號：頂級眼光", _extra("horse_3x_win", 1)), ("陪跑員", "所選馬連續 5 場第二。稱號：萬年老二", _extra("horse_second_place", 5)),
    ("馬場常青樹", "觀看賽馬 100 場。稱號：榮譽裁判", _plays(100)), ("資金避風港", "靠安慰金未破產。稱號：仰賴保險", _losses(10)),
    ("絕對掌控", "大幅拉開距離。稱號：斷層式領先", _extra("horse_dominant_win", 1)), ("凱旋門之王", "累計總獎金 5000 倍下注額。稱號：傳奇馬主", _extra("horse_reward_multiplier_total", 5000)),
]]

ACHIEVEMENTS["打氣球"] += [Achievement("🎈", name, desc, check) for name, desc, check in [
    ("氣體外洩", "第 1 次打氣後立刻結束。稱號：膽小如鼠", _extra("balloon_cashout_1", 1)), ("氣流湧動", "連續 5 場打氣 5 次以上。稱號：穩定輸出", _extra("balloon_cashout_5", 5)),
    ("臨界點", "25% 那一擊成功撐過。稱號：極限施壓", _extra("balloon_cashout_25_percent", 1)), ("醫療費暴擊", "醫藥費 10 倍。稱號：骨科重症", _extra("medical_fee_10x_count", 1)),
    ("無傷出院", "3 次爆炸 0 倍醫藥費。稱號：錦鯉附體", _extra("medical_fee_0x_count", 3)), ("頭像充氣中", "累計打氣 200 次。稱號：手速達人", _extra("pump_total", 200)),
    ("半途而廢", "低於 18% 風險收手 3 次。稱號：安全第一", _extra("balloon_cashout_low_risk", 3)), ("天空才是極限", "打氣 10 次後收手。稱號：扼腕嘆息", _extra("balloon_cashout_10", 1)),
    ("保險公司在哭泣", "醫藥費低於總收益 5%。稱號：幸運規避", _extra("cashout_total", 1)), ("一擊即炸", "第 1 次打氣直接爆炸。稱號：天譴開局", _extra("balloon_first_pump_burst", 1)),
    ("膨脹美學", "頭像遮住半個螢幕。稱號：遮天蔽日", _extra("balloon_cashout_8", 1)), ("貪婪的代價", "9 次後貪心爆炸。稱號：人財兩空", _extra("balloon_burst_after_9", 1)),
    ("穩健收割", "結束打氣總獎金突破 3000 倍。稱號：氣球大亨", _extra("cashout_total", 3000)), ("醫學奇蹟", "高醫藥費爆炸後通關。稱號：起死回生", lambda s: _extra("medical_fee_8x_count", 2)(s) and _extra("cashout_500x_count", 1)(s)),
    ("打氣筒冒煙", "5 秒內點擊 6 次。稱號：瘋狂抽真空", _extra("pump_total", 6)), ("安全著陸", "30% 風險時收手。稱號：見好就收", _extra("balloon_cashout_30_percent", 1)),
    ("氣球終結者", "點破 50 個氣球。稱號：爆破專家", _losses(50)), ("黃金十一次", "第二次達成 11 次成功。稱號：氣球之神", _extra("cashout_500x_count", 2)),
    ("預算赤字", "醫藥費造成破產邊緣。稱號：破產邊緣", _extra("medical_fee_multiplier_total", 100)), ("心理戰大師", "33% 爆炸率仍成功。稱號：鋼鐵神經", _extra("pump_30_percent_survive", 1)),
]]

ACHIEVEMENTS["拋硬幣挑戰"] = [Achievement("🪙", name, desc, check) for name, desc, check in [
    ("正反交響曲", "序列呈現正反交替。稱號：規律之美", _extra("coin_alternating_6", 1)), ("鏡像對決", "AI 隨機與玩家組合相同。稱號：靈魂共鳴", _extra("coin_mirror_ai", 1)),
    ("外掛制裁者", "AI 反制算法下仍獲勝。稱號：【弒神者】", _extra("coin_counter_win", 1)), ("一擲乾坤", "3 次投擲內玩家獲勝。稱號：三連天選", _extra("coin_fast_player_win", 1)),
    ("硬幣工廠", "累計投擲 1000 次。稱號：鑄幣廠長", _extra("coin_toss_total", 1000)), ("極端不對稱", "選正正正但前 8 次全反。稱號：被詛咒的正面", _extra("coin_all_heads_all_tails_start", 1)),
    ("這也在算法之內？", "玩家先選連敗 5 場。稱號：算法的奴隸", _extra("coin_counter_loss", 5)), ("翻轉吧硬幣", "單局超過 20 次投擲。稱號：世紀拉鋸戰", _extra("coin_long_game", 1)),
    ("莊家通吃", "AI 先選且 3 次內獲勝。稱號：閃電落敗", _extra("coin_fast_ai_win", 1)), ("黃金三倍", "累積 3 倍獎勵 3000。稱號：硬幣富豪", _profit(3000)),
    ("單一信仰", "連續 10 場同組合。稱號：頑固分子", _plays(10)), ("概率收斂", "正反誤差在 1% 內。稱號：大數法則", _extra("coin_balance_close", 1)),
    ("先手狂人", "連續 5 場玩家先選。稱號：奪刀在手", _extra("coin_player_first", 5)), ("後手逆襲", "AI 先選連續 5 場玩家全勝。稱號：後發制人", _extra("coin_ai_first_player_win", 5)),
    ("擦肩而過", "差一枚就贏。稱號：遺憾空手", _extra("coin_near_miss", 1)), ("硬幣收藏家", "參與 100 場。稱號：歐幣玩家", _plays(100)),
    ("極速運轉", "2 秒內結束。稱號：效率至上", _extra("coin_fast_player_win", 1)), ("直覺失靈", "遭遇 4 連敗。稱號：玄不救非", _losses(4)),
    ("幸運幣之魂", "資產只剩一把時翻盤。稱號：賭徒的末路", _extra("coin_all_in_comeback", 1)), ("硬幣之主", "同時解鎖反制反制與外掛制裁者。稱號：【概率代行者】", lambda s: _extra("coin_counter_win", 1)(s) and _extra("coin_counter_loss", 1)(s)),
]]

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
    record_path = ACHIEVEMENT_RECORD_PATH if ACHIEVEMENT_RECORD_PATH.exists() else LEGACY_ACHIEVEMENT_RECORD_PATH
    if not record_path.exists():
        return {}
    try:
        with record_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_achievement_records(records: dict) -> None:
    ACHIEVEMENT_RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ACHIEVEMENT_RECORD_PATH.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=4, ensure_ascii=False)


def sync_user_achievement_records(uid: str, summary: dict[str, dict]) -> dict:
    """Persist newly unlocked achievements to json/achievements.json."""

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


def unlock_new_achievement_records(uid: str, game_name: str | None = None) -> list[AchievementUnlock]:
    """Evaluate achievements, persist new unlocks, and return only newly earned ones."""

    summary = summarize_game_records(load_data(), str(uid))
    records = _load_achievement_records()
    user_records = records.setdefault(str(uid), {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    changed = False
    new_unlocks: list[AchievementUnlock] = []
    games = {game_name: ACHIEVEMENTS.get(game_name, [])} if game_name else ACHIEVEMENTS
    for current_game, achievements in games.items():
        if not achievements:
            continue
        stats = summary.get(current_game, {})
        game_records = user_records.setdefault(current_game, {})
        for achievement in achievements:
            if achievement.key in game_records or not achievement.check(stats):
                continue
            game_records[achievement.key] = {
                "title": achievement.title,
                "description": achievement.description,
                "icon": achievement.icon,
                "unlocked_at": now,
            }
            new_unlocks.append(AchievementUnlock(current_game, achievement.title, achievement.description, achievement.icon, now))
            changed = True
    if changed:
        _save_achievement_records(records)
    return new_unlocks


def format_achievement_unlock_text(unlocks: list[AchievementUnlock]) -> str:
    if not unlocks:
        return ""
    lines = ["🏆 **成就解鎖！**"]
    for unlock in unlocks[:5]:
        lines.append(f"{unlock.icon} **{unlock.title}**｜{unlock.description}")
    if len(unlocks) > 5:
        lines.append(f"…另外還有 {len(unlocks) - 5} 個成就已寫入 Achievement 頁面。")
    return "\n".join(lines)


def build_achievement_embed(user: discord.User, game_name: str | None = None) -> discord.Embed:
    uid = str(user.id)
    summary = summarize_game_records(load_data(), uid)
    unlock_new_achievement_records(uid)
    records = sync_user_achievement_records(uid, summary)
    display_name = getattr(user, "display_name", getattr(user, "name", "玩家"))
    if game_name is None:
        total = sum(len(v) for v in ACHIEVEMENTS.values())
        unlocked = sum(sum(1 for a in achievements if a.check(summary.get(game, {}))) for game, achievements in ACHIEVEMENTS.items())
        embed = discord.Embed(title=f"🏆 {display_name} 的 Achievement", description=f"總進度 **{unlocked}/{total}**。已解鎖成就會寫入 `json/achievements.json`。", color=discord.Color.gold())
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
