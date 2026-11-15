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
    "ما المواد المتأخرة عن المقرر؟",
    "هل يوجد تعارض هذا الأسبوع؟ اقترح إصلاحه.",
    "من الأساتذة الفارغون غداً من 08:00 إلى 10:00؟",
    "اكتب ملخصاً لتقدم كل الأقسام.",
    "برمج الأسبوع القادم مع التركيز على المواد المتأخرة.",
]

SOURCES = [("auto", "تلقائي"), ("embedded", "داخلي (ملف النموذج)"), ("ollama", "Ollama"),
           ("openai", "LM Studio / متوافق")]


def help_offline() -> str:
    from ...ai.provider import embedded_status, no_model_message
    ok, why = embedded_status()
    head = no_model_message() if ok else why
    return (head + "\n\nكل شيء يبقى على جهازك: لا إنترنت ولا بيانات تخرج.\n"
            "(بديل: Ollama أو LM Studio إن كانا مثبّتين، ثم «فحص».)")


# ---------------------------------------------------------------- العامل في الخيط
class AskWorker(QObject):
    chunk = Signal(str)
    note = Signal(str)
    tool = Signal(str)
    done = Signal(str)
    failed = Signal(str)
    proposal = Signal(object)

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
                elif kind == "proposal":
                    self.proposal.emit(payload)
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
            if self.cfg.kind in ("ollama", "openai", "embedded"):
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

    def add_actions(self, page):
        """أزرار تحت جواب نصي: نسخ، فتح في Word."""
        if getattr(self, "_acts", False):
            return
        self._acts = True
        row = QHBoxLayout()
        row.setSpacing(4)
        for ic, lab, fn in (("mdi6.content-copy", "نسخ", lambda: page.copy_text(self._text)),
                            ("mdi6.microsoft-word", "فتح في Word", lambda: page.to_word(self._text))):
            b = QPushButton(icon(ic), lab)
            b.setFlat(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        self.layout().addLayout(row)

    def add_note(self, note: str):
        if note in self._notes:
            return
        self._notes.append(note)
        self.steps.setText(" · ".join(self._notes))
        self.steps.show()


class ProposalCard(QFrame):
    """بطاقة اقتراح: التغييرات بالضبط والتحذيرات، مع «تطبيق» و«تجاهل» ثم «تراجع»."""

    def __init__(self, prop, page):
        super().__init__()
        self.prop, self.page = prop, page
        self.setObjectName("Card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setMaximumWidth(720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        t = QLabel(f"اقتراح {prop.id}: {prop.title}")
        t.setStyleSheet("font-weight: bold;")
        t.setWordWrap(True)
        lay.addWidget(t)
        body = "\n".join(f"• {x}" for x in prop.lines[:20])
        if len(prop.lines) > 20:
            body += f"\n… و{len(prop.lines) - 20} تغييراً آخر"
        lb = QLabel(body)
        lb.setWordWrap(True)
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(lb)
        if prop.warnings:
            w = QLabel("تنبيه: " + "؛ ".join(prop.warnings[:6]))
            w.setWordWrap(True)
            w.setStyleSheet("color: #B45309;")
            lay.addWidget(w)
        self.status = QLabel("لم يُطبَّق بعد — لا شيء تغيّر.")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.b_apply = QPushButton(icon("mdi6.check"), "تطبيق")
        self.b_apply.clicked.connect(self.apply)
        self.b_skip = QPushButton(icon("mdi6.close"), "تجاهل")
        self.b_skip.clicked.connect(self.skip)
        self.b_undo = QPushButton(icon("mdi6.undo"), "تراجع")
        self.b_undo.clicked.connect(self.undo)
        self.b_undo.hide()
        for b in (self.b_apply, self.b_skip, self.b_undo):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

    def apply(self):
        try:
            msg = self.page.apply_proposal(self.prop)
        except Exception as e:
            self.status.setText(f"تعذّر التطبيق: {e}")
            return
        self.status.setText(msg)
        self.b_apply.hide()
        self.b_skip.hide()
        self.b_undo.show()

    def skip(self):
        self.prop.state = "dismissed"
        self.status.setText("تُجوهل الاقتراح.")
        self.b_apply.hide()
        self.b_skip.hide()

    def undo(self):
        try:
            msg = self.page.undo_proposal(self.prop)
        except Exception as e:
            self.status.setText(f"تعذّر التراجع: {e}")
            return
        self.status.setText(msg)
        self.b_undo.hide()


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
        self.source = QComboBox()
        for k, lab in SOURCES:
            self.source.addItem(lab, k)
        self.source.setCurrentIndex(max(0, self.source.findData(self.cfg.kind)))
        self.source.setToolTip("مصدر النموذج: الداخلي يعمل داخل DPP من ملف ‎.gguf‎ بلا أي برنامج آخر")
        self.source.currentIndexChanged.connect(self._source_changed)
        h.addWidget(self.source)
        self.models = QComboBox()
        self.models.setMinimumWidth(190)
        self.models.setToolTip("النموذج المستعمل")
        self.models.currentTextChanged.connect(self._model_changed)
        h.addWidget(QLabel("النموذج:"))
        h.addWidget(self.models)
        f = QPushButton(icon("mdi6.file-download-outline"), "ملف النموذج…")
        f.setToolTip("اختيار ملف نموذج ‎.gguf‎ من أي مكان، أو فتح مجلد النماذج")
        f.clicked.connect(self._model_file_menu)
        h.addWidget(f)
        b = QPushButton(icon("mdi6.lan-connect"), "فحص")
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
            self.state.setText("لا يوجد نموذج جاهز")
            self.models.clear()
            if getattr(self, "_probe_force", False):
                self._bot(help_offline())
            return
        kind, base = found
        label = {"ollama": "Ollama", "openai": "LM Studio / متوافق", "embedded": "المحرك الداخلي"}.get(kind, kind)
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

    def _source_changed(self, *_):
        self.cfg.kind = self.source.currentData()
        save_config(self.ctx.db, self.cfg)
        self.probe(force=True)

    def _model_file_menu(self):
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction(icon("mdi6.file-search-outline"), "اختيار ملف نموذج (‎.gguf‎)…", self._pick_model_file)
        m.addAction(icon("mdi6.folder-open-outline"), "فتح مجلد النماذج", self._open_models_dir)
        m.addAction(icon("mdi6.information-outline"), "أي نموذج أحمّل؟", lambda: self._bot(help_offline()))
        m.exec(QCursor.pos())

    def _pick_model_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "ملف النموذج", "", "GGUF (*.gguf)")
        if not path:
            return
        from pathlib import Path
        self.cfg.model_path = path
        self.cfg.model = Path(path).name
        self.cfg.kind = "embedded"
        save_config(self.ctx.db, self.cfg)
        self.source.blockSignals(True)
        self.source.setCurrentIndex(max(0, self.source.findData("embedded")))
        self.source.blockSignals(False)
        self.probe(force=True)

    def _open_models_dir(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from ...ai.provider import model_dirs
        d = model_dirs()[0]
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            d = model_dirs()[-1]
            d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def _model_changed(self, name: str):
        if name and name != self.cfg.model:
            self.cfg.model = name
            save_config(self.ctx.db, self.cfg)

    # ------------------------------------------------------------------ الدردشة
    def _welcome(self):
        names = "، ".join(t.name for t in AT.REGISTRY.values())
        self._bot("مرحباً. أجيب عن أسئلتك من بيانات البرنامج نفسه (الجدول، الأساتذة، القاعات، المقرر والتقدم، "
                  "التعارضات، الخفارة)، وأشرح وأحلّل، وأكتب النصوص (ملاحظات، ملخصات، رسائل).\n"
                  "وأقترح التعديلات: نقل حصة، إضافة حصة، إكمال أسبوع قسم، إصلاح التعارضات، توزيع الخفارة، "
                  "وبرمجة أسبوع كامل بمحرك البرنامج.\n"
                  "لا يتغيّر شيء إلا بعد أن تضغط «تطبيق» على بطاقة الاقتراح، ويمكنك التراجع.")
        del names

    def _put(self, w: QWidget, right: bool, max_w: int = 820):
        """سطر في المحادثة: الفقاعة تأخذ العرض المتاح حتى max_w (لا محاذاة على الفقاعة نفسها:
        مع نص ملتف كانت تأخذ عرض تلميحها الصغير فيُقصّ النص)."""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        w.setMaximumWidth(max_w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if right:                      # الاتجاه RTL: أول عنصر على اليمين
            h.addWidget(w, 1)
            h.addStretch(0)
        else:
            h.addStretch(0)
            h.addWidget(w, 1)
        self.chat.insertWidget(self.chat.count() - 1, row)
        self._scroll_down()

    def _bot(self, text: str) -> Bubble:
        b = Bubble("bot", text)
        self._put(b, True)
        return b

    def _user(self, text: str) -> Bubble:
        b = Bubble("user", text)
        self._put(b, False, 640)
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
        self.worker.proposal.connect(self._on_proposal)
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

    @Slot(object)
    def _on_proposal(self, prop):
        self._put(ProposalCard(prop, self), True, 760)

    @Slot(str)
    def _on_done(self, text: str):
        if self.cur is not None:
            if not self.cur.text().strip():
                self.cur.set_text(text or "لم يُرجع النموذج جواباً. جرّب صياغة أقصر أو نموذجاً آخر.")
            self.history.append(Turn("assistant", self.cur.text()))
            if len(self.cur.text()) > 40:
                self.cur.add_actions(self)

    # ------------------------------------------------------------------ تنفيذ الاقتراحات
    def main_window(self):
        for w in QApplication.topLevelWidgets():
            if hasattr(w, "pages") and hasattr(w, "show_page"):
                return w
        return None

    def apply_proposal(self, prop) -> str:
        """ينفّذ الاقتراح في خيط الواجهة. نقل/إضافة الحصص تمر بالجدول العام (Ctrl+Z يعمل هناك)."""
        from ...ai import actions as AA
        grid, page = None, None
        win = self.main_window()
        if win is not None and "master" in getattr(win, "pages", {}):
            page = win.pages["master"]
            if getattr(page, "grid", None) is not None and page.grid.ws == prop.ws:
                grid = page.grid
        msg = AA.apply(self.ctx.db, prop, grid)
        if page is not None and grid is not None:
            page.rebuild()
        self.ctx.changed("sessions_grid" if prop.kind in ("move", "add", "fill", "fix") else
                         {"plan": "sessions", "duty": "duty", "note": "weeks"}.get(prop.kind, "*"))
        return msg

    def undo_proposal(self, prop) -> str:
        from ...ai import actions as AA
        msg = AA.undo(self.ctx.db, prop)
        win = self.main_window()
        if win is not None and "master" in getattr(win, "pages", {}):
            try:
                win.pages["master"].rebuild()
            except Exception:
                pass
        self.ctx.changed("*")
        return msg

    def copy_text(self, text: str):
        QApplication.clipboard().setText(text)

    def to_word(self, text: str):
        import tempfile
        from pathlib import Path
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from docx import Document
        from ...exporters.word_tpl import rtl_paragraph, style_run
        doc = Document()
        for line in text.splitlines():
            p = doc.add_paragraph()
            rtl_paragraph(p, "right")
            style_run(p.add_run(line), size=12, font="Arial")
        out = Path(tempfile.gettempdir()) / f"المساعد_{date.today().isoformat()}.docx"
        doc.save(str(out))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))

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
