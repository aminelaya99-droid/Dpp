"""المقرر: قالب Excel، الاستيراد مع المطابقة التقريبية، الإدخال اليدوي، وتدقيق النواقص."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from dpp.models import (SUBJECT_GENERAL, SUBJECT_KINDS, SUBJECT_MILITARY, Alert, CurriculumItem, Lesson,
                        Level, Phase, Specialty, Subject, Training)
from dpp.services import catalog, structure
from dpp.services.textnorm import best_match, normalize, similarity

HEADERS = ["التكوين", "الطور", "الاختصاص", "المادة", "النوع", "المرحلة", "الحجم الساعي"]
AUTO_MATCH = 0.92     # مطابقة تلقائية
DOUBT_MATCH = 0.70    # مشكوك فيها: تُطلب مراجعة
TOTAL_WORDS = {"المجموع", "مجموع", "المجموع العام", "total", "totale"}
KIND_BY_LABEL = {normalize(v): k for k, v in SUBJECT_KINDS.items()}
KIND_BY_LABEL.update({"عسكري": SUBJECT_MILITARY, "عام": SUBJECT_GENERAL, "تخصصي": "specialized",
                      "military": SUBJECT_MILITARY, "general": SUBJECT_GENERAL, "specialized": "specialized"})


# ------------------------------------------------------------------ القالب
def write_template(s: Session, path: str | Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "المقرر"
    ws.sheet_view.rightToLeft = True
    head_fill = PatternFill("solid", fgColor="15803D")
    thin = Side(style="thin", color="CBD5E1")
    for c, h in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
    widths = [14, 12, 24, 36, 12, 26, 14]
    for i, w in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = w
    ws.freeze_panes = "A2"
    # أمثلة من الهيكل الحالي
    row = 2
    for t in structure.trainings(s):
        for lv in t.levels:
            ph = t.phases[0].name if t.phases else ""
            sp = lv.specialties[0].name if lv.specialties else ""
            ws.append([t.code, lv.code, sp, "", "", ph if lv.curriculum_scope == "phase" else "", None])
            row += 1
            break
    kinds = DataValidation(type="list", formula1='"' + ",".join(SUBJECT_KINDS.values()) + '"', allow_blank=True)
    ws.add_data_validation(kinds)
    kinds.add("E2:E2000")
    hours = DataValidation(type="decimal", operator="between", formula1="0", formula2="5000", allow_blank=True)
    ws.add_data_validation(hours)
    hours.add("G2:G2000")
    # ورقة التعليمات
    info = wb.create_sheet("تعليمات")
    info.sheet_view.rightToLeft = True
    lines = [
        "قالب المقرر — برنامج DPP",
        "كل سطر = مادة لاختصاص (ولمرحلة إن كان المقرر لكل مرحلة).",
        "التكوين: الرمز (BMP، ESOC، RES) أو الاسم. الطور: الرمز (BMP1، ESOC 1، OF-R ...).",
        "الاختصاص: اتركه فارغاً للمواد العسكرية والعامة ليُطبق على كل اختصاصات الطور.",
        "النوع: عسكرية / تخصصية / عامة (اختياري، يُخمن من اسم المادة إن تُرك فارغاً).",
        "المرحلة: اسم المرحلة من المخطط الزمني؛ فارغ = لكامل التكوين.",
        "الحجم الساعي: بالساعات. سطر «المجموع» في عمود المادة يُستعمل للتحقق من المجاميع.",
        "الخانات الناقصة تُترك فارغة وتظهر تنبيهات داخل البرنامج.",
    ]
    for i, ln in enumerate(lines, 1):
        info.cell(row=i, column=1, value=ln).font = Font(bold=(i == 1), size=12 if i == 1 else 11)
    info.column_dimensions["A"].width = 100
    out = Path(path)
    wb.save(out)
    return out


# ------------------------------------------------------------------ الاستيراد
@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    doubtful: int = 0
    new_subjects: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"أُضيف {self.created}، حُدّث {self.updated}، مطابقات للمراجعة {self.doubtful}، "
                f"مواد جديدة {len(self.new_subjects)}، تنبيهات {len(self.alerts)}")


def _alert(s: Session, res: ImportResult | None, msg: str, category="curriculum", severity="warning",
           payload: dict | None = None) -> None:
    s.add(Alert(category=category, severity=severity, message=msg,
                payload=json.dumps(payload or {}, ensure_ascii=False)))
    if res is not None:
        res.alerts.append(msg)


def _match_name(name: str, objs, attrs=("name", "code")):
    key = normalize(name)
    if not key:
        return None, 0.0
    best, score = None, 0.0
    for o in objs:
        for a in attrs:
            v = getattr(o, a, "") or ""
            sc = similarity(name, v) if v else 0
            if v and normalize(v) == key:
                sc = 1.0
            if sc > score:
                best, score = o, sc
    return best, score


def _cell(v) -> str:
    return "" if v is None else str(v).strip()


def import_excel(s: Session, path: str | Path) -> ImportResult:
    res = ImportResult()
    wb = load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return res
    header = [normalize(_cell(h)) for h in rows[0]]
    idx = {}
    for i, h in enumerate(HEADERS):
        nh = normalize(h)
        for j, x in enumerate(header):
            if x == nh or (x and (nh in x or x in nh)):
                idx[i] = j
                break
    if 3 not in idx or 6 not in idx:
        raise ValueError("الملف لا يطابق القالب: عمودا «المادة» و«الحجم الساعي» مطلوبان")
    trainings = structure.trainings(s)
    totals: dict[tuple, float] = {}
    sums: dict[tuple, float] = {}
    last_ctx: dict = {}
    for rno, row in enumerate(rows[1:], start=2):
        get = lambda i: _cell(row[idx[i]]) if i in idx and idx[i] < len(row) else ""  # noqa: E731
        t_name, lv_name, sp_name, subj_name, kind_lbl, ph_name, hours_raw = (get(i) for i in range(7))
        if not any((t_name, lv_name, sp_name, subj_name, hours_raw)):
            continue
        # السياق: الخانات الفارغة للتكوين/الطور ترث السطر السابق (خلايا مدمجة في الأصل)
        t_name = t_name or last_ctx.get("t", "")
        lv_name = lv_name or last_ctx.get("lv", "")
        last_ctx.update(t=t_name, lv=lv_name)
        training, sc = _match_name(t_name, trainings, ("code", "name"))
        if training is None or sc < 0.8:
            if len(trainings) == 1:
                training = trainings[0]
            else:
                _alert(s, res, f"السطر {rno}: تكوين غير معروف «{t_name}»", severity="error")
                continue
        level, sc = _match_name(lv_name, training.levels, ("code", "name"))
        if level is None or sc < 0.8:
            _alert(s, res, f"السطر {rno}: طور غير معروف «{lv_name}» في {training.code}", severity="error")
            continue
        try:
            hours = float(str(hours_raw).replace(",", ".")) if hours_raw != "" else None
        except ValueError:
            hours = None
            _alert(s, res, f"السطر {rno}: حجم ساعي غير صالح «{hours_raw}»")
        phase = None
        if ph_name:
            phase, sc = _match_name(ph_name, training.phases, ("name",))
            if phase is None or sc < 0.75:
                _alert(s, res, f"السطر {rno}: مرحلة غير معروفة «{ph_name}» — اعتُبر المقرر لكامل التكوين")
                phase = None
        elif level.curriculum_scope == "phase":
            _alert(s, res, f"السطر {rno}: المرحلة غير محددة والطور {level.code} مقرره لكل مرحلة")
        # الاختصاصات
        kind = KIND_BY_LABEL.get(normalize(kind_lbl)) if kind_lbl else None
        if sp_name:
            sp, sc = _match_name(sp_name, level.specialties, ("name", "code"))
            if sp is None or sc < 0.8:
                _alert(s, res, f"السطر {rno}: اختصاص غير واضح «{sp_name}» في {level.code}")
                continue
            specialties = [sp]
        else:
            specialties = list(level.specialties)
            guessed = kind or (catalog.guess_kind(subj_name) if subj_name else None)
            if guessed == "specialized" and subj_name:
                _alert(s, res, f"السطر {rno}: مادة تخصصية «{subj_name}» بلا اختصاص")
                continue
            if not specialties:
                _alert(s, res, f"السطر {rno}: الطور {level.code} لا يحتوي اختصاصات")
                continue
        # سطر المجموع
        if normalize(subj_name) in {normalize(w) for w in TOTAL_WORDS}:
            for sp in specialties:
                if hours is not None:
                    totals[(sp.id, phase.id if phase else None)] = hours
            continue
        if not subj_name:
            _alert(s, res, f"السطر {rno}: مادة ناقصة (اسم المادة فارغ)")
            continue
        # مطابقة المادة
        subjects = {x.id: x.name for x in catalog.subjects(s)}
        sid, score = best_match(subj_name, subjects)
        doubtful = False
        if sid is not None and score >= AUTO_MATCH:
            subject = s.get(Subject, sid)
        elif sid is not None and score >= DOUBT_MATCH:
            subject = s.get(Subject, sid)
            doubtful = True
        else:
            subject = catalog.get_or_create_subject(s, subj_name, kind=kind)
            res.new_subjects.append(subject.name)
        if kind and subject.kind != kind and not doubtful:
            subject.kind = kind
        if subject.kind == "specialized" and len(specialties) == 1 and subject.specialty_id is None:
            subject.specialty_id = specialties[0].id
        if hours is None:
            _alert(s, res, f"السطر {rno}: الحجم الساعي ناقص لـ «{subj_name}»")
        for sp in specialties:
            item = find_item(s, sp.id, subject.id, phase.id if phase else None)
            if item is None:
                item = CurriculumItem(specialty_id=sp.id, subject_id=subject.id,
                                      phase_id=phase.id if phase else None, hours=hours, source_name=subj_name)
                s.add(item)
                res.created += 1
            else:
                item.hours, item.source_name = hours, subj_name
                res.updated += 1
            s.flush()
            key = (sp.id, phase.id if phase else None)
            sums[key] = sums.get(key, 0) + (hours or 0)
            if doubtful:
                res.doubtful += 1
                _alert(s, None, f"مطابقة مشكوك فيها: «{subj_name}» ← «{subject.name}» ({score:.0%})",
                       category="match", severity="info",
                       payload={"item_id": item.id, "raw": subj_name, "subject_id": subject.id})
    for key, total in totals.items():
        got = sums.get(key, 0)
        if abs(got - total) > 0.01:
            sp = s.get(Specialty, key[0])
            _alert(s, res, f"عدم تطابق المجاميع في «{sp.name}»: المجموع المكتوب {total:g} سا، "
                           f"ومجموع المواد {got:g} سا")
    s.commit()
    return res


# ------------------------------------------------------------------ المراجعة
def pending_matches(s: Session) -> list[Alert]:
    return list(s.scalars(select(Alert).where(Alert.category == "match", Alert.resolved.is_(False))))


def resolve_match(s: Session, alert: Alert, subject: Subject | None = None, create_new: bool = False) -> None:
    """قبول المطابقة، أو ربط البند بمادة أخرى، أو إنشاء مادة جديدة من الاسم الأصلي."""
    data = json.loads(alert.payload or "{}")
    item = s.get(CurriculumItem, data.get("item_id"))
    if item is not None:
        if create_new:
            subject = Subject(name=data["raw"], kind=catalog.guess_kind(data["raw"]))
            s.add(subject)
            s.flush()
        if subject is not None:
            item.subject_id = subject.id
    alert.resolved = True
    s.commit()


# ------------------------------------------------------------------ التدقيق
def audit(s: Session) -> list[str]:
    """تنبيهات النواقص: مواد عسكرية/عامة غير موحدة بين اختصاصات الطور، مواد مُدرَّسة خارج المقرر،
    بنود بلا حجم ساعي."""
    s.execute(delete(Alert).where(Alert.category == "audit"))
    msgs: list[str] = []
    for t in structure.trainings(s):
        for lv in t.levels:
            specs = lv.specialties
            if not specs:
                continue
            items_by_sp = {sp.id: list(s.scalars(select(CurriculumItem).where(CurriculumItem.specialty_id == sp.id)))
                           for sp in specs}
            if not any(items_by_sp.values()):
                continue
            common: dict[int, set[int]] = {}
            for sp_id, items in items_by_sp.items():
                for it in items:
                    if it.subject.kind in (SUBJECT_MILITARY, SUBJECT_GENERAL):
                        common.setdefault(it.subject_id, set()).add(sp_id)
                    if it.hours is None:
                        msgs.append(f"{lv.code} / {it.specialty.name}: الحجم الساعي ناقص لـ «{it.subject.name}»")
            for subj_id, have in common.items():
                missing = [sp for sp in specs if sp.id not in have and items_by_sp[sp.id]]
                if missing:
                    subj = s.get(Subject, subj_id)
                    msgs.append(f"{lv.code}: المادة «{subj.name}» ({SUBJECT_KINDS[subj.kind]}) ناقصة في: "
                                + "، ".join(sp.name for sp in missing))
            for sp in specs:
                if not items_by_sp[sp.id]:
                    continue
                planned = {it.subject_id for it in items_by_sp[sp.id]}
                taught = set(s.scalars(select(Lesson.subject_id).where(
                    Lesson.section_id.in_([x.id for x in sp.sections]), Lesson.subject_id.is_not(None)).distinct()))
                for subj_id in taught - planned:
                    subj = s.get(Subject, subj_id)
                    if subj and not subj.allow_shared:
                        msgs.append(f"{lv.code} / {sp.name}: «{subj.name}» مُدرَّسة لكنها غير موجودة في المقرر")
    for m in msgs:
        s.add(Alert(category="audit", severity="warning", message=m))
    s.commit()
    return msgs


def find_item(s: Session, specialty_id: int, subject_id: int, phase_id: int | None) -> CurriculumItem | None:
    q = select(CurriculumItem).where(CurriculumItem.specialty_id == specialty_id,
                                     CurriculumItem.subject_id == subject_id)
    q = q.where(CurriculumItem.phase_id == phase_id) if phase_id else q.where(CurriculumItem.phase_id.is_(None))
    return s.scalar(q)


def items_for(s: Session, specialty_id: int) -> list[CurriculumItem]:
    return list(s.scalars(select(CurriculumItem).where(CurriculumItem.specialty_id == specialty_id)))
