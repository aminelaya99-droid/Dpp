"""صفحة «المساعد»: دردشة بالعربية مع نموذج محلي يقرأ بيانات البرنامج.

النموذج يعمل في خيط منفصل مع اتصال قراءة خاص بقاعدة البيانات، حتى لا تتجمد الواجهة
ولا يتشارك خيطان اتصالاً واحداً. إن لم تكن خدمة النماذج مشتغلة تظهر تعليمات واضحة
ويبقى باقي البرنامج يعمل عادياً.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ...ai import tools as AT
from ...ai.agent import Agent, Turn
from ...ai.provider import AIError, available_models, detect, load_config, save_config
from ...db.database import open_reader
from ..context import AppContext
from ..widgets import icon

SUGGESTIONS = [
    "ما جدول القسم الأول هذا الأسبوع؟",
    "من الأساتذة الفارغون غداً من 08:00 إلى 10:00؟",
    "ما المواد المتأخرة عن المقرر؟",
    "هل يوجد تعارض هذا الأسبوع؟",
    "لخّص تقدم كل الأقسام.",
]

HELP_OFFLINE = (
    "خدمة النماذج المحلية غير مشتغلة.\n\n"
    "الطريقة الأسهل (مرة واحدة):\n"
    "١. نصّب Ollama من ollama.com (نسخة Windows).\n"
    "٢. افتح موجّه الأوامر واكتب:  ollama pull qwen3:4b\n"
    "٣. اضغط «فحص الخدمة» هنا.\n\n"
    "أو شغّل LM Studio وفعّل فيه الخدمة المحلية (Local Server).\n"
    "كل شيء يبقى على جهازك: لا إنترنت بعد تحميل النموذج، ولا بيانات تخرج."
)


# ---------------------------------------------------------------- العامل في الخيط
class AskWorker(QObject):
    chunk = Signal(str)
    note = Signal(str)
    tool = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, db_path, cfg, formation_ids, question: str, history: list[Turn]):
        super().__init__()
        self.db_path = db_path
        self.cfg = replace(cfg)          # نسخة خاصة بالخيط: لا نشارك كائن الإعدادات
        self.formation_ids = formation_ids
        self.question = question
        self.history = history
        self._stop = False

    def stop(self):
        self._stop = True

    @Slot()
    def run(self):
        db = None
        try:
            db = open_reader(self.db_path, user="ai")
            agent = Agent(db, self.cfg, self.formation_ids, today=date.today())
            text = ""
            for kind, payload in agent.ask(self.question, self.history, cancel=lambda: self._stop):
                if kind == "text":
                    self.chunk.emit(payload)
                elif kind == "tool":
                    self.tool.emit(payload)
                elif kind == "note":
                    self.note.emit(payload)
                elif kind == "end":
                    text = payload
            self.done.emit(text)
        except AIError as e:
            self.failed.emit(str(e))
        except Exception as e:                       # لا نُسقط البرنامج بسبب سؤال
            self.failed.emit(f"خطأ غير متوقع في المساعد: {type(e).__name__}: {e}")
        finally:
            if db is not None:
                try:
                    db.conn.close()
                except Exception:
                    pass


class ProbeWorker(QObject):
    """كشف الخدمة المحلية والنماذج المتاحة في خيط منفصل (لا يُجمّد الواجهة)."""
    result = Signal(object, object)                  # (النوع، العنوان) أو None ، قائمة النماذج

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    @Slot()
    def run(self):
        found, models = None, []
        try:
            if self.cfg.kind in ("ollama", "openai"):
                from ...ai.provider import PROVIDER_CLASSES
                prov = PROVIDER_CLASSES[self.cfg.kind](self.cfg.url(), self.cfg)
                models = prov.models()                 # يرفع AIError إن كانت متوقفة
                found = (self.cfg.kind, self.cfg.url())
            else:
                found = detect(self.cfg)
                models = available_models(self.cfg) if found else []
        except AIError:
            found, models = None, []
        except Exception:
            found, models = None, []
        self.result.emit(found, models)


# ---------------------------------------------------------------- فقاعات الدردشة
class Bubble(QFrame):
    def __init__(self, role: str, text: str = ""):
        super().__init__()
        self.role = role
        self.setObjectName("ChatUser" if role == "user" else "ChatBot")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(4)
        self.body = QLabel(text)
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.setAlignment(Qt.AlignRight | Qt.AlignAbsolute)
        lay.addWidget(self.body)
        self.steps = QLabel()
        self.steps.setObjectName("Muted")
        self.steps.setWordWrap(True)
        self.steps.setAlignment(Qt.AlignRight | Qt.AlignAbsolute)
        self.steps.hide()
        lay.addWidget(self.steps)
        self._text = text
        self._notes: list[str] = []

    def set_text(self, text: str):
        self._text = text
        self.body.setText(text)

    def append(self, chunk: str):
        self.set_text(self._text + chunk)

    def text(self) -> str:
        return self._text

    def add_note(self, note: str):
        if note in self._notes:
            return
        self._notes.append(note)
        self.steps.setText(" · ".join(self._notes))
        self.steps.show()


# ---------------------------------------------------------------- الصفحة
class AssistantPage(QWidget):
    def __init__(self, ctx: AppContext, standalone: bool = False):
        super().__init__()
        self.ctx = ctx
        self.cfg = load_config(ctx.db)
        self.history: list[Turn] = []
        self.thread: QThread | None = None
        self.worker: AskWorker | None = None
        self.probe_thread: QThread | None = None
        self.cur: Bubble | None = None
        self._probed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)
        root.addLayout(self._head(standalone))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.chat_w = QWidget()
        self.chat = QVBoxLayout(self.chat_w)
        self.chat.setContentsMargins(2, 2, 2, 2)
        self.chat.setSpacing(8)
        self.chat.addStretch(1)
        self.scroll.setWidget(self.chat_w)
        root.addWidget(self.scroll, 1)

        self.chips = QWidget()
        cl = QHBoxLayout(self.chips)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        for s in SUGGESTIONS:
            b = QPushButton(s)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, t=s: self._ask_text(t))
            cl.addWidget(b)
        cl.addStretch()
        root.addWidget(self.chips)

        row = QHBoxLayout()
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("اكتب سؤالك عن الجدول أو التقدم… (Enter للإرسال، Shift+Enter لسطر جديد)")
        self.input.setFixedHeight(74)
        self.input.setLayoutDirection(Qt.RightToLeft)
        row.addWidget(self.input, 1)
        col = QVBoxLayout()
        self.send_btn = QPushButton(icon("mdi6.send"), "إرسال")
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(self.send)
        col.addWidget(self.send_btn)
        self.stop_btn = QPushButton(icon("mdi6.stop"), "إيقاف")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        col.addWidget(self.stop_btn)
        row.addLayout(col)
        root.addLayout(row)

        QShortcut(QKeySequence("Ctrl+Return"), self, self.send)
        self.input.installEventFilter(self)
        # إغلاق البرنامج لا يمرّ دائماً بـ closeEvent الصفحة: نوقف الخيوط عند الخروج
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)
        self._welcome()

    # ------------------------------------------------------------------ الرأس
    def _head(self, standalone: bool):
        h = QHBoxLayout()
        t = QLabel("المساعد الذكي (محلي)")
        t.setObjectName("PageTitle")
        h.addWidget(t)
        self.state = QLabel("لم تُفحص الخدمة بعد")
        self.state.setObjectName("Muted")
        h.addWidget(self.state)
        h.addStretch()
        self.models = QComboBox()
        self.models.setMinimumWidth(190)
        self.models.setToolTip("النموذج المستعمل من الخدمة المحلية")
        self.models.currentTextChanged.connect(self._model_changed)
        h.addWidget(QLabel("النموذج:"))
        h.addWidget(self.models)
        b = QPushButton(icon("mdi6.lan-connect"), "فحص الخدمة")
        b.clicked.connect(lambda: self.probe(force=True))
        h.addWidget(b)
        if not standalone:
            w = QPushButton(icon("mdi6.open-in-new"), "نافذة مستقلة")
            w.setToolTip("فتح المساعد في نافذة منفصلة تبقى ظاهرة أثناء العمل على الجدول")
            w.clicked.connect(self.open_window)
            h.addWidget(w)
        c = QPushButton(icon("mdi6.broom"), "محادثة جديدة")
        c.clicked.connect(self.clear)
        h.addWidget(c)
        return h

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.input and ev.type() == QEvent.KeyPress:
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and not (ev.modifiers() & Qt.ShiftModifier):
                self.send()
                return True
        return super().eventFilter(obj, ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._probed:
            self._probed = True
            QTimer.singleShot(250, self.probe)

    # ------------------------------------------------------------------ الكشف
    def probe(self, force: bool = False):
        if self.probe_thread is not None:
            return
        self.state.setText("يفحص الخدمة المحلية…")
        self.probe_thread = QThread(self)
        w = ProbeWorker(self.cfg)
        w.moveToThread(self.probe_thread)
        self.probe_thread.started.connect(w.run)
        w.result.connect(self._probed_done)
        w.result.connect(self.probe_thread.quit)
        self.probe_thread.finished.connect(self._probe_cleanup)
        self._probe_worker = w
        self.probe_thread.start()
        self._probe_force = force

    @Slot(object, object)
    def _probed_done(self, found, models):
        if not found:
            self.state.setText("الخدمة المحلية متوقفة")
            self.models.clear()
            if getattr(self, "_probe_force", False):
                self._bot(HELP_OFFLINE)
            return
        kind, base = found
        label = {"ollama": "Ollama", "openai": "LM Studio / متوافق"}.get(kind, kind)
        if not models:
            self.models.clear()
            self.state.setText(f"{label} مشتغل لكن بلا نماذج")
            if getattr(self, "_probe_force", False):
                self._bot(f"{label} مشتغل على {base} لكن لا يوجد فيه أي نموذج.\n"
                          "حمّل نموذجاً يناسب 8 غيغا رام، مثلاً:  ollama pull qwen3:4b")
            return
        self.models.blockSignals(True)
        self.models.clear()
        self.models.addItems(models)
        if self.cfg.model and self.cfg.model in models:
            self.models.setCurrentText(self.cfg.model)
        elif models:
            from ...ai.agent import _pick
            self.cfg.model = _pick(models)
            self.models.setCurrentText(self.cfg.model)
            save_config(self.ctx.db, self.cfg)
        self.models.blockSignals(False)
        self.state.setText(f"{label} — {len(models)} نموذج")

    def _probe_cleanup(self):
        if self.probe_thread is not None:
            self.probe_thread.deleteLater()
        self.probe_thread = None
        self._probe_worker = None

    def _model_changed(self, name: str):
        if name and name != self.cfg.model:
            self.cfg.model = name
            save_config(self.ctx.db, self.cfg)

    # ------------------------------------------------------------------ الدردشة
    def _welcome(self):
        names = "، ".join(t.name for t in AT.REGISTRY.values())
        self._bot("مرحباً. أجيب عن أسئلتك انطلاقاً من بيانات البرنامج نفسه: الجدول، الأساتذة، القاعات، "
                  "المقرر والتقدم، التعارضات، الخفارة والغيابات.\n"
                  "في هذا الإصدار أقرأ البيانات فقط ولا أعدّلها.\n"
                  f"أدواتي: {names}")

    def _bot(self, text: str) -> Bubble:
        b = Bubble("bot", text)
        self.chat.insertWidget(self.chat.count() - 1, b, 0, Qt.AlignRight)
        self._scroll_down()
        return b

    def _user(self, text: str) -> Bubble:
        b = Bubble("user", text)
        self.chat.insertWidget(self.chat.count() - 1, b, 0, Qt.AlignLeft)
        self._scroll_down()
        return b

    def _scroll_down(self):
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def clear(self):
        self.history.clear()
        while self.chat.count() > 1:
            it = self.chat.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.chips.show()
        self._welcome()

    def _ask_text(self, text: str):
        self.input.setPlainText(text)
        self.send()

    def send(self):
        text = self.input.toPlainText().strip()
        if not text or self.thread is not None:
            return
        if not self.cfg.enabled:
            self._bot("المساعد معطّل في الإعدادات.")
            return
        self.input.clear()
        self.chips.hide()
        self._user(text)
        self.cur = self._bot("")
        self.cur.add_note("ينتظر النموذج…")
        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker = AskWorker(str(self.ctx.db.path), self.cfg, self.ctx.formation_ids(), text, list(self.history))
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.chunk.connect(self._on_chunk)
        self.worker.tool.connect(self._on_note)
        self.worker.note.connect(self._on_note)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.done.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup)
        self.history.append(Turn("user", text))
        self.thread.start()

    def stop(self):
        if self.worker is not None:
            self.worker.stop()
            self.stop_btn.setEnabled(False)
            if self.cur is not None:
                self.cur.add_note("أُوقف بطلب منك")

    @Slot(str)
    def _on_chunk(self, chunk: str):
        if self.cur is not None:
            self.cur.append(chunk)
            self._scroll_down()

    @Slot(str)
    def _on_note(self, note: str):
        if self.cur is not None:
            self.cur.add_note(note)

    @Slot(str)
    def _on_done(self, text: str):
        if self.cur is not None:
            if not self.cur.text().strip():
                self.cur.set_text(text or "لم يُرجع النموذج جواباً. جرّب صياغة أقصر أو نموذجاً آخر.")
            self.history.append(Turn("assistant", self.cur.text()))

    @Slot(str)
    def _on_failed(self, message: str):
        if self.cur is not None:
            self.cur.set_text(message)
        if self.history and self.history[-1].role == "user":
            self.history.pop()

    def _cleanup(self):
        if self.thread is not None:
            self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.input.setFocus()

    # ------------------------------------------------------------------ نافذة مستقلة
    def open_window(self):
        from .assistant import AssistantWindow
        self._win = AssistantWindow(self.ctx)
        self._win.show()
        self._win.raise_()

    def shutdown(self):
        """إيقاف الخيوط وانتظارها (عند إغلاق الصفحة أو البرنامج)."""
        if self.worker is not None:
            self.worker.stop()
        for th in (self.thread, self.probe_thread):
            if th is not None:
                th.quit()
                th.wait(3000)

    def closeEvent(self, ev):
        self.shutdown()
        super().closeEvent(ev)


class AssistantWindow(QWidget):
    """المساعد في نافذة منفصلة تبقى ظاهرة أثناء العمل على الجدول."""

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.setWindowTitle("DPP — المساعد الذكي (محلي)")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(760, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.page = AssistantPage(ctx, standalone=True)
        lay.addWidget(self.page)
        # لا نضع stylesheet على النافذة: نمط التطبيق يسري عليها، فيبقى تغيير المظهر يعمل

    def closeEvent(self, ev):
        self.page.close()
        super().closeEvent(ev)
