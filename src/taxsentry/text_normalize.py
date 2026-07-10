from __future__ import annotations

import re
import unicodedata


def normalize_for_match(text: str) -> str:
    """Lowercase text and remove Vietnamese accents for intent/memory matching."""
    lowered = (text or "").lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    without_marks = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return without_marks.replace("đ", "d")


def tokens_for_match(text: str) -> list[str]:
    normalized = normalize_for_match(text)
    return [token for token in re.split(r"\W+", normalized) if token]
