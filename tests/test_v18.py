"""اختبارات الإصدار 1.8 — المساعد الذكي الداخلي: المحرك المدمج (llama.cpp)، الاقتراحات بالموافقة.

لا نموذج حقيقي هنا: المحرك مستبدل بمكتبة llama_cpp وهمية، والنموذج الحقيقي يُجرَّب في GitHub Actions
(scripts/ai_eval.py والفحص الذاتي من البرنامج المبني).
"""
import sys
import types
from datetime import timedelta

import pytest

from conftest import START

from dpp.ai import actions as A
from dpp.ai import tools as T
from dpp.ai.agent import Agent
from dpp.ai.provider import AIConfig, EmbeddedProvider, find_models, make_provider

TODAY = START + timedelta(days=1)          # الإثنين من الأسبوع الأول


@pytest.fixture
def planned(seeded):
    db, ids = seeded
    from dpp.services import timetables as T2
    T2.plan_period(db, ids["formation"], time_limit=5)
    return db, ids


def _env(db, ids):
    return T.Env(db=db, formation_ids=[ids["formation"]], today=TODAY)


def _rows(db):
    return {t: db.scalar(f"SELECT COUNT(*) FROM {t}") for t in ("sessions", "session_groups", "duty_assignments")}


# ---------------------------------------------------------------- المحرك الداخلي
class _FakeLlama:
    loads = 0

    def __init__(self, model_path, n_ctx, n_threads, n_batch, verbose):
        _FakeLlama.loads += 1
        self.path = model_path

    def create_chat_completion(self, messages, stream, temperature, max_tokens):
        assert stream
        last = messages[-1]["content"]
        reply = "TOOL: today {}" if "اليوم" in last and "نتيجة" not in last else "الجواب: الأسبوع الأول."
        for i in range(0, len(reply), 4):
            yield {"choices": [{"delta": {"content": reply[i:i + 4]}}]}


@pytest.fixture
def fake_llama(monkeypatch, tmp_path):
    mod = types.ModuleType("llama_cpp")
    mod.Llama = _FakeLlama
    monkeypatch.setitem(sys.modules, "llama_cpp", mod)
    from dpp.ai import provider as P
    monkeypatch.setattr(P, "model_dirs", lambda: [tmp_path / "models"])
    P._LLM_CACHE.clear()
    (tmp_path / "models").mkdir()
    return tmp_path / "models"


def test_embedded_finds_model_and_streams(fake_llama, seeded):
    db, ids = seeded
    cfg = AIConfig()
    with pytest.raises(Exception) as ei:                        # لا ملف بعد: رسالة تذكر المجلد
        EmbeddedProvider("", cfg).models()
    assert "models" in str(ei.value) and ".gguf" in str(ei.value)
    (fake_llama / "small.gguf").write_bytes(b"x" * 100)         # ملف ناقص: يُتجاهل
    (fake_llama / "mmproj-vision.gguf").write_bytes(b"x" * 30_000_000)
    good = fake_llama / "Qwen3-4B-Instruct-Q4_K_M.gguf"
    good.write_bytes(b"x" * 30_000_000)
    assert [p.name for p in find_models(cfg)] == [good.name]
    prov = make_provider(cfg)                                   # التلقائي يختار الداخلي
    assert isinstance(prov, EmbeddedProvider) and prov.native_tools is False
    # الوكيل: صيغة الأدوات النصية مباشرة، وتحميل النموذج مرة واحدة
    _FakeLlama.loads = 0
    agent = Agent(db, cfg, [ids["formation"]], today=TODAY)
    ev = list(agent.ask("ما اليوم؟"))
    kinds = [k for k, _ in ev]
    assert ("note" in kinds) and ("tool" in kinds)
    assert agent.fallback is True
    assert ev[-1] == ("end", "الجواب: الأسبوع الأول.")
    assert "TOOL" not in "".join(p for k, p in ev if k == "text")
    list(Agent(db, cfg, [ids["formation"]], today=TODAY).ask("سؤال آخر"))
    assert _FakeLlama.loads == 1
    # قائمة الأدوات النصية تذكر المعاملات الإلزامية
    sp = Agent(db, cfg, [ids["formation"]], today=TODAY)
    sp.fallback = True
    assert "propose_move(section*, day*" in sp.system_prompt()


def test_embedded_unavailable_message(monkeypatch):
    from dpp.ai import provider as P
    monkeypatch.setitem(sys.modules, "llama_cpp", None)          # الاستيراد يفشل
    ok, why = P.embedded_status()
    assert not ok and "المحرك الداخلي" in why


# ---------------------------------------------------------------- الاقتراحات لا تكتب شيئاً
def test_proposals_never_write_then_apply_and_undo(planned):
    db, ids = planned
    env = _env(db, ids)
    sec = db.scalar("SELECT short FROM sections WHERE id=?", (ids["sections"][0],))
    before = _rows(db)
    # إضافة حصة: أقرب وقت فارغ
    out = T.run(env, "propose_add", {"section": sec, "subject": "قانون", "hours": "1"})
    assert "اقتراح رقم" in out and "لم يُنفَّذ" in out
    p = env.proposals[-1]
    assert p.kind == "add" and len(p.ops) == 1 and p.ops[0]["end"] - p.ops[0]["start"] == 60
    # نقل حصة
    from dpp.services.grid import WeekGrid
    g = WeekGrid(db, START, today=TODAY)
    c = min((c for c in g.cards.values() if ids["sections"][0] in c.sections and c.status == "planned"),
            key=lambda c: (c.day, c.start))
    day = c.day.isoformat()
    out = T.run(env, "propose_move", {"section": sec, "day": day, "start": f"{c.start // 60:02d}:{c.start % 60:02d}",
                                      "new_day": (c.day + timedelta(days=1)).isoformat()})
    assert "اقتراح رقم" in out, out
    mv = env.proposals[-1]
    # برمجة أسبوع بالمحرك، إكمال، تعارضات، خفارة، ملاحظة
    T.run(env, "propose_week_note", {"text": "أسبوع الامتحانات"})
    T.run(env, "propose_duty", {"week": START.isoformat()})
    assert _rows(db) == before                                   # لا شيء كُتب
    # التطبيق ثم التراجع
    msg = A.apply(db, p)
    assert "طُبّق" in msg and _rows(db)["sessions"] == before["sessions"] + 1
    assert A.undo(db, p) == "تم التراجع." and _rows(db)["sessions"] == before["sessions"]
    A.apply(db, mv)
    moved = db.one("SELECT date, start_min FROM sessions WHERE id=?", (mv.ops[0]["sid"],))
    assert moved["date"] == mv.ops[0]["day"] and moved["start_min"] == mv.ops[0]["start"]
    A.undo(db, mv)
    assert db.one("SELECT date FROM sessions WHERE id=?", (mv.ops[0]["sid"],))["date"] == day
    note = [x for x in env.proposals if x.kind == "note"][0]
    A.apply(db, note)
    from dpp.services import weeks as WK
    assert WK.notes(db).get(note.ws.isoformat()) == "أسبوع الامتحانات"
    A.undo(db, note)
    assert not WK.notes(db).get(note.ws.isoformat())
    with pytest.raises(A.ApplyError):
        A.undo(db, note)


def test_week_plan_uses_engine_and_focus(planned):
    db, ids = planned
    env = _env(db, ids)
    nxt = START + timedelta(days=14)
    db.execute("DELETE FROM sessions WHERE date BETWEEN ? AND ?", (nxt.isoformat(), (nxt + timedelta(days=6)).isoformat()))
    before = _rows(db)
    out = T.run(env, "propose_week_plan", {"week": nxt.isoformat(), "focus": "قانون=4"})
    assert "اقتراح رقم" in out, out
    p = env.proposals[-1]
    assert p.kind == "plan" and p.ops and "قانون 4 سا" in p.lines[1]
    assert _rows(db) == before
    A.apply(db, p)
    assert _rows(db)["sessions"] == before["sessions"] + len(p.ops)
    law = db.scalar("SELECT id FROM subjects WHERE name='قانون'")
    h = db.scalar("""SELECT SUM(s.end_min-s.start_min)/60.0 FROM sessions s JOIN session_groups sg ON sg.session_id=s.id
                     JOIN groups_ g ON g.id=sg.group_id WHERE g.section_id=? AND s.subject_id=? AND s.date BETWEEN ? AND ?""",
                  (ids["sections"][0], law, nxt.isoformat(), (nxt + timedelta(days=6)).isoformat()))
    assert h and h >= 2
    A.undo(db, p)
    assert _rows(db)["sessions"] == before["sessions"]


def test_fill_and_fix_proposals(planned):
    db, ids = planned
    env = _env(db, ids)
    sec = db.scalar("SELECT short FROM sections WHERE id=?", (ids["sections"][0],))
    # نحذف يوماً كاملاً للقسم فيصير ناقصاً
    from dpp.services.grid import WeekGrid
    g = WeekGrid(db, START, today=TODAY)
    for c in [c for c in g.cards.values() if ids["sections"][0] in c.sections and c.day == START + timedelta(days=3)]:
        g.to_tray(c)
    out = T.run(env, "propose_fill", {"section": sec, "week": START.isoformat()})
    assert "اقتراح رقم" in out or "لا ينقصه" in out
    if env.proposals:
        p = env.proposals[-1]
        spans = [(o["day"], o["start"], o["end"]) for o in p.ops]
        for (d1, a1, b1), (d2, a2, b2) in zip(spans, spans[1:]):
            assert not (d1 == d2 and a2 < b1 and a1 < b2)          # لا تداخل بين ما اقتُرح
        A.apply(db, p)
    out = T.run(env, "propose_fix_conflicts", {"week": START.isoformat()})
    assert "اقتراح" in out or "لا توجد تعارضات" in out


def test_agent_yields_proposal_event(planned):
    db, ids = planned
    sec = db.scalar("SELECT short FROM sections WHERE id=?", (ids["sections"][0],))

    class Fake:
        kind = "fake"
        native_tools = False

        def __init__(self):
            self.n = 0
            self.cfg = AIConfig(model="fake")

        def models(self):
            return ["fake"]

        def chat(self, messages, tools=None, cancel=None):
            self.n += 1
            txt = (f'TOOL: propose_add {{"section": "{sec}", "subject": "قانون", "hours": "2"}}' if self.n == 1
                   else "الاقتراح جاهز، اضغط «تطبيق».")
            yield ("text", txt)
            yield ("end", {"content": txt, "tool_calls": []})

    agent = Agent(db, AIConfig(model="fake"), [ids["formation"]], today=TODAY, provider=Fake())
    ev = list(agent.ask("زيد حصة قانون"))
    props = [p for k, p in ev if k == "proposal"]
    assert len(props) == 1 and props[0].kind == "add"
    assert any(k == "tool" and p.startswith("يُعدّ اقتراحاً") for k, p in ev)
    assert ev[-1] == ("end", "الاقتراح جاهز، اضغط «تطبيق».")


def test_proposal_card_ui(planned, monkeypatch):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    db, ids = planned
    from dpp.ui.context import AppContext
    from dpp.ui.pages.assistant import AssistantPage, ProposalCard
    page = AssistantPage(AppContext(db))
    env = _env(db, ids)
    T.run(env, "propose_week_note", {"text": "ملاحظة من المساعد"})
    card = ProposalCard(env.proposals[-1], page)
    card.apply()
    from dpp.services import weeks as WK
    assert WK.notes(db)[env.proposals[-1].ws.isoformat()] == "ملاحظة من المساعد"
    assert not card.b_apply.isVisible() and "حُفظت" in card.status.text()
    card.undo()
    assert "تم التراجع" in card.status.text()
    page.shutdown()
    app.processEvents()
