"""الحلقة التي تربط النموذج المحلي بأدوات قراءة قاعدة البيانات.

سؤال → (ربما) مناداة أداة أو أكثر → جواب نهائي بالعربية. النموذج يبثّ جوابه قطعة قطعة
حتى لا تبدو الواجهة متوقفة على جهاز بلا كارت رسومات.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterator

from ..utils import iso, week_start
from . import tools as T
from .provider import AIConfig, AIError, load_config, make_provider

# صيغة بديلة لمناداة الأدوات، للنماذج الصغيرة التي لا تدعم tool calling أصلاً
CALL_RE = re.compile(r"(?:TOOL|أداة)\s*:\s*([A-Za-z_]+)\s*(\{.*?\})?", re.S | re.I)
CALL_HEAD = re.compile(r"^\s*(?:tool|أداة)\s*[:：]", re.I)

SYSTEM = """أنت «مساعد DPP» داخل برنامج تسيير جداول مدرسة تكوين.
أجب بالعربية الفصحى البسيطة وباختصار شديد، بلا مقدمات ولا اعتذار.
لا تخترع شيئاً: كل اسم أو رقم في جوابك يجب أن يكون جاء من نتيجة أداة. إن لم تجد المعلومة فقل ذلك.
إن احتجت بيانات، نادِ أداة واحدة وانتظر نتيجتها قبل أن تنادي غيرها.
أنت تقرأ البيانات فقط ولا تستطيع تعديلها في هذا الإصدار؛ إن طُلب منك تعديل، فاشرح للمستخدم في أي صفحة يفعله.
الأسبوع يبدأ يوم الأحد."""

FALLBACK_HINT = """لمناداة أداة اكتب سطراً واحداً فقط بهذا الشكل ثم توقف فوراً:
TOOL: اسم_الأداة {"المعامل": "القيمة"}
الأدوات المتاحة:
__TOOLS__"""


@dataclass
class Turn:
    role: str          # user | assistant
    text: str


class ThinkFilter:
    """يحجب ما بين <think> و</think> (نماذج التفكير مثل Qwen3) عن الواجهة."""

    def __init__(self):
        self.buf = ""
        self.inside = False
        self.thought = False

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        out = []
        while self.buf:
            if self.inside:
                i = self.buf.find("</think>")
                if i < 0:
                    self.buf = self.buf[-8:] if len(self.buf) > 8 else self.buf
                    return "".join(out)
                self.buf = self.buf[i + 8:]
                self.inside = False
                continue
            i = self.buf.find("<think>")
            if i >= 0:
                out.append(self.buf[:i])
                self.buf = self.buf[i + 7:]
                self.inside = True
                self.thought = True
                continue
            keep = _tail_len(self.buf)
            if keep:
                out.append(self.buf[:-keep])
                self.buf = self.buf[-keep:]
            else:
                out.append(self.buf)
                self.buf = ""
            return "".join(out)
        return "".join(out)

    def flush(self) -> str:
        rest = "" if self.inside else self.buf
        self.buf = ""
        return rest


def _tail_len(buf: str) -> int:
    """طول آخر جزء قد يكون بداية وسم <think> أو </think> غير مكتمل."""
    for tag in ("</think>", "<think>"):
        for n in range(min(len(tag) - 1, len(buf)), 0, -1):
            if buf.endswith(tag[:n]):
                return n
    return 0


class Agent:
    def __init__(self, db, cfg: AIConfig | None = None, formation_ids: list[int] | None = None,
                 today: date | None = None, provider=None):
        self.db = db
        self.cfg = cfg or load_config(db)
        self.env = T.Env(db=db, formation_ids=list(formation_ids or []), today=today or date.today())
        self._provider = provider
        self.fallback = False          # يصير True إن لم يدعم النموذج مناداة الأدوات

    # ------------------------------------------------------------------
    def provider(self):
        if self._provider is None:
            self._provider = make_provider(self.cfg)
        if not self.cfg.model:                       # لم يُختر نموذج: نأخذ أنسب موجود
            models = self._provider.models()
            if not models:
                raise AIError("الخدمة المحلية مشتغلة لكن لا يوجد فيها أي نموذج.\n"
                              "حمّل نموذجاً أولاً، مثلاً:  ollama pull qwen3:4b")
            self.cfg.model = _pick(models)
        self._provider.cfg = self.cfg
        return self._provider

    def system_prompt(self) -> str:
        from ..services.grid import week_number
        name = self.db.get_setting("institution_name", "")
        head = SYSTEM + (f"\nالمؤسسة: {name}." if name else "")
        ws = week_start(self.env.today)
        head += (f"\nاليوم {iso(self.env.today)} ({T.DAYS[(self.env.today.weekday() + 1) % 7]})، "
                 f"الأسبوع رقم {week_number(self.db, self.env.today)} يبدأ {iso(ws)}.")
        if self.fallback:
            lst = "\n".join(f"- {t.name}: {t.desc}" for t in T.REGISTRY.values())
            head += "\n" + FALLBACK_HINT.replace("__TOOLS__", lst)
        return head

    def messages(self, question: str, history: list[Turn] | None) -> list[dict]:
        msgs = [{"role": "system", "content": self.system_prompt()}]
        for t in (history or [])[-self.cfg.history:]:
            msgs.append({"role": t.role, "content": t.text})
        msgs.append({"role": "user", "content": question})
        return msgs

    # ------------------------------------------------------------------
    def ask(self, question: str, history: list[Turn] | None = None,
            cancel: Callable[[], bool] | None = None) -> Iterator[tuple]:
        """مولّد أحداث: ("tool", وصف) و("text", قطعة) و("note", ملاحظة) و("end", الجواب الكامل)."""
        msgs = self.messages(question, history)
        specs = T.specs() if self.cfg.use_tools else None
        answer: list[str] = []
        for _round in range(max(1, self.cfg.max_rounds)):
            if cancel and cancel():
                break
            try:
                content, calls, shown = yield from self._one_round(msgs, specs, cancel)
            except AIError as e:
                if e.no_tools and specs and not self.fallback:
                    self.fallback = True
                    specs = None
                    msgs = self.messages(question, history)
                    yield ("note", "النموذج لا يدعم مناداة الأدوات مباشرة؛ انتقلت إلى الصيغة النصية.")
                    continue
                raise
            if shown:
                answer.append(shown)
            if not calls:
                break
            # نتيجة الأداة تُعاد كرسالة عادية لا كرسالة «tool»: بعض الخدمات المحلية
            # ترفض صيغة tool_call_id الصارمة، وهذا يعمل على Ollama و LM Studio معاً.
            names = "، ".join(c["name"] for c in calls)
            msgs.append({"role": "assistant", "content": content.strip() or f"سأستعمل: {names}"})
            for call in calls:
                yield ("tool", _tool_label(call))
                result = T.run(self.env, call["name"], call["args"])
                msgs.append({"role": "user",
                             "content": f"نتيجة الأداة {call['name']}:\n{result}\n\n"
                                        "أجب الآن على سؤالي بالعربية وباختصار اعتماداً على هذه النتيجة، "
                                        "أو نادِ أداة أخرى إن كانت ناقصة."})
        text = "".join(answer).strip()
        yield ("end", text)

    # ------------------------------------------------------------------
    GATE = 12          # عدد الحروف المحتجزة قبل العرض (لكشف سطر مناداة أداة نصية)

    def _one_round(self, msgs, specs, cancel):
        """دورة واحدة مع النموذج: يبثّ النص ويعيد (النص الخام، الأدوات المطلوبة، ما يُحتسب جواباً).

        أول حروف الجواب تُحتجز لحظة قبل عرضها: إن كانت بداية سطر مناداة أداة نصية (TOOL: …)
        فلا يظهر منها شيء للمستخدم، وإلا تُعرض ويستمر البثّ عادياً.
        """
        prov = self.provider()
        flt = ThinkFilter()
        raw, calls = "", []
        shown: list[str] = []
        held = ""
        open_gate = not self.cfg.use_tools    # بلا أدوات لا حاجة للاحتجاز: كل شيء جواب
        blocked = False            # هذه الدورة سطر مناداة أداة: لا يُعرض منها شيء
        thinking_sent = False
        for kind, payload in prov.chat(msgs, specs, cancel=cancel):
            if kind == "end":
                raw = payload.get("content") or ""
                calls = list(payload.get("tool_calls") or [])
                continue
            if kind != "text":
                continue
            visible = flt.feed(payload)
            if flt.thought and not thinking_sent:
                thinking_sent = True
                yield ("note", "النموذج يفكّر…")
            if not visible:
                continue
            shown.append(visible)
            if blocked:
                continue
            if open_gate:
                yield ("text", visible)
                continue
            held += visible
            if CALL_HEAD.match(held):
                blocked, held = True, ""
                continue
            if len(held.lstrip()) < self.GATE:
                continue
            open_gate = True
            yield ("text", held)
            held = ""
        rest = flt.flush()
        if rest:
            shown.append(rest)
            if not blocked:
                if open_gate:
                    yield ("text", rest)
                else:
                    held += rest
        if held and not blocked:
            if CALL_HEAD.match(held):
                blocked = True
            else:
                yield ("text", held)
        text = "".join(shown)
        if not calls and self.cfg.use_tools:
            calls, text = _parse_text_calls(text)
            if calls and not self.fallback:
                self.fallback = True
        return raw, calls, "" if calls else text


def _parse_text_calls(text: str) -> tuple[list[dict], str]:
    """يستخرج مناداة أداة مكتوبة نصاً (TOOL: name {...}) ويعيد ما تبقى من النص."""
    m = CALL_RE.search(text or "")
    if not m or m.group(1) not in T.REGISTRY:
        return [], text
    args = {}
    if m.group(2):
        try:
            parsed = json.loads(m.group(2))
            args = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            args = {}
    return [{"name": m.group(1), "args": args}], (text[:m.start()] + text[m.end():]).strip()


def _tool_label(call: dict) -> str:
    t = T.REGISTRY.get(call["name"])
    label = (t.desc.split(":")[0].split(".")[0] if t else call["name"])[:48]
    args = "، ".join(f"{v}" for v in (call.get("args") or {}).values() if isinstance(v, (str, int, float)))
    return f"يقرأ: {label}" + (f" ({args})" if args else "")


def _pick(models: list[str]) -> str:
    """أنسب نموذج موجود لجهاز متوسط: من القائمة المقترحة إن وُجد، وإلا الأول."""
    from .provider import SUGGESTED
    low = {m.lower(): m for m in models}
    for want in SUGGESTED:
        for key, orig in low.items():
            if key.startswith(want.split(":")[0]) and want.split(":")[-1] in key:
                return orig
    for want in SUGGESTED:
        base = want.split(":")[0]
        for key, orig in low.items():
            if key.startswith(base):
                return orig
    return models[0]
