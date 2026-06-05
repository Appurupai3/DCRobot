"""Pirate word-bank loading and translation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random


REPO_ROOT = Path(__file__).resolve().parents[1]
WORD_BANK_PATH = REPO_ROOT / "pirate_words.txt"
WORD_CATEGORY_DIR = REPO_ROOT / "words"


@dataclass(frozen=True)
class PirateWordEntry:
    word: str
    translation: str
    category_key: str
    category_name: str
    story_hint: str


CATEGORY_STORIES: dict[str, tuple[str, str]] = {
    "1_Nature_Cosmos": (
        "大自然與宇宙",
        "船長夜裡仰望星空，潮汐、暴風、山脈與極光都在替寶藏指路。",
    ),
    "2_Nautical_Pirate": (
        "航海與海盜冒險",
        "水手拉起船帆、拋下船錨，黑旗在甲板上呼呼作響，遠方像藏著一座島。",
    ),
    "3_Travel_Transport": (
        "旅遊、交通與航空",
        "旅人拿著登機證穿越車站、機場與港口，一路尋找下一段旅程的交通工具。",
    ),
    "4_History_Fantasy": (
        "歷史、奇幻與中世紀",
        "古堡裡的騎士、法師與王國傳說被封在羊皮卷中，等你打開年代久遠的門。",
    ),
    "5_Flora_Fauna": (
        "動植物與生物界",
        "叢林、珊瑚礁與草原同時醒來，羽毛、葉片、爪印和花香留下生命的暗號。",
    ),
    "6_Science_Tech": (
        "科學、科技與醫療",
        "實驗室的儀器閃著藍光，演算法、藥劑與電路正在破解未知的祕密。",
    ),
    "7_Business_Law": (
        "商業、經濟與法律",
        "港口商會正在簽合約、算帳本、開庭辯論，金幣與規則一起決定勝負。",
    ),
    "8_Arts_Culture": (
        "藝術、文學與休閒娛樂",
        "劇院燈光亮起，畫布、小說、音樂與遊戲把船員帶進一場文化盛宴。",
    ),
    "9_Psychology_Traits": (
        "心理學與人格特質",
        "船員的勇氣、焦慮、記憶與野心在風浪中浮現，真正的線索藏在內心。",
    ),
    "10_Abstract_Terms": (
        "社會城市與進階抽象概念",
        "城市高樓、制度、理念與看不見的概念交織成迷霧，考驗你對抽象世界的理解。",
    ),
}


FALLBACK_CATEGORY = "海盜寶藏單字庫"
FALLBACK_STORY = "老船長只留下一張泛黃藏寶圖，答案可能來自任何一箱混合單字寶物。"


def _parse_word_line(line: str) -> tuple[str, str] | None:
    raw_line = line.strip()
    if not raw_line:
        return None
    if "|" in raw_line:
        word_part, translation_part = raw_line.split("|", 1)
        word = word_part.strip().upper()
        translation = translation_part.strip()
    else:
        word = raw_line.upper()
        translation = ""
    if not word.isalpha():
        return None
    return word, translation


def _category_sort_key(path: Path) -> tuple[int, str]:
    prefix = path.stem.split("_", 1)[0]
    try:
        return int(prefix), path.stem
    except ValueError:
        return 999, path.stem


def _load_category_word_entries() -> list[PirateWordEntry]:
    entries: list[PirateWordEntry] = []

    if not WORD_CATEGORY_DIR.exists():
        return entries

    for path in sorted(WORD_CATEGORY_DIR.glob("[0-9]*_*.txt"), key=_category_sort_key):
        category_key = path.stem
        category_name, story_hint = CATEGORY_STORIES.get(category_key, (category_key, FALLBACK_STORY))
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                parsed = _parse_word_line(line)
                if parsed is None:
                    continue
                word, translation = parsed
                entries.append(
                    PirateWordEntry(
                        word=word,
                        translation=translation,
                        category_key=category_key,
                        category_name=category_name,
                        story_hint=story_hint,
                    )
                )
    return entries


def _load_fallback_word_entries() -> list[PirateWordEntry]:
    entries: list[PirateWordEntry] = []
    seen: set[str] = set()

    if not WORD_BANK_PATH.exists():
        return entries

    with WORD_BANK_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            parsed = _parse_word_line(line)
            if parsed is None:
                continue
            word, translation = parsed
            if word in seen:
                continue
            seen.add(word)
            entries.append(
                PirateWordEntry(
                    word=word,
                    translation=translation,
                    category_key="pirate_words",
                    category_name=FALLBACK_CATEGORY,
                    story_hint=FALLBACK_STORY,
                )
            )
    return entries


def load_pirate_word_bank() -> tuple[list[PirateWordEntry], dict[str, str]]:
    entries = _load_category_word_entries() or _load_fallback_word_entries()

    if not entries:
        raise ValueError("pirate word bank is empty; please populate words/*.txt or pirate_words.txt")

    translations: dict[str, str] = {}
    for entry in entries:
        if entry.translation and entry.word not in translations:
            translations[entry.word] = entry.translation

    return entries, translations


PIRATE_WORD_ENTRIES, PIRATE_WORD_TRANSLATIONS = load_pirate_word_bank()
PIRATE_WORDS = [entry.word for entry in PIRATE_WORD_ENTRIES]


def random_pirate_word_entry() -> PirateWordEntry:
    return random.choice(PIRATE_WORD_ENTRIES)


def pirate_translation(word: str) -> str:
    upper = word.upper()
    return PIRATE_WORD_TRANSLATIONS.get(upper, "（暫無翻譯）")
