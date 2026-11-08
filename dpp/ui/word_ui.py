"""الواجهة لقوالب Word وتصدير الأسبوع.

* «تعديل القالب»: يكتب نسخة القالب في مجلد «قوالب Word» ويفتحها في Word، ثم يراقب الملف (QFileSystemWatcher).
  كل حفظ في Word ← فحص (جدول الحصص موجود، الحقول معروفة) ← استيراد تلقائي إلى قاعدة البيانات.
  الحفظ غير الصالح يُرفض برسالة، ويبقى القالب السابق مستعملاً.
* تصدير الأسبوع كاملاً إلى مجلد (Word + PDF) مع شريط تقدم.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QObject, QFileSystemWatcher, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from ..exporters import word_tpl as W


class WordTemplateWatcher(QObject):
    imported = Signal(str, str)          # النطاق، رسالة
    rejected = Signal(str, list)         # النطاق، الأخطاء

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.files: dict[str, str] = {}          # المسار ← النطاق
        self.digest: dict[str, str] = {}
        self.w = QFileSystemWatcher(self)
        self.w.fileChanged.connect(self._changed)
        self.w.directoryChanged.connect(self._changed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1200)              # Word يكتب ملفاً مؤقتاً ثم يستبدل: ننتظر حتى يستقر
        self.timer.timeout.connect(self.check)

    def open_for_edit(self, scope: str, open_app: bool = True) -> Path:
        db = self.ctx.db
        path = W.edit_path(db, scope)
        data = W.scope_bytes(db, scope)
        try:
            cur = path.read_bytes() if path.exists() else None
        except OSError:
            cur = None
        if cur != data:
            try:
                if cur:                           # تعديلات لم تُستورد (ملف غير صالح مثلاً): نحفظها نسخةً جانبية
                    path.with_name(path.stem + " (نسخة سابقة).docx").write_bytes(cur)
                path.write_bytes(data)
            except PermissionError:
                data = cur or data                # مفتوح في Word: نتركه كما هو ونراقبه
        key = str(path)
        self._watch(key, scope, hashlib.sha1(data).hexdigest())
        m = self._saved_map()
        m[key] = scope
        db.set_setting("word_tpl_files", json.dumps(m, ensure_ascii=False))
        if open_app:
            QDesktopServices.openUrl(QUrl.fromLocalFile(key))
        return path

    def _saved_map(self) -> dict:
        try:
            return json.loads(self.ctx.db.get_setting("word_tpl_files", "") or "{}")
        except Exception:
            return {}

    def _watch(self, key: str, scope: str, digest: str):
        self.files[key] = scope
        self.digest[key] = digest
        if Path(key).exists() and key not in self.w.files():
            self.w.addPath(key)
        d = str(Path(key).parent)
        if Path(d).exists() and d not in self.w.directories():
            self.w.addPath(d)

    def restore(self) -> list:
        """عند فتح البرنامج: يراقب ملفات القوالب التي فُتحت سابقاً، ويستورد ما حُفظ منها والبرنامج مغلق."""
        db = self.ctx.db
        for key, scope in self._saved_map().items():
            cur = W.stored(db, scope)
            self._watch(key, scope, hashlib.sha1(cur).hexdigest() if cur else "")
        return self.check()

    def _changed(self, *_):
        self.timer.start()

    def check(self) -> list[tuple[str, bool]]:
        """يفحص الملفات المراقبة التي تغيّر محتواها. يعيد [(النطاق، استُورد؟)]."""
        out = []
        db = self.ctx.db
        for key, scope in list(self.files.items()):
            p = Path(key)
            if key not in self.w.files() and p.exists():
                self.w.addPath(key)               # Word يستبدل الملف عند الحفظ فتسقط المراقبة
            try:
                data = p.read_bytes()
            except OSError:
                continue
            h = hashlib.sha1(data).hexdigest()
            if h == self.digest.get(key) or not data:
                continue
            self.digest[key] = h
            errors, _notes = W.validate(data)
            if errors:
                out.append((scope, False))
                self.rejected.emit(scope, errors)
                continue
            W.store(db, scope, data)
            out.append((scope, True))
            self.imported.emit(scope, f"تم استيراد قالب Word: {W.scope_label(db, scope)}")
            try:
                self.ctx.changed("word_templates")
            except Exception:
                pass
        return out


def watcher(ctx) -> WordTemplateWatcher:
    w = getattr(ctx, "_word_watch", None)
    if w is None:
        from PySide6.QtWidgets import QApplication
        w = WordTemplateWatcher(ctx, QApplication.instance())
        ctx._word_watch = w
        w.imported.connect(_on_imported)
        w.rejected.connect(lambda scope, errs, ctx=ctx: _on_rejected(ctx, scope, errs))
    return w


def _active_window():
    from PySide6.QtWidgets import QApplication
    return QApplication.activeWindow()


def _on_imported(scope, msg):
    from . import sounds
    from .widgets import info
    try:
        sounds.play("ok")
    except Exception:
        pass
    win = _active_window()
    if win is not None and hasattr(win, "statusBar"):
        try:
            win.statusBar().showMessage(msg, 8000)
            return
        except Exception:
            pass
    info(win, msg)


def _on_rejected(ctx, scope, errors):
    from .widgets import error
    error(_active_window(), f"لم يُستورد {W.scope_label(ctx.db, scope)} — بقي القالب السابق مستعملاً.\n\n• "
          + "\n• ".join(errors[:6]) + "\n\nصحّح الملف في Word واحفظه مرة أخرى.", "قالب Word")


# ====================================================================== تصدير الأسبوع
def pdf_fallback(db):
    def run(sheets, path):
        from .sheet_view import SheetScene, render_to_pdf
        show_room = db.get_setting("print_show_room", "1") == "1"
        color = db.get_setting("print_color", "0") == "1"
        render_to_pdf([SheetScene(s, show_room, color) for s in sheets], path)
    return run


def export_week_dialog(parent, ctx, ws) -> dict | None:
    from PySide6.QtWidgets import QApplication, QFileDialog, QProgressDialog
    from ..exporters import week_export as WE
    from .widgets import error, info
    db = ctx.db
    start = db.get_setting("week_export_dir", "") or str(Path.home() / "Documents")
    root = QFileDialog.getExistingDirectory(parent, "اختر المجلد الذي يُحفظ فيه الأسبوع", start)
    if not root:
        return None
    db.set_setting("week_export_dir", root)
    secs = WE.week_sections(db, ws, None if ctx.all_formations else ctx.formation_ids())
    if not secs:
        info(parent, "لا توجد حصص لأي قسم في هذا الأسبوع.")
        return None
    dlg = QProgressDialog("تصدير الأسبوع…", "", 0, len(secs) + 2, parent)
    dlg.setWindowTitle("تصدير الأسبوع كاملاً")
    dlg.setCancelButton(None)
    dlg.setMinimumDuration(0)
    dlg.setMinimumWidth(420)

    def progress(text, i, n):
        dlg.setMaximum(n)
        dlg.setValue(i)
        dlg.setLabelText(text)
        QApplication.processEvents()
    try:
        res = WE.export_week(db, ws, root, None if ctx.all_formations else ctx.formation_ids(),
                             pdf_fallback=pdf_fallback(db), progress=progress,
                             color=db.get_setting("print_color", "0") == "1")
    except Exception as e:
        dlg.close()
        error(parent, f"تعذر التصدير: {e}")
        return None
    dlg.close()
    eng = {"word": "PDF عبر Microsoft Word", "internal": "PDF بمحرك البرنامج (Word غير متاح)",
           "mixed": "PDF عبر Word، وبعضها بمحرك البرنامج"}[res["engine"]]
    msg = f"تم تصدير {res['sections']} قسماً إلى:\n{res['folder']}\n\n{eng}"
    if res["errors"]:
        msg += "\n\nملاحظات:\n• " + "\n• ".join(res["errors"][:8])
    info(parent, msg)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(res["folder"])))
    return res
