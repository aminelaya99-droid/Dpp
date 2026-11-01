"""قراءة ملفات .roz المصدّرة من aSc Timetables (صيغة XML).

يدعم البنية القياسية لتصدير aSc:
<timetable><periods><period period= starttime= endtime=/></periods>
<daysdefs/><subjects/><teachers/><classes/><groups/><lessons/><cards/></timetable>
الملف قد يكون XML مباشرة أو مضغوطاً (zip/gzip)، بترميز UTF-8 أو UTF-16.
"""
from __future__ import annotations

import gzip
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RozTeacher:
    id: str
    name: str
    first_name: str = ""
    last_name: str = ""
    short: str = ""


@dataclass
class RozEntry:
    """حصة واحدة مفكوكة: فرع واحد، يوم واحد، وقت متصل."""
    class_id: str
    class_name: str
    subject_id: str
    subject_name: str
    teacher_ids: list[str]
    day: int
    start: int
    end: int
    group_name: str = ""

    @property
    def duration(self) -> int:
        return self.end - self.start


@dataclass
class RozData:
    periods: dict[int, tuple[int, int]] = field(default_factory=dict)
    subjects: dict[str, tuple[str, str]] = field(default_factory=dict)  # id -> (name, short)
    teachers: dict[str, RozTeacher] = field(default_factory=dict)
    classes: dict[str, tuple[str, str]] = field(default_factory=dict)
    entries: list[RozEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _read_bytes(src) -> bytes:
    if isinstance(src, (bytes, bytearray)):
        data = bytes(src)
    else:
        data = Path(src).read_bytes()
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            xmls = [n for n in names if n.lower().endswith(".xml")] or names
            data = z.read(xmls[0])
    elif data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def _parse_xml(data: bytes) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        for enc in ("utf-16", "utf-8-sig", "cp1256"):
            try:
                text = data.decode(enc)
                text = re.sub(r"^<\?xml[^>]*\?>", "", text.strip())
                return ET.fromstring(text)
            except (UnicodeDecodeError, ET.ParseError):
                continue
        raise ValueError("الملف ليس XML صالحاً من aSc")


def parse_time(text: str) -> int:
    text = (text or "").strip()
    m = re.match(r"(\d{1,2})[:h.](\d{2})", text)
    if not m:
        raise ValueError(f"وقت غير صالح: {text!r}")
    return int(m.group(1)) * 60 + int(m.group(2))


def _ids(text: str | None) -> list[str]:
    return [x.strip() for x in (text or "").split(",") if x.strip()]


def _days(mask: str) -> list[int]:
    """'01000' -> [1]. قد يحتوي القناع على فواصل لعدة خيارات (يُؤخذ الأول)."""
    mask = (mask or "").split(",")[0].strip()
    return [i for i, ch in enumerate(mask) if ch == "1"]


def _find(root: ET.Element, tag: str) -> list[ET.Element]:
    return list(root.iter(tag))


def parse_roz(src) -> RozData:
    root = _parse_xml(_read_bytes(src))
    d = RozData()
    for p in _find(root, "period"):
        try:
            num = int(p.get("period") or p.get("name") or 0)
            d.periods[num] = (parse_time(p.get("starttime", "")), parse_time(p.get("endtime", "")))
        except ValueError as e:
            d.warnings.append(str(e))
    daysdefs = {x.get("id"): x.get("days", "") for x in _find(root, "daysdef")}
    for x in _find(root, "subject"):
        d.subjects[x.get("id")] = ((x.get("name") or x.get("short") or "").strip(), (x.get("short") or "").strip())
    for x in _find(root, "teacher"):
        first, last = (x.get("firstname") or "").strip(), (x.get("lastname") or "").strip()
        name = (x.get("name") or f"{last} {first}").strip()
        d.teachers[x.get("id")] = RozTeacher(x.get("id"), name, first, last, (x.get("short") or "").strip())
    for x in _find(root, "class"):
        d.classes[x.get("id")] = ((x.get("name") or x.get("short") or "").strip(), (x.get("short") or "").strip())
    groups = {x.get("id"): (x.get("name") or "", x.get("entireclass") == "1") for x in _find(root, "group")}
    lessons = {}
    for x in _find(root, "lesson"):
        lessons[x.get("id")] = x

    raw: list[RozEntry] = []
    for c in _find(root, "card"):
        les = lessons.get(c.get("lessonid"))
        if les is None:
            d.warnings.append(f"بطاقة بلا حصة معروفة: {c.get('lessonid')}")
            continue
        try:
            period = int(c.get("period") or 0)
        except ValueError:
            continue
        if period not in d.periods:
            if c.get("period"):
                d.warnings.append(f"حصة رقم {period} غير معرفة في التوقيت")
            continue
        ppc = int(les.get("periodspercard") or 1)
        last_p = period + ppc - 1
        start = d.periods[period][0]
        end = d.periods.get(last_p, d.periods[period])[1]
        days = _days(c.get("days") or daysdefs.get(les.get("daysdefid"), ""))
        subj_id = les.get("subjectid") or ""
        subj_name = d.subjects.get(subj_id, ("", ""))[0]
        teacher_ids = _ids(les.get("teacherids"))
        group_names = {}
        for gid in _ids(les.get("groupids")):
            g = groups.get(gid)
            if g and not g[1]:
                group_names[gid] = g[0]
        for cid in _ids(les.get("classids")):
            cname = d.classes.get(cid, (cid, ""))[0]
            gname = ""
            for gid in _ids(les.get("groupids")):
                if gid in group_names:
                    gname = group_names[gid]
            for day in days:
                raw.append(RozEntry(cid, cname, subj_id, subj_name, teacher_ids, day, start, end, gname))
    d.entries = merge_adjacent(raw)
    return d


def merge_adjacent(entries: list[RozEntry], max_gap: int = 15) -> list[RozEntry]:
    """دمج الحصص المتتالية لنفس الفرع/المادة/الأستاذ في اليوم نفسه (حصة متعددة الفترات)."""
    key = lambda e: (e.class_id, e.day, e.subject_id, tuple(sorted(e.teacher_ids)), e.group_name)  # noqa: E731
    out: list[RozEntry] = []
    for e in sorted(entries, key=lambda e: (key(e), e.start)):
        if out and key(out[-1]) == key(e) and 0 <= e.start - out[-1].end <= max_gap:
            out[-1].end = max(out[-1].end, e.end)
        elif out and key(out[-1]) == key(e) and e.start < out[-1].end:
            out[-1].end = max(out[-1].end, e.end)  # تكرار
        else:
            out.append(RozEntry(**e.__dict__))
    return out


def week_number_from_filename(path) -> int | None:
    m = re.search(r"(\d+)", Path(str(path)).stem)
    return int(m.group(1)) if m else None
