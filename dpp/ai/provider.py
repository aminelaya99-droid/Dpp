"""النماذج المحلية: المحرك الداخلي (llama.cpp داخل DPP) أو خدمة Ollama / LM Studio.

* الداخلي (1.8): ملف نموذج ‎.gguf‎ في مجلد «models» بجانب البرنامج (أو في مجلد البيانات)،
  يُحمَّل في الذاكرة ويعمل على المعالج — بلا إنترنت وبلا أي برنامج آخر.
* الخدمات: urllib فقط، وكل الطلبات إلى 127.0.0.1 مع تعطيل وكيل الشبكة.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, fields
from typing import Callable, Iterator

SETTING_KEY = "ai_config"

# النوع ← (العنوان الافتراضي، الاسم المعروض)
KINDS = {
    "embedded": ("", "داخلي (llama.cpp)"),
    "ollama": ("http://127.0.0.1:11434", "Ollama"),
    "openai": ("http://127.0.0.1:1234/v1", "LM Studio / متوافق مع OpenAI"),
}

# ما يُجرّب عند الكشف التلقائي، بالترتيب
PROBES = [
    ("ollama", "http://127.0.0.1:11434"),
    ("openai", "http://127.0.0.1:1234/v1"),
    ("openai", "http://127.0.0.1:8080/v1"),
]

# نماذج مقترحة لجهاز بـ 8 غيغا رام بلا كارت رسومات (الأصغر أولاً)
SUGGESTED = ["qwen3:4b", "gemma3:4b", "qwen2.5:3b", "llama3.2:3b"]


class AIError(Exception):
    """خطأ مع رسالة عربية جاهزة للعرض. `offline` يعني أن الخدمة غير مشتغلة."""

    def __init__(self, message: str, *, offline: bool = False, no_tools: bool = False):
        super().__init__(message)
        self.offline = offline
        self.no_tools = no_tools


@dataclass
class AIConfig:
    enabled: bool = True
    kind: str = "auto"              # auto | ollama | openai
    base_url: str = ""              # فارغ = العنوان الافتراضي للنوع
    model: str = ""
    temperature: float = 0.2
    num_ctx: int = 8192             # يتسع لقائمة الأدوات؛ نموذج 4B بـ Q4 + هذا السياق ≈ 4 غيغا رام
    timeout: int = 240
    max_rounds: int = 4             # أقصى عدد مناداة أدوات في سؤال واحد
    history: int = 6                # عدد الرسائل السابقة المُرسلة مع السؤال
    use_tools: bool = True          # مناداة الأدوات أصلاً (قراءة قاعدة البيانات)
    model_path: str = ""            # الداخلي: ملف ‎.gguf‎ محدد (فارغ = أول نموذج في مجلد models)
    threads: int = 0                # الداخلي: عدد أنوية المعالج (0 = تلقائي)
    max_tokens: int = 900           # أقصى طول للجواب

    def url(self) -> str:
        if self.base_url:
            return self.base_url.rstrip("/")
        return KINDS.get(self.kind, KINDS["ollama"])[0]

    def label(self) -> str:
        return KINDS.get(self.kind, ("", self.kind))[1]


def load_config(db) -> AIConfig:
    raw = db.get_setting(SETTING_KEY, "")
    cfg = AIConfig()
    if not raw:
        return cfg
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    known = {f.name: f.type for f in fields(AIConfig)}
    for key, value in data.items():
        if key not in known:
            continue
        try:
            cur = getattr(cfg, key)
            setattr(cfg, key, type(cur)(value) if not isinstance(cur, bool) else bool(value))
        except (TypeError, ValueError):
            pass
    return cfg


def save_config(db, cfg: AIConfig) -> None:
    db.set_setting(SETTING_KEY, json.dumps(asdict(cfg), ensure_ascii=False))


# ---------------------------------------------------------------------- HTTP
def _opener():
    """فاتح بلا وكيل: متغيرات HTTP_PROXY لا تُطبق على المضيف المحلي."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _request(url: str, payload=None, timeout: int = 30, stream: bool = False):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        return _opener().open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        raise AIError(_http_message(e.code, body), no_tools=_means_no_tools(body)) from e
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        raise AIError(
            "لا يمكن الوصول إلى خدمة النماذج المحلية على " + url.split("/api")[0].split("/chat")[0] + "\n"
            "تأكد أن Ollama أو LM Studio مشتغل على الجهاز، ثم أعد المحاولة.", offline=True) from e


def _http_message(code: int, body: str) -> str:
    detail = ""
    try:
        detail = (json.loads(body) or {}).get("error") or ""
        if isinstance(detail, dict):
            detail = detail.get("message", "")
    except (ValueError, TypeError, AttributeError):
        detail = body.strip()
    if code == 404 and "model" in body.lower():
        return "النموذج المطلوب غير موجود في الخدمة المحلية. حمّله أولاً (مثلاً: ollama pull qwen3:4b)."
    if code == 404:
        return "عنوان الخدمة غير صحيح (404). راجع العنوان في الإعدادات."
    if code in (500, 503) and "memory" in body.lower():
        return "الخدمة المحلية تقول إن الذاكرة غير كافية لهذا النموذج. اختر نموذجاً أصغر (مثلاً 4B بصيغة Q4)."
    return f"الخدمة المحلية ردّت بخطأ {code}." + (f"\n{detail[:300]}" if detail else "")


def _means_no_tools(body: str) -> bool:
    low = (body or "").lower()
    return "does not support tools" in low or ("tools" in low and "support" in low)


def _json(url: str, timeout: int = 10) -> dict:
    with _request(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace") or "{}")


# ---------------------------------------------------------------------- المزوّدون
class LocalProvider:
    """واجهة موحّدة: `models()` و`ping()` و`chat()` (مولّد يبثّ الجواب)."""

    kind = ""

    def __init__(self, base_url: str, cfg: AIConfig | None = None):
        self.base = base_url.rstrip("/")
        self.cfg = cfg or AIConfig()

    def models(self) -> list[str]:
        raise NotImplementedError

    def ping(self) -> bool:
        try:
            self.models()
            return True
        except AIError:
            return False

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             cancel: Callable[[], bool] | None = None) -> Iterator[tuple]:
        raise NotImplementedError

    # أدوات مشتركة للبثّ
    def _lines(self, resp, cancel):
        for raw in resp:
            if cancel and cancel():
                break
            line = raw.decode("utf-8", "replace").strip()
            if line:
                yield line


class OllamaProvider(LocalProvider):
    kind = "ollama"

    def models(self) -> list[str]:
        data = _json(f"{self.base}/api/tags", timeout=10)
        return sorted(m.get("name", "") for m in data.get("models", []) if m.get("name"))

    def chat(self, messages, tools=None, cancel=None):
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": self.cfg.temperature, "num_ctx": self.cfg.num_ctx},
        }
        if tools:
            payload["tools"] = tools
        text, calls = [], []
        with _request(f"{self.base}/api/chat", payload, timeout=self.cfg.timeout, stream=True) as resp:
            for line in self._lines(resp, cancel):
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("error"):
                    raise AIError(f"الخدمة المحلية: {obj['error']}", no_tools=_means_no_tools(str(obj["error"])))
                msg = obj.get("message") or {}
                chunk = msg.get("content") or ""
                if chunk:
                    text.append(chunk)
                    yield ("text", chunk)
                for call in msg.get("tool_calls") or []:
                    fn = call.get("function") or {}
                    calls.append({"name": fn.get("name", ""), "args": _as_args(fn.get("arguments"))})
                if obj.get("done"):
                    break
        yield ("end", {"content": "".join(text), "tool_calls": calls})


class OpenAIProvider(LocalProvider):
    """متوافق مع OpenAI: LM Studio، llama.cpp server، وواجهة Ollama على /v1."""

    kind = "openai"

    def models(self) -> list[str]:
        data = _json(f"{self.base}/models", timeout=10)
        return sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))

    def chat(self, messages, tools=None, cancel=None):
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": True,
            "temperature": self.cfg.temperature,
        }
        if tools:
            payload["tools"] = tools
        text, parts = [], {}
        with _request(f"{self.base}/chat/completions", payload, timeout=self.cfg.timeout, stream=True) as resp:
            for line in self._lines(resp, cancel):
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    obj = json.loads(body)
                except ValueError:
                    continue
                if obj.get("error"):
                    err = obj["error"]
                    msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                    raise AIError(f"الخدمة المحلية: {msg}", no_tools=_means_no_tools(msg))
                for choice in obj.get("choices") or []:
                    delta = choice.get("delta") or {}
                    chunk = delta.get("content") or ""
                    if chunk:
                        text.append(chunk)
                        yield ("text", chunk)
                    for tc in delta.get("tool_calls") or []:
                        slot = parts.setdefault(tc.get("index", 0), {"name": "", "args": ""})
                        fn = tc.get("function") or {}
                        slot["name"] += fn.get("name") or ""
                        slot["args"] += fn.get("arguments") or ""
        calls = [{"name": p["name"], "args": _as_args(p["args"])} for _i, p in sorted(parts.items()) if p["name"]]
        yield ("end", {"content": "".join(text), "tool_calls": calls})


def _as_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except (ValueError, TypeError):
        return {}


# ====================================================================== المحرك الداخلي
def model_dirs() -> list:
    """أين نبحث عن ملفات النماذج: «models» بجانب DPP.exe (أو جذر المشروع)، ثم مجلد البيانات."""
    import sys
    from pathlib import Path
    from ..db.database import default_data_dir
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
    else:
        app_dir = Path(__file__).resolve().parent.parent.parent
    out = []
    for d in (app_dir / "models", default_data_dir() / "models"):
        if d not in out:
            out.append(d)
    return out


def find_models(cfg: AIConfig | None = None) -> list:
    """ملفات ‎.gguf‎ المتاحة (الأكبر أولاً لا يهم: الترتيب أبجدي). ملفات الرؤية (mmproj) مستبعدة."""
    from pathlib import Path
    seen, out = set(), []
    if cfg is not None and cfg.model_path and Path(cfg.model_path).is_file():
        p = Path(cfg.model_path)
        seen.add(p.resolve())
        out.append(p)
    for d in model_dirs():
        try:
            files = sorted(d.glob("*.gguf"))
        except OSError:
            continue
        for p in files:
            if "mmproj" in p.name.lower() or p.resolve() in seen:
                continue
            try:
                if p.stat().st_size < 20_000_000:          # ملف ناقص (تحميل لم يكتمل)
                    continue
            except OSError:
                continue
            seen.add(p.resolve())
            out.append(p)
    return out


def cpu_supports_avx2() -> bool | None:
    """Windows: هل يدعم المعالج AVX2 (المحرك مبني له)؟ None = لا نعرف."""
    import os
    if os.name != "nt":
        return None
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))   # PF_AVX2_INSTRUCTIONS_AVAILABLE
    except Exception:
        return None


def embedded_status() -> tuple[bool, str]:
    """(المحرك متاح؟، سبب عدم توفره)."""
    try:
        import llama_cpp  # noqa: F401
    except Exception as e:                       # ImportError / OSError (DLL)
        msg = "المحرك الداخلي غير موجود في هذه النسخة من البرنامج."
        if cpu_supports_avx2() is False:
            msg = "معالج هذا الجهاز لا يدعم تعليمات AVX2 التي يحتاجها المحرك الداخلي."
        return False, f"{msg}\n({type(e).__name__}: {e})"
    return True, ""


_LLM_CACHE: dict = {}
_LLM_LOCK = None


def _llm_lock():
    global _LLM_LOCK
    if _LLM_LOCK is None:
        import threading
        _LLM_LOCK = threading.Lock()
    return _LLM_LOCK


class EmbeddedProvider(LocalProvider):
    """llama.cpp داخل البرنامج: يحمّل ملف ‎.gguf‎ مرة واحدة ويبقيه في الذاكرة.

    النماذج الصغيرة لا تدعم مناداة الأدوات بالصيغة الرسمية هنا، فالوكيل يستعمل الصيغة النصية
    (TOOL: الاسم {…}) مباشرة (native_tools = False)."""

    kind = "embedded"
    native_tools = False

    def __init__(self, base_url: str = "", cfg: AIConfig | None = None):
        super().__init__(base_url or "local", cfg)

    def models(self) -> list[str]:
        ok, why = embedded_status()
        if not ok:
            raise AIError(why, offline=True)
        files = find_models(self.cfg)
        if not files:
            raise AIError(no_model_message(), offline=True)
        return [p.name for p in files]

    def _path(self):
        files = find_models(self.cfg)
        if not files:
            raise AIError(no_model_message(), offline=True)
        if self.cfg.model:
            for p in files:
                if p.name == self.cfg.model:
                    return p
        return files[0]

    def loaded(self) -> bool:
        try:
            p = self._path()
        except AIError:
            return False
        return (str(p), self.cfg.num_ctx) in _LLM_CACHE

    def llm(self):
        ok, why = embedded_status()
        if not ok:
            raise AIError(why, offline=True)
        p = self._path()
        key = (str(p), self.cfg.num_ctx)
        with _llm_lock():
            if key not in _LLM_CACHE:
                import os
                from llama_cpp import Llama
                _LLM_CACHE.clear()                     # نموذج واحد في الذاكرة
                threads = self.cfg.threads or max(1, min(8, (os.cpu_count() or 4) - 1))
                try:
                    _LLM_CACHE[key] = Llama(model_path=str(p), n_ctx=self.cfg.num_ctx, n_threads=threads,
                                            n_batch=256, verbose=False)
                except MemoryError as e:
                    raise AIError("الذاكرة غير كافية لتحميل النموذج. أغلق برامج أخرى أو اختر نموذجاً أصغر.") from e
                except Exception as e:
                    raise AIError(f"تعذّر تحميل النموذج {p.name}: {type(e).__name__}: {e}\n"
                                  "تأكد أن الملف اكتمل تحميله وأنه بصيغة GGUF.") from e
            return _LLM_CACHE[key]

    def chat(self, messages, tools=None, cancel=None):
        llm = self.llm()
        text = []
        try:
            stream = llm.create_chat_completion(messages=messages, stream=True, temperature=self.cfg.temperature,
                                                max_tokens=self.cfg.max_tokens)
            for chunk in stream:
                if cancel and cancel():
                    break
                for ch in chunk.get("choices") or []:
                    piece = (ch.get("delta") or {}).get("content") or ""
                    if piece:
                        text.append(piece)
                        yield ("text", piece)
        except AIError:
            raise
        except ValueError as e:                        # تجاوز طول السياق
            if "context" in str(e).lower() or "token" in str(e).lower():
                raise AIError("السؤال والمحادثة أطول من ذاكرة النموذج. اضغط «محادثة جديدة» وأعد السؤال.") from e
            raise AIError(f"المحرك الداخلي: {e}") from e
        except Exception as e:
            raise AIError(f"المحرك الداخلي: {type(e).__name__}: {e}") from e
        yield ("end", {"content": "".join(text), "tool_calls": []})


RECOMMENDED_MODEL = ("Qwen3-4B-Instruct-2507 (Q4_K_M)، حوالي 2.5 GB، "
                     "ابحث عنه في huggingface.co باسم: Qwen3-4B-Instruct-2507-GGUF")


def no_model_message() -> str:
    dirs = "\n".join(f"  • {d}" for d in model_dirs())
    return ("لا يوجد ملف نموذج (‎.gguf‎) بعد.\n"
            f"ضع ملف النموذج في أحد هذه المجلدات ثم اضغط «فحص»:\n{dirs}\n"
            f"النموذج المقترح لجهاز بـ 8 غيغا: {RECOMMENDED_MODEL}.\n"
            "أو اضغط «اختيار ملف النموذج…» إن كان الملف في مكان آخر.")


PROVIDER_CLASSES = {"embedded": EmbeddedProvider, "ollama": OllamaProvider, "openai": OpenAIProvider}


def make_provider(cfg: AIConfig) -> LocalProvider:
    """مزوّد جاهز حسب الإعدادات. التلقائي: الداخلي إن وُجد نموذج، وإلا أول خدمة مشتغلة."""
    if cfg.kind in PROVIDER_CLASSES:
        return PROVIDER_CLASSES[cfg.kind](cfg.url(), cfg)
    if embedded_status()[0] and find_models(cfg):
        return EmbeddedProvider("", cfg)
    found = detect(cfg)
    if not found:
        raise AIError(no_model_message() + "\n\nأو شغّل Ollama / LM Studio إن كانا مثبّتين.", offline=True)
    kind, base = found
    return PROVIDER_CLASSES[kind](base, cfg)


def detect(cfg: AIConfig | None = None) -> tuple[str, str] | None:
    """أول مصدر متاح: الداخلي إن وُجد نموذج، وإلا أول خدمة محلية مشتغلة: (النوع، العنوان) أو None."""
    if embedded_status()[0] and find_models(cfg):
        return "embedded", "local"
    for kind, base in PROBES:
        probe = PROVIDER_CLASSES[kind](base, cfg)
        try:
            probe.models()
            return kind, base
        except AIError:
            continue
    return None


def available_models(cfg: AIConfig) -> list[str]:
    """قائمة النماذج المحمّلة في الخدمة (قائمة فارغة إن كانت متوقفة)."""
    try:
        return make_provider(cfg).models()
    except AIError:
        return []
