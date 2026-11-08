"""بيانات اختبار منفصلة — لا تُستعمل في قاعدة بيانات المؤسسة الحقيقية."""
from __future__ import annotations

from datetime import date, timedelta

from .db.database import Database
from .utils import iso, week_start


def seed(db: Database, start: date | None = None, weeks: int = 4, sections: int = 3) -> dict:
    start = week_start(start or date(2026, 11, 1))
    end = start + timedelta(days=7 * weeks - 1)
    ids: dict = {}
    with db.tx():
        f = db.insert("formations", name="تكوين تجريبي", short="TEST", start_date=iso(start), end_date=iso(end),
                      rest_days="5,6")
        ids["formation"] = f
        lvl = db.insert("levels", formation_id=f, name="الطور الأول", short="L1")
        subj = {}
        for name, short, color, share in [("لغة فرنسية", "FR", "#3E7CB1", 0), ("إعلام آلي", "INF", "#2A9D8F", 0),
                                          ("تربية بدنية", "EPS", "#E76F51", 1), ("قانون", "DRT", "#8E6C8A", 0),
                                          ("محاضرات وندوات", "CONF", "#F4A261", 1)]:
            subj[short] = db.insert("subjects", name=name, short=short, color=color, shareable=share)
        ids["subjects"] = subj
        rooms = [db.insert("rooms", name=f"القاعة {i}", short=f"S{i}", capacity=30) for i in range(1, 4)]
        ids["rooms"] = rooms
        cat = db.scalar("SELECT id FROM teacher_categories WHERE name='عسكري'")
        teachers = {}
        for name, rank, quals in [("أحمد بن علي", "مساعد", ["FR"]), ("سامية قاسمي", "م م م", ["FR", "DRT"]),
                                  ("كريم عيسو", "رقيب أول", ["INF"]), ("ليلى حمزي", "أ ت ج", ["INF"]),
                                  ("يوسف طويل", "مساعد أول", ["EPS"]), ("مراد بودراس", "ملازم أول", ["DRT", "CONF"])]:
            t = db.insert("teachers", full_name=name, rank=rank, category_id=cat)
            teachers[name] = t
            for q in quals:
                db.execute("INSERT INTO teacher_subjects VALUES (?,?)", (t, subj[q]))
        ids["teachers"] = teachers
        ids["sections"], ids["groups"], ids["subgroups"] = [], [], []
        for i in range(1, sections + 1):
            sec = db.insert("sections", formation_id=f, level_id=lvl, name=f"القسم {i}", short=f"BMP{i}", size=24)
            g = db.insert("groups_", section_id=sec, name="الفوج الكامل", short="ALL", is_whole=1, size=24)
            g1 = db.insert("groups_", section_id=sec, name="مجموعة 1", short="G1", size=12)
            g2 = db.insert("groups_", section_id=sec, name="مجموعة 2", short="G2", size=12)
            ids["sections"].append(sec)
            ids["groups"].append(g)
            ids["subgroups"] += [g1, g2]
            for short, wh, mins, room, teacher in [("FR", 4, 120, 1, None), ("DRT", 3, 90, 1, None),
                                                   ("EPS", 2, 120, 0, "يوسف طويل")]:
                db.insert("requirements", formation_id=f, group_id=g, subject_id=subj[short],
                          teacher_id=teachers.get(teacher), weekly_hours=wh, total_hours=wh * weeks,
                          session_minutes=mins, needs_room=room,
                          share_code="EPS-ALL" if short == "EPS" else None)
            for sg in (g1, g2):   # الإعلام الآلي بالمجموعات
                db.insert("requirements", formation_id=f, group_id=sg, subject_id=subj["INF"], weekly_hours=2,
                          total_hours=2 * weeks, session_minutes=120, needs_room=1)
    return ids
