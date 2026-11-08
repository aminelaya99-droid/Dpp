"""سياق التطبيق المشترك بين الصفحات: قاعدة البيانات، التكوين الحالي (أو «الكل»)، إشارات التحديث."""
from __future__ import annotations

import re

from PySide6.QtCore import QObject, Signal

from ..db.database import Database

ALL = 0      # قيمة «كل التكوينات» في قائمة الاختيار

_FID_RE = re.compile(r"((?:\b\w+\.)?formation_id)\s*=\s*\?")


class AppContext(QObject):
    data_changed = Signal(str)        # اسم الجدول/الوحدة التي تغيرت
    formation_changed = Signal(int)
    status = Signal(str)
    navigate = Signal(str, object)    # اسم الصفحة + وسيط اختياري

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        try:
            from .colors import load_config
            load_config(db)                    # ألوان البطاقات المختارة في الإعدادات
        except Exception:
            pass
        self._formation_id = None
        self.all_formations = (db.get_setting("last_formation", "") in ("", "0", "all"))

    # ------------------------------------------------------------------ التكوين الحالي
    @property
    def formation_id(self) -> int | None:
        """تكوين محدد (في وضع «الكل» = أول تكوين نشط، للأوامر التي تحتاج تكويناً واحداً)."""
        if self._formation_id and self.db.one("SELECT id FROM formations WHERE id=?", (self._formation_id,)):
            return self._formation_id
        last = self.db.get_setting("last_formation", "")
        if last and last.isdigit() and int(last) and self.db.one("SELECT id FROM formations WHERE id=?", (int(last),)):
            self._formation_id = int(last)
            return self._formation_id
        r = self.db.one("SELECT id FROM formations WHERE archived=0 ORDER BY start_date DESC, id DESC LIMIT 1") or \
            self.db.one("SELECT id FROM formations ORDER BY id DESC LIMIT 1")
        self._formation_id = r["id"] if r else None
        return self._formation_id

    @property
    def selection(self) -> int | None:
        """ما يظهر في قائمة الاختيار: ALL أو رقم التكوين."""
        return ALL if self.all_formations else self.formation_id

    def set_formation(self, fid: int | None):
        if fid == ALL:
            if not self.all_formations:
                self.all_formations = True
                self.db.set_setting("last_formation", "all")
                self.formation_changed.emit(ALL)
            return
        if fid != self._formation_id or self.all_formations:
            self.all_formations = False
            self._formation_id = fid
            self.db.set_setting("last_formation", fid or "")
            self.formation_changed.emit(fid or 0)

    def formation_ids(self) -> list[int]:
        """التكوينات المعنية بالعرض الحالي: كل التكوينات النشطة في وضع «الكل»."""
        if self.all_formations:
            return [r[0] for r in self.db.q("SELECT id FROM formations WHERE archived=0 ORDER BY start_date, id")]
        return [self.formation_id] if self.formation_id else []

    def scope(self, sql: str) -> str:
        """في وضع «الكل» يحوّل كل شرط «formation_id=?» إلى كل التكوينات النشطة، مع بقاء عدد المعاملات كما هو."""
        if not self.all_formations:
            return sql
        return _FID_RE.sub(r"\1 IN (SELECT id FROM formations WHERE archived=0 OR id=?)", sql)

    def q(self, sql: str, params=()):
        return self.db.q(self.scope(sql), params)

    def scalar(self, sql: str, params=(), default=None):
        return self.db.scalar(self.scope(sql), params, default)

    def formation_label(self) -> str:
        if self.all_formations:
            return "كل التكوينات"
        f = self.db.one("SELECT name FROM formations WHERE id=?", (self.formation_id or -1,))
        return f["name"] if f else "—"

    def changed(self, what: str = "*"):
        self.data_changed.emit(what)

    def formations(self, include_archived=False):
        return self.db.q("SELECT * FROM formations WHERE (?=1 OR archived=0) ORDER BY start_date DESC, id DESC",
                         (int(include_archived),))
