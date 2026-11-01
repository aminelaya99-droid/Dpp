"""تطبيع النصوص العربية ومطابقة الأسماء التقريبية."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text)).strip().lower()
    t = _DIACRITICS.sub("", t)
    t = (t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ٱ", "ا")
         .replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي"))
    t = _PUNCT.sub(" ", t).replace("_", " ")
    words = [w[2:] if w.startswith("ال") and len(w) > 4 else w for w in _SPACES.split(t) if w]
    return " ".join(words)


def similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    wa, wb = set(na.split()), set(nb.split())
    jacc = len(wa & wb) / len(wa | wb) if wa | wb else 0
    contain = 0.9 if (na in nb or nb in na) and min(len(na), len(nb)) >= 4 else 0
    return max(ratio, jacc, contain)


def best_match(name: str, candidates: dict) -> tuple[object, float]:
    """candidates: {key: name}. يعيد (المفتاح، الدرجة)."""
    best, score = None, 0.0
    for k, cand in candidates.items():
        sc = similarity(name, cand)
        if sc > score:
            best, score = k, sc
    return best, score
