"""Pirate word-bank loading and translation helpers."""

from __future__ import annotations

import os


WORD_BANK_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pirate_words.txt")


def load_pirate_word_bank() -> tuple[list[str], dict[str, str]]:
    words: list[str] = []
    translations: dict[str, str] = {}

    if os.path.exists(WORD_BANK_PATH):
        with open(WORD_BANK_PATH, "r", encoding="utf-8") as f:
            for line in f:
                raw_line = line.strip()
                if not raw_line:
                    continue
                if "|" in raw_line:
                    word_part, translation_part = raw_line.split("|", 1)
                    word = word_part.strip().upper()
                    translation = translation_part.strip()
                else:
                    word = raw_line.upper()
                    translation = ""
                if word.isalpha():
                    words.append(word)
                    if translation:
                        translations[word] = translation

    if not words:
        raise ValueError("pirate word bank is empty; please populate pirate_words.txt")

    return words, translations


PIRATE_WORDS, PIRATE_WORD_TRANSLATIONS = load_pirate_word_bank()


def pirate_translation(word: str) -> str:
    upper = word.upper()
    return PIRATE_WORD_TRANSLATIONS.get(upper, "（暫無翻譯）")
