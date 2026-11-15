"""تجربة المساعد الذكي بنموذج حقيقي (تُشغَّل في GitHub Actions على Windows، أو محلياً):

    python scripts/ai_eval.py path/to/model.gguf

تنشئ قاعدة تجريبية، تبرمج أسابيعها، ثم تطرح أسئلة حقيقية (فصحى ودارجة، قراءة واقتراح تعديل)
وتطبع لكل سؤال: الأدوات المنادى عليها، الجواب، الاقتراحات، والزمن. لا تقيّم الجودة آلياً
إلا في حدود دنيا (جواب غير فارغ)، والغرض أن يُقرأ السجل.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QUESTIONS = [
    "ما هو اليوم ورقم الأسبوع؟",
    "واش هوما الحصص تاع القسم الأول نهار الإثنين؟",
    "ما المواد المتأخرة عن المقرر؟",
    "هل يوجد تعارض هذا الأسبوع؟",
    "اكتب ملاحظة قصيرة لهذا الأسبوع تلخّص عدد الحصص.",
    "انقل أول حصة للقسم الأول يوم الأحد إلى يوم الثلاثاء.",
    "زيد حصة ساعتين لمادة القانون للقسم الأول هذا الأسبوع.",
]


def main(model: str) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="dpp_ai_eval_"))
    os.environ["DPP_DATA_DIR"] = str(tmp)
    from dpp.ai.agent import Agent
    from dpp.ai.provider import AIConfig
    from dpp.db.database import Database
    from dpp.demo import seed
    from dpp.services import timetables as T
    db = Database(tmp / "dpp.sqlite")
    ids = seed(db, start=date(2026, 11, 1), weeks=3)
    T.plan_period(db, ids["formation"], time_limit=10)
    names = [r[0] for r in db.q("SELECT short FROM sections ORDER BY id")]
    print("الأقسام:", names, flush=True)
    cfg = AIConfig(kind="embedded", model_path=model, num_ctx=8192, max_tokens=500)
    failures = 0
    t_load = time.time()
    for q in QUESTIONS:
        q = q.replace("القسم الأول", f"القسم {names[0]}")
        agent = Agent(db, cfg, [ids["formation"]], today=date(2026, 11, 2))
        t0 = time.time()
        text, tools, props, notes = [], [], [], []
        try:
            for kind, payload in agent.ask(q):
                if kind == "text":
                    text.append(payload)
                elif kind == "tool":
                    tools.append(payload)
                elif kind == "note":
                    notes.append(payload)
                elif kind == "proposal":
                    props.append(payload)
        except Exception as e:                                # noqa: BLE001
            text.append(f"[خطأ] {type(e).__name__}: {e}")
            failures += 1
        dt = time.time() - t0
        ans = "".join(text).strip()
        if not ans:
            failures += 1
        print("=" * 70, flush=True)
        print(f"س: {q}", flush=True)
        print(f"الأدوات: {tools or '—'}", flush=True)
        if notes:
            print(f"ملاحظات: {notes}", flush=True)
        print(f"ج ({dt:.1f} ث): {ans}", flush=True)
        for p in props:
            print(f"   اقتراح {p.id}: {p.title} | {p.lines[:4]} | تحذيرات: {p.warnings[:2]}", flush=True)
    print("=" * 70)
    print(f"المجموع: {len(QUESTIONS)} سؤالاً، {failures} بلا جواب، الزمن الكلي {time.time() - t_load:.0f} ث")
    return 0 if failures < len(QUESTIONS) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
