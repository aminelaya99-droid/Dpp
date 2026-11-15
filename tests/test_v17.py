"""اختبارات الإصدار 1.7 — المساعد الذكي المحلي.

لا يُنادى أي نموذج حقيقي هنا: المزوّد مُستبدل بمزوّد وهمي، حتى تبقى الاختبارات سريعة
وتعمل على GitHub Actions بلا تنصيب Ollama.
"""
import copy
import json
import time
from datetime import timedelta

import pytest

from conftest import START

from dpp.ai import tools as T
from dpp.ai.agent import Agent, ThinkFilter, Turn, _parse_text_calls
from dpp.ai.provider import (AIConfig, AIError, OllamaProvider, OpenAIProvider, load_config, make_provider,
                             save_config)

TODAY = START + timedelta(days=9)          # ثلاثاء داخل المدى المزروع


# ---------------------------------------------------------------- تجهيز
def _fill(db, ids):
    """حصص حقيقية في قاعدة الاختبار + مقرر، حتى تكون للأدوات بيانات تقرأها."""
    f = ids["formation"]
    ws = START + timedelta(days=7)
    tt = db.insert("timetables", formation_id=f, week_start=ws.strftime("%Y-%m-%d"), status="draft")
    subj, teach, rooms = ids["subjects"], ids["teachers"], ids["rooms"]
    plan = [(2, 480, 600, "FR", "أحمد بن علي", 0), (2, 600, 720, "INF", "كريم عيسو", 1),
            (3, 480, 600, "DRT", "سامية قاسمي", 0), (4, 780, 900, "EPS", "يوسف طويل", 2)]
    lvl = db.scalar("SELECT level_id FROM sections WHERE id=?", (ids["sections"][0],))
    for day, a, b, sub, who, room in plan:
        d = ws + timedelta(days=day)
        sid = db.insert("sessions", timetable_id=tt, date=d.strftime("%Y-%m-%d"), start_min=a, end_min=b,
                        subject_id=subj[sub], teacher_id=teach[who], room_id=rooms[room], status="done")
        db.execute("INSERT INTO session_groups VALUES (?,?)", (sid, ids["groups"][0]))
    for sub, hours in (("FR", 40), ("INF", 20), ("DRT", 30)):
        db.insert("curriculum", level_id=lvl, specialty_id=0, subject_id=subj[sub], phase="all", hours=hours)
    db.commit()
    return tt


def _env(db, ids):
    return T.Env(db=db, formation_ids=[ids["formation"]], today=TODAY)


class FakeProvider:
    """مزوّد وهمي: يبثّ نصاً حرفاً حرفاً ثم يطلب أدوات، حسب سيناريو معطى."""

    kind = "fake"

    def __init__(self, script, *, fail_tools=False):
        self.script = list(script)
        self.fail_tools = fail_tools
        self.seen = []
        self.cfg = AIConfig(model="fake")

    def models(self):
        return ["fake"]

    def ping(self):
        return True

    def chat(self, messages, tools=None, cancel=None):
        self.seen.append((copy.deepcopy(messages), bool(tools)))
        if self.fail_tools and tools:
            raise AIError("model does not support tools", no_tools=True)
        step = self.script.pop(0) if self.script else {"text": "لا مزيد."}
        text = step.get("text", "")
        for ch in text:
            yield ("text", ch)
        yield ("end", {"content": text, "tool_calls": step.get("calls", [])})


class FakeResp:
    def __init__(self, lines):
        self.lines = [line.encode("utf-8") + b"\n" for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self.lines)

    def read(self):
        return b"".join(self.lines)


# ---------------------------------------------------------------- الإعدادات
def test_config_roundtrip_and_bad_json(db):
    cfg = load_config(db)
    assert cfg.kind == "auto" and cfg.enabled and cfg.num_ctx == 4096
    cfg.model, cfg.temperature, cfg.use_tools = "qwen3:4b", 0.5, False
    save_config(db, cfg)
    again = load_config(db)
    assert (again.model, again.temperature, again.use_tools) == ("qwen3:4b", 0.5, False)
    db.set_setting("ai_config", "{ليس JSON")
    assert load_config(db).model == ""              # يرجع إلى الافتراضي بلا انفجار
    db.set_setting("ai_config", json.dumps({"model": "x", "غريب": 1}))
    assert load_config(db).model == "x"             # المفاتيح المجهولة تُتجاهل
    assert cfg.url().startswith("http://127.0.0.1")


# ---------------------------------------------------------------- الأدوات
def test_every_tool_returns_arabic_text(seeded):
    db, ids = seeded
    _fill(db, ids)
    env = _env(db, ids)
    cases = [
        ("today", {}), ("find", {"kind": "teacher", "name": "أحمد"}),
        ("schedule", {"scope": "all", "week": "2026-11-08"}),
        ("schedule", {"scope": "section", "name": "BMP1", "week": "2026-11-08"}),
        ("schedule", {"scope": "teacher", "name": "أحمد بن علي", "week": "2026-11-08"}),
        ("schedule", {"scope": "room", "name": "القاعة 1", "week": "2026-11-08"}),
        ("free", {"kind": "teacher", "date": "2026-11-10", "start": "08:00", "end": "10:00"}),
        ("free", {"kind": "room", "date": "الثلاثاء"}),
        ("progress", {}), ("progress", {"section": "BMP1"}),
        ("late", {}), ("conflicts", {"week": "2026-11-08"}), ("duty", {}), ("status", {}),
    ]
    for name, args in cases:
        out = T.run(env, name, args)
        assert out and isinstance(out, str), name
        assert "تعذّر تنفيذ" not in out, f"{name} ← {out}"
        assert "Traceback" not in out, name
    sched = T.run(env, "schedule", {"scope": "section", "name": "BMP1", "week": "2026-11-08"})
    assert "لغة فرنسية" in sched and "أحمد بن علي" in sched and "08:00-10:00" in sched
    prog = T.run(env, "progress", {"section": "BMP1"})
    assert "لغة فرنسية" in prog and "/40" in prog
    assert len(T.specs()) == len(T.REGISTRY) >= 9
    for spec in T.specs():
        fn = spec["function"]
        assert fn["name"] and fn["description"] and fn["parameters"]["type"] == "object"
        assert set(fn["parameters"]["required"]) <= set(fn["parameters"]["properties"])


def test_tools_never_write_to_database(seeded):
    db, ids = seeded
    _fill(db, ids)
    env = _env(db, ids)
    tables = ("sessions", "session_groups", "timetables", "teachers", "sections", "audit_log", "curriculum",
              "settings", "hours_adjust")
    before = {t: db.scalar(f"SELECT COUNT(*) FROM {t}", default=0) for t in tables}
    for name in T.REGISTRY:
        T.run(env, name, {"kind": "teacher", "name": "أحمد", "scope": "all"})
    after = {t: db.scalar(f"SELECT COUNT(*) FROM {t}", default=0) for t in tables}
    assert before == after


def test_tool_errors_are_helpful_messages(seeded):
    db, ids = seeded
    env = _env(db, ids)
    assert "لا توجد أداة" in T.run(env, "nope", {})
    bad = T.run(env, "schedule", {"scope": "section", "name": "قسم غير موجود"})
    assert "لا يوجد قسم" in bad and "القسم 1" in bad          # يقترح الأسماء الموجودة
    assert "08:00" in T.run(env, "free", {"kind": "teacher", "start": "صباحاً"})
    assert "بعد البداية" in T.run(env, "free", {"kind": "teacher", "start": "10:00", "end": "09:00"})
    assert "2026-11-08" in T.run(env, "schedule", {"scope": "all", "week": "أمس"}) or \
           "لم أفهم" in T.run(env, "schedule", {"scope": "all", "week": "أمس"})
    many = T.run(env, "schedule", {"scope": "section", "name": "القسم"})
    assert "أكثر من" in many or "القسم 1" in many
    assert "حدّد الاسم" in T.run(env, "schedule", {"scope": "teacher"})


def test_week_and_day_parsing(seeded):
    db, ids = seeded
    env = _env(db, ids)
    db.set_setting("week1_start", "2026-09-13")
    out = T.run(env, "today", {})
    assert "الأسبوع رقم 9" in out and "2026-11-08" in out
    assert "2026-11-08" in T.run(env, "schedule", {"scope": "all", "week": "9"})
    assert "الخميس" in T.run(env, "schedule", {"scope": "all", "day": "الخميس"})


# ---------------------------------------------------------------- الحلقة
def test_agent_calls_tool_then_answers(seeded):
    db, ids = seeded
    _fill(db, ids)
    fake = FakeProvider([{"text": "", "calls": [{"name": "today", "args": {}}]},
                         {"text": "الأسبوع رقم 9 يبدأ الأحد."}])
    agent = Agent(db, AIConfig(model="fake"), [ids["formation"]], today=TODAY, provider=fake)
    events = list(agent.ask("ما هو الأسبوع الحالي؟"))
    kinds = [k for k, _ in events]
    assert "tool" in kinds and kinds[-1] == "end"
    assert events[-1][1] == "الأسبوع رقم 9 يبدأ الأحد."
    assert "".join(p for k, p in events if k == "text") == "الأسبوع رقم 9 يبدأ الأحد."
    # نتيجة الأداة وُضعت في رسائل الدورة الثانية
    second = fake.seen[1][0]
    assert any("نتيجة الأداة today" in m["content"] for m in second)
    assert any("الأسبوع رقم 9" in m["content"] for m in second)
    assert fake.seen[0][1] is True                       # أُرسلت مواصفات الأدوات


def test_agent_stops_after_max_rounds(seeded):
    db, ids = seeded
    loop = [{"text": "", "calls": [{"name": "today", "args": {}}]}] * 10
    cfg = AIConfig(model="fake", max_rounds=3)
    fake = FakeProvider(loop)
    agent = Agent(db, cfg, [ids["formation"]], today=TODAY, provider=fake)
    list(agent.ask("سؤال"))
    assert len(fake.seen) == 3


def test_agent_falls_back_to_text_protocol(seeded):
    db, ids = seeded
    _fill(db, ids)
    fake = FakeProvider([{"text": "TOOL: today {}"}, {"text": "الجواب النهائي."}], fail_tools=True)
    agent = Agent(db, AIConfig(model="fake"), [ids["formation"]], today=TODAY, provider=fake)
    events = list(agent.ask("ما اليوم؟"))
    assert agent.fallback is True
    assert events[-1] == ("end", "الجواب النهائي.")
    notes = [p for k, p in events if k == "note"]
    assert any("الصيغة النصية" in n for n in notes)
    # في الصيغة النصية لا تُرسل مواصفات الأدوات، وتُشرح في رسالة النظام
    assert fake.seen[-1][1] is False
    assert "TOOL:" in fake.seen[-1][0][0]["content"]
    # ولا يظهر سطر مناداة الأداة للمستخدم
    assert "TOOL:" not in "".join(p for k, p in events if k == "text")


def test_agent_hides_think_block(seeded):
    db, ids = seeded
    fake = FakeProvider([{"text": "<think>حساب داخلي طويل</think>الجواب: 3 أقسام."}])
    agent = Agent(db, AIConfig(model="fake"), [ids["formation"]], today=TODAY, provider=fake)
    events = list(agent.ask("كم قسماً؟"))
    assert events[-1][1] == "الجواب: 3 أقسام."
    assert "حساب داخلي" not in "".join(p for k, p in events if k == "text")
    assert any("يفكّر" in p for k, p in events if k == "note")


def test_agent_can_be_cancelled(seeded):
    db, ids = seeded
    fake = FakeProvider([{"text": "جواب طويل جداً"}] * 5)
    agent = Agent(db, AIConfig(model="fake", max_rounds=5), [ids["formation"]], today=TODAY, provider=fake)
    out = list(agent.ask("سؤال", cancel=lambda: True))
    assert out == [("end", "")] and not fake.seen


def test_think_filter_and_call_parser():
    f = ThinkFilter()
    assert "".join(f.feed(c) for c in "أ<think>خفي</think>ب") + f.flush() == "أب"
    assert f.thought is True
    assert _parse_text_calls('TOOL: schedule {"scope": "all"}')[0] == [{"name": "schedule", "args": {"scope": "all"}}]
    assert _parse_text_calls("أداة: today")[0] == [{"name": "today", "args": {}}]
    assert _parse_text_calls("TOOL: غير_موجودة {}") == ([], "TOOL: غير_موجودة {}")
    assert _parse_text_calls("جواب عادي") == ([], "جواب عادي")


def test_agent_history_is_trimmed(seeded):
    db, ids = seeded
    fake = FakeProvider([{"text": "تم."}])
    cfg = AIConfig(model="fake", history=2)
    agent = Agent(db, cfg, [ids["formation"]], today=TODAY, provider=fake)
    hist = [Turn("user", f"س{i}") for i in range(10)]
    list(agent.ask("السؤال الأخير", hist))
    msgs = fake.seen[0][0]
    assert len(msgs) == 4 and msgs[0]["role"] == "system" and msgs[-1]["content"] == "السؤال الأخير"
    assert [m["content"] for m in msgs[1:3]] == ["س8", "س9"]


# ---------------------------------------------------------------- المزوّدون
def test_ollama_stream_and_tool_calls(monkeypatch):
    from dpp.ai import provider as P
    lines = [json.dumps({"message": {"content": "سلا"}}, ensure_ascii=False),
             json.dumps({"message": {"content": "م"}}, ensure_ascii=False),
             json.dumps({"message": {"content": "", "tool_calls": [
                 {"function": {"name": "today", "arguments": {"x": 1}}}]}}, ensure_ascii=False),
             json.dumps({"done": True})]
    seen = {}

    def fake_request(url, payload=None, timeout=30, stream=False):
        seen["url"], seen["payload"] = url, payload
        return FakeResp(lines)
    monkeypatch.setattr(P, "_request", fake_request)
    prov = P.OllamaProvider("http://127.0.0.1:11434", AIConfig(model="qwen3:4b", num_ctx=2048))
    out = list(prov.chat([{"role": "user", "content": "مرحبا"}], tools=[{"type": "function"}]))
    assert [p for k, p in out if k == "text"] == ["سلا", "م"]
    end = out[-1][1]
    assert end["content"] == "سلام" and end["tool_calls"] == [{"name": "today", "args": {"x": 1}}]
    assert seen["url"].endswith("/api/chat")
    assert seen["payload"]["options"] == {"temperature": 0.2, "num_ctx": 2048}
    assert seen["payload"]["stream"] is True and seen["payload"]["model"] == "qwen3:4b"


def test_openai_stream_and_tool_calls(monkeypatch):
    from dpp.ai import provider as P
    lines = ["data: " + json.dumps({"choices": [{"delta": {"content": "نعم"}}]}, ensure_ascii=False),
             "data: " + json.dumps({"choices": [{"delta": {"tool_calls": [
                 {"index": 0, "function": {"name": "sched", "arguments": '{"scope":'}}]}}]}),
             "data: " + json.dumps({"choices": [{"delta": {"tool_calls": [
                 {"index": 0, "function": {"arguments": '"all"}'}}]}}]}),
             "data: [DONE]"]
    monkeypatch.setattr(P, "_request", lambda url, payload=None, timeout=30, stream=False: FakeResp(lines))
    prov = P.OpenAIProvider("http://127.0.0.1:1234/v1", AIConfig(model="local"))
    out = list(prov.chat([{"role": "user", "content": "x"}]))
    assert [p for k, p in out if k == "text"] == ["نعم"]
    assert out[-1][1]["tool_calls"] == [{"name": "sched", "args": {"scope": "all"}}]


def test_provider_models_parsing(monkeypatch):
    from dpp.ai import provider as P
    monkeypatch.setattr(P, "_request", lambda url, payload=None, timeout=30, stream=False:
                        FakeResp([json.dumps({"models": [{"name": "b:4b"}, {"name": "a:4b"}]})]))
    assert OllamaProvider("http://x", AIConfig()).models() == ["a:4b", "b:4b"]
    monkeypatch.setattr(P, "_request", lambda url, payload=None, timeout=30, stream=False:
                        FakeResp([json.dumps({"data": [{"id": "m2"}, {"id": "m1"}]})]))
    assert OpenAIProvider("http://x/v1", AIConfig()).models() == ["m1", "m2"]


def test_offline_message_is_arabic_and_flagged():
    cfg = AIConfig(kind="ollama", base_url="http://127.0.0.1:1", model="m", timeout=3)
    prov = make_provider(cfg)
    assert prov.ping() is False
    with pytest.raises(AIError) as e:
        prov.models()
    assert e.value.offline is True
    assert "خدمة النماذج المحلية" in str(e.value)
    with pytest.raises(AIError) as e2:
        make_provider(AIConfig(kind="auto", timeout=3))
    assert "لم أجد خدمة نماذج محلية" in str(e2.value) and e2.value.offline


def test_model_auto_pick():
    from dpp.ai.agent import _pick
    assert _pick(["llama3.2:3b", "qwen3:4b", "mistral:7b"]) == "qwen3:4b"
    assert _pick(["gemma3:12b", "gemma3:4b"]) == "gemma3:4b"
    assert _pick(["mistral:7b"]) == "mistral:7b"


# ---------------------------------------------------------------- الواجهة
def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait(page, app, seconds=20):
    end = time.time() + seconds
    while page.thread is not None and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_assistant_page_asks_and_shows_answer(seeded, monkeypatch):
    db, ids = seeded
    _fill(db, ids)
    app = _app()
    from dpp.ai import agent as AG
    fake = FakeProvider([{"text": "", "calls": [{"name": "progress", "args": {"section": "BMP1"}}]},
                         {"text": "تقدم القسم الأول جيد."}])
    monkeypatch.setattr(AG, "make_provider", lambda cfg: fake)
    from dpp.ui.context import AppContext
    from dpp.ui.pages.assistant import AssistantPage
    ctx = AppContext(db)
    ctx.set_formation(ids["formation"])
    page = AssistantPage(ctx)
    page.cfg.model = "fake"
    page.resize(900, 700)
    page.input.setPlainText("كيف تقدم القسم الأول؟")
    page.send()
    assert page.thread is not None and page.send_btn.isEnabled() is False
    _wait(page, app)
    assert page.cur.text() == "تقدم القسم الأول جيد."
    assert "يقرأ" in page.cur.steps.text()
    assert [t.role for t in page.history] == ["user", "assistant"]
    assert page.send_btn.isEnabled() and not page.stop_btn.isEnabled()
    page.clear()
    assert page.history == [] and page.chips.isVisibleTo(page) is not None
    page.close()


def test_assistant_page_reports_offline_without_crashing(seeded, monkeypatch):
    db, ids = seeded
    app = _app()
    from dpp.ui.context import AppContext
    from dpp.ui.pages.assistant import AssistantPage
    page = AssistantPage(AppContext(db))
    page.cfg.kind, page.cfg.base_url, page.cfg.timeout = "ollama", "http://127.0.0.1:1", 3
    page.input.setPlainText("سؤال")
    page.send()
    _wait(page, app)
    assert "خدمة النماذج المحلية" in page.cur.text()
    assert page.history == []                     # السؤال الفاشل لا يُحفظ في السياق
    assert page.send_btn.isEnabled()
    page.close()


def test_assistant_page_probe_offline(seeded, monkeypatch):
    db, _ids = seeded
    app = _app()
    from dpp.ui.context import AppContext
    from dpp.ui.pages.assistant import AssistantPage
    page = AssistantPage(AppContext(db))
    page.cfg.kind, page.cfg.base_url, page.cfg.timeout = "ollama", "http://127.0.0.1:1", 3
    page.probe(force=True)
    end = time.time() + 15
    while page.probe_thread is not None and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert "متوقفة" in page.state.text()
    page.close()


def test_standalone_window_builds(seeded):
    db, ids = seeded
    _app()
    from dpp.ui.context import AppContext
    from dpp.ui.pages.assistant import AssistantWindow
    ctx = AppContext(db)
    ctx.set_formation(ids["formation"])
    win = AssistantWindow(ctx)
    assert win.page.cfg is not None
    win.close()


def test_reader_connection_is_separate(seeded):
    from dpp.db.database import open_reader
    db, ids = seeded
    _fill(db, ids)
    r = open_reader(db.path, user="ai")
    assert r.conn is not db.conn
    assert r.scalar("SELECT COUNT(*) FROM sessions") == db.scalar("SELECT COUNT(*) FROM sessions")
    env = T.Env(db=r, formation_ids=[ids["formation"]], today=TODAY)
    assert "لغة فرنسية" in T.run(env, "schedule", {"scope": "section", "name": "BMP1", "week": "2026-11-08"})
    r.conn.close()


def test_agent_picks_model_when_none_chosen(seeded):
    db, ids = seeded
    fake = FakeProvider([{"text": "تم."}])
    fake.models = lambda: ["mistral:7b", "qwen3:4b"]
    agent = Agent(db, AIConfig(model=""), [ids["formation"]], today=TODAY, provider=fake)
    list(agent.ask("سؤال"))
    assert agent.cfg.model == "qwen3:4b"


def test_agent_says_when_service_has_no_model(seeded):
    db, ids = seeded
    fake = FakeProvider([])
    fake.models = lambda: []
    agent = Agent(db, AIConfig(model=""), [ids["formation"]], today=TODAY, provider=fake)
    with pytest.raises(AIError) as e:
        list(agent.ask("سؤال"))
    assert "لا يوجد فيها أي نموذج" in str(e.value)


def test_assistant_page_probe_service_without_models(seeded, monkeypatch):
    db, _ids = seeded
    app = _app()
    from dpp.ai import provider as P
    monkeypatch.setattr(P, "_request", lambda url, payload=None, timeout=30, stream=False:
                        FakeResp([json.dumps({"models": []})]))
    from dpp.ui.context import AppContext
    from dpp.ui.pages.assistant import AssistantPage
    page = AssistantPage(AppContext(db))
    page.cfg.kind = "ollama"
    page.probe(force=True)
    end = time.time() + 15
    while page.probe_thread is not None and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert "بلا نماذج" in page.state.text()
    page.close()


def test_text_tool_call_never_shown_to_user(seeded):
    """سطر مناداة أداة نصية لا يظهر للمستخدم حتى لو بثّه النموذج حرفاً حرفاً."""
    db, ids = seeded
    _fill(db, ids)
    fake = FakeProvider([{"text": 'TOOL: today {"x": 1}'}, {"text": "الأسبوع 9."}])
    agent = Agent(db, AIConfig(model="fake"), [ids["formation"]], today=TODAY, provider=fake)
    events = list(agent.ask("أي أسبوع؟"))
    streamed = "".join(p for k, p in events if k == "text")
    assert "TOOL" not in streamed and streamed == "الأسبوع 9."
    assert events[-1] == ("end", "الأسبوع 9.")
    assert any(k == "tool" for k, _ in events)


def test_normal_answer_is_streamed_whole(seeded):
    db, ids = seeded
    fake = FakeProvider([{"text": "جواب قصير"}])
    agent = Agent(db, AIConfig(model="fake"), [ids["formation"]], today=TODAY, provider=fake)
    events = list(agent.ask("سؤال"))
    assert "".join(p for k, p in events if k == "text") == "جواب قصير"
    assert events[-1][1] == "جواب قصير"


def test_short_answer_shorter_than_gate_is_shown(seeded):
    db, ids = seeded
    fake = FakeProvider([{"text": "نعم"}])
    agent = Agent(db, AIConfig(model="fake"), [ids["formation"]], today=TODAY, provider=fake)
    events = list(agent.ask("سؤال"))
    assert "".join(p for k, p in events if k == "text") == "نعم"


def test_no_gate_when_tools_disabled(seeded):
    db, ids = seeded
    fake = FakeProvider([{"text": "TOOL: today {} نص عادي"}])
    agent = Agent(db, AIConfig(model="fake", use_tools=False), [ids["formation"]], today=TODAY, provider=fake)
    events = list(agent.ask("سؤال"))
    assert "".join(p for k, p in events if k == "text") == "TOOL: today {} نص عادي"
    assert not any(k == "tool" for k, _ in events)
    assert fake.seen[0][1] is False


def test_bad_enum_values_are_explained(seeded):
    db, ids = seeded
    env = _env(db, ids)
    assert "scope يجب أن يكون" in T.run(env, "schedule", {"scope": "sections"})
    assert "kind يجب أن يكون" in T.run(env, "free", {"kind": "prof"})
    assert "النوع يجب أن يكون" in T.run(env, "find", {"kind": "person", "name": "أحمد"})
