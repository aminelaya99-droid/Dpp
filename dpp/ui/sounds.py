"""التنبيهات الصوتية: نغمات قصيرة مولَّدة داخل البرنامج (بلا ملفات خارجية).

الأنواع: ok (نجاح الوضع/الحفظ)، conflict (تعارض أو رفض)، alert (تنبيهات البيانات)، reminder (تذكير بالوقت).
التشغيل على Windows عبر winmm.PlaySoundW (ctypes، غير متزامن)؛ في غيره لا يُصدر شيء.
الإعدادات في sounds (JSON): التفعيل العام، مستوى الصوت، تفعيل كل نوع، ومدة التذكير قبل الحصة.
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import tempfile

KINDS = {"ok": "نجاح الوضع والحفظ", "conflict": "تعارض أو رفض", "alert": "تنبيهات البيانات عند الفتح",
         "reminder": "تذكير قبل الحصة أو الحدث"}
DEFAULTS = {"enabled": True, "volume": 70, "ok": True, "conflict": True, "alert": True, "reminder": True,
            "reminder_min": 10}
RATE = 22050

# كل نغمة: قائمة (التردد، المدة بالثانية، شدة نسبية)؛ التردد 0 = صمت
TONES = {
    "ok": [(880, 0.07, 0.8), (1318.5, 0.11, 0.8)],
    "conflict": [(311, 0.12, 1.0), (0, 0.05, 0), (233, 0.18, 1.0)],
    "alert": [(988, 0.08, 0.8), (0, 0.04, 0), (988, 0.08, 0.8), (0, 0.04, 0), (1319, 0.14, 0.8)],
    "reminder": [(1046.5, 0.45, 0.9), (1568, 0.6, 0.6)],
}
_cache: dict[tuple, str] = {}


def load(db) -> dict:
    o = dict(DEFAULTS)
    try:
        o.update(json.loads(db.get_setting("sounds", "") or "{}"))
    except Exception:
        pass
    return o


def save(db, o: dict) -> None:
    db.set_setting("sounds", json.dumps(o, ensure_ascii=False))


def _wav(kind: str, volume: int) -> str:
    key = (kind, volume)
    if key in _cache and os.path.exists(_cache[key]):
        return _cache[key]
    amp = 32767 * max(0, min(100, volume)) / 100 * 0.6
    frames = bytearray()
    for freq, dur, gain in TONES[kind]:
        n = int(RATE * dur)
        for i in range(n):
            t = i / RATE
            env = min(1.0, i / (RATE * 0.006)) * math.exp(-3.2 * t / max(dur, 0.01))   # هجوم سريع ثم خفوت
            v = 0.0
            if freq:
                v = math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t)
            frames += struct.pack("<h", int(max(-32767, min(32767, amp * gain * env * v / 1.25))))
    path = os.path.join(tempfile.gettempdir(), f"dpp_{kind}_{volume}.wav")
    data = bytes(frames)
    # ترويسة WAV (PCM 16 بت، قناة واحدة) مكتوبة يدوياً
    header = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
              struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16) + b"data" + struct.pack("<I", len(data)))
    with open(path, "wb") as fh:
        fh.write(header + data)
    _cache[key] = path
    return path


def play(kind: str, db=None, force: bool = False) -> bool:
    """يشغّل نغمة النوع إذا كان مفعّلاً. يعيد True إذا أُرسل الصوت."""
    if kind not in TONES:
        return False
    o = load(db) if db is not None else dict(DEFAULTS)
    if not force and (not o.get("enabled") or not o.get(kind, True)):
        return False
    try:
        path = _wav(kind, int(o.get("volume", 70)))
    except Exception:
        return False
    if sys.platform.startswith("win"):
        try:
            import ctypes
            SND_ASYNC, SND_NODEFAULT, SND_FILENAME = 0x0001, 0x0002, 0x00020000
            ctypes.windll.winmm.PlaySoundW(path, None, SND_ASYNC | SND_NODEFAULT | SND_FILENAME)
            return True
        except Exception:
            return False
    return False
