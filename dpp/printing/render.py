"""رسم صفحة القالب (نفس الكود للمحرر والمعاينة والطباعة وPDF).

الأبعاد بالمليمتر وتُحول إلى نقاط الجهاز بمعامل k (نقطة/مم).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QTextOption

from dpp.models import DAY_NAMES, FULL_DAY_KINDS, LESSON_KINDS
from dpp.printing.template import fill
from dpp.services.timeutil import fmt

PT_TO_MM = 25.4 / 72


@dataclass
class TimeCol:
    key: str
    start: int
    end: int
    is_lunch: bool = False

    @property
    def minutes(self) -> int:
        return self.end - self.start


@dataclass
class CellLesson:
    day: int
    start: int
    end: int
    title: str
    teacher: str
    color: str
    full_day: bool = False


@dataclass
class TableData:
    days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    cols: list[TimeCol] = field(default_factory=list)
    lessons: list[CellLesson] = field(default_factory=list)


@dataclass
class RenderContext:
    values: dict
    table: TableData


def build_table_data(section, week, color_fn=None) -> TableData:
    """أعمدة الجدول = الفترات بين حدود الساعات والغداء وحدود الحصص الفعلية."""
    lv = section.level
    t = section.training
    days = [d for d in range(7) if d not in t.weekend_days]
    ls = section.effective_lunch_start
    le = ls + lv.lunch_minutes
    bounds = {lv.day_start, lv.day_end}
    m = (lv.day_start // 60 + 1) * 60
    while m < lv.day_end:
        bounds.add(m)
        m += 60
    if lv.lunch_minutes:
        bounds |= {ls, le}
    lessons: list[CellLesson] = []
    for les in (week.lessons if week else []):
        if les.section_id != section.id:
            continue
        full = les.kind in FULL_DAY_KINDS
        s0, e0 = (lv.day_start, lv.day_end) if full else (les.start, les.end)
        s0, e0 = max(s0, lv.day_start), min(e0, lv.day_end)
        if e0 <= s0:
            continue
        if not full:
            bounds |= {s0, e0}
        title = les.subject.name if les.subject else LESSON_KINDS.get(les.kind, "")
        if full and les.subject:
            title = f"{LESSON_KINDS[les.kind]}: {les.subject.name}"
        elif full:
            title = LESSON_KINDS.get(les.kind, "")
        color = color_fn(les.subject).name() if (color_fn and les.subject) else "#F1F5F9"
        lessons.append(CellLesson(les.day, s0, e0, title, les.teacher.display_name if les.teacher else "",
                                  color, full))
    b = sorted(x for x in bounds if lv.day_start <= x <= lv.day_end)
    # دمج الفترات الأقل من 30 د مع ما قبلها لتفادي أعمدة ضيقة جداً
    merged = [b[0]]
    for x in b[1:]:
        if x - merged[-1] < 30 and x != b[-1] and x not in (ls, le):
            continue
        merged.append(x)
    cols = []
    for a, z in zip(merged, merged[1:]):
        cols.append(TimeCol(f"{fmt(a)}-{fmt(z)}", a, z, lv.lunch_minutes > 0 and a >= ls and z <= le))
    return TableData(days, cols, lessons)


def sample_table_data() -> TableData:
    cols = [TimeCol(f"{fmt(a)}-{fmt(a + 60)}", a, a + 60, a == 720) for a in range(480, 960, 60)]
    les = [CellLesson(0, 480, 600, "مادة نموذجية", "اللقب", "#DCFCE7"),
           CellLesson(1, 540, 660, "مادة تخصصية", "اللقب", "#DBEAFE")]
    return TableData([0, 1, 2, 3, 4], cols, les)


# ------------------------------------------------------------------ هندسة الجدول
@dataclass
class TableGeom:
    cols: list[tuple[str, float, float]]   # (المفتاح، x يسار، x يمين) بالمم؛ الترتيب من اليمين
    rows: list[tuple[object, float, float]]  # ("header" أو رقم اليوم، y أعلى، y أسفل)
    timecols: list[TimeCol]


def table_geometry(item: dict, data: TableData) -> TableGeom:
    hidden = set(item.get("hidden_cols", []))
    tcols = [c for c in data.cols if c.key not in hidden]
    extras = item.get("extra_cols", [])
    x_right = item["x"] + item["w"]
    day_w = item.get("day_col_w", 22.0)
    extra_w = sum(e.get("width", 25.0) for e in extras)
    avail = max(10.0, item["w"] - day_w - extra_w)
    weights = [float(item.get("col_weights", {}).get(c.key, c.minutes / 60)) for c in tcols]
    tot = sum(weights) or 1.0
    day_left = item.get("day_col_side", "right") == "left"
    cols: list[tuple[str, float, float]] = []
    x = x_right
    if not day_left:
        cols.append(("__day__", x_right - day_w, x_right))
        x = x_right - day_w
    for c, wgt in zip(tcols, weights):
        w = avail * wgt / tot
        cols.append((c.key, x - w, x))
        x -= w
    for i, e in enumerate(extras):
        w = e.get("width", 25.0)
        cols.append((f"__extra{i}__", x - w, x))
        x -= w
    if day_left:
        cols.append(("__day__", x - day_w, x))
    days = [d for d in data.days if d not in set(item.get("hidden_days", []))]
    hh = item.get("header_h", 9.0)
    rows: list[tuple[object, float, float]] = [("header", item["y"], item["y"] + hh)]
    rw = [float(item.get("row_weights", {}).get(str(d), 1.0)) for d in days]
    rt = sum(rw) or 1.0
    y = item["y"] + hh
    avail_h = max(5.0, item["h"] - hh)
    for d, wgt in zip(days, rw):
        h = avail_h * wgt / rt
        rows.append((d, y, y + h))
        y += h
    return TableGeom(cols, rows, tcols)


# ------------------------------------------------------------------ الرسم
class Renderer:
    def __init__(self, painter: QPainter, k: float, ox: float = 0.0, oy: float = 0.0):
        self.p, self.k, self.ox, self.oy = painter, k, ox, oy

    def R(self, x, y, w, h) -> QRectF:
        return QRectF(self.ox + x * self.k, self.oy + y * self.k, w * self.k, h * self.k)

    def font(self, family: str, size_pt: float, bold=False, italic=False) -> QFont:
        f = QFont()
        f.setFamilies([family, "Tahoma", "Arial", "Noto Sans Arabic", "DejaVu Sans"])
        f.setPixelSize(max(1, round(size_pt * PT_TO_MM * self.k)))
        f.setBold(bold)
        f.setItalic(italic)
        return f

    def pen(self, color: str, width_mm: float, style=Qt.SolidLine) -> QPen:
        pen = QPen(QColor(color), max(0.0, width_mm * self.k), style)
        pen.setCosmetic(False)
        return pen

    # -------------------------------------------- نص
    def draw_text_box(self, it: dict, values: dict) -> list[str]:
        text, missing = fill(it["text"], values)
        r = self.R(it["x"], it["y"], it["w"], it["h"])
        p = self.p
        p.save()
        if it.get("bg"):
            p.fillRect(r, QColor(it["bg"]))
        if it.get("border", 0) > 0:
            p.setPen(self.pen(it.get("border_color", "#000"), it["border"]))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
        pad = it.get("padding", 1.0) * self.k
        rot = float(it.get("rotation", 0) or 0)
        p.translate(r.center())
        p.rotate(rot)
        w, h = r.width(), r.height()
        if abs(rot) % 180 == 90:
            w, h = h, w
        tr = QRectF(-w / 2 + pad, -h / 2 + pad, max(1.0, w - 2 * pad), max(1.0, h - 2 * pad))
        p.setFont(self.font(it.get("font", "Tahoma"), it.get("size", 11), it.get("bold"), it.get("italic")))
        col = QColor(it.get("color", "#000"))
        p.setPen(col)
        align = {"right": Qt.AlignRight, "left": Qt.AlignLeft, "center": Qt.AlignHCenter}.get(it.get("align"), Qt.AlignHCenter)
        valign = {"top": Qt.AlignTop, "bottom": Qt.AlignBottom}.get(it.get("valign"), Qt.AlignVCenter)
        opt = QTextOption(align | valign)
        opt.setWrapMode(QTextOption.WordWrap)
        opt.setTextDirection(Qt.RightToLeft)
        if missing:
            p.setPen(QColor("#DC2626"))
        p.drawText(tr, text, opt)
        p.restore()
        return missing

    def fit_text(self, rect: QRectF, lines: list[tuple[str, bool, float]], family: str, color="#000") -> None:
        """يرسم عدة أسطر مع تصغير الخط تلقائياً لتفادي القص (حتى 5 نقاط)."""
        p = self.p
        scale = 1.0
        for _ in range(8):
            heights = []
            for text, bold, size in lines:
                fm = QFontMetricsF(self.font(family, size * scale, bold))
                br = fm.boundingRect(QRectF(0, 0, rect.width(), 10000), Qt.TextWordWrap | Qt.AlignCenter, text)
                heights.append(br.height())
            if sum(heights) <= rect.height() or min(s for _, _, s in lines) * scale <= 5:
                break
            scale *= 0.88
        total = sum(heights)
        y = rect.top() + max(0.0, (rect.height() - total) / 2)
        p.setPen(QColor(color))
        for (text, bold, size), hgt in zip(lines, heights):
            p.setFont(self.font(family, size * scale, bold))
            opt = QTextOption(Qt.AlignCenter)
            opt.setWrapMode(QTextOption.WordWrap)
            opt.setTextDirection(Qt.RightToLeft)
            p.drawText(QRectF(rect.left(), y, rect.width(), hgt), text, opt)
            y += hgt

    # -------------------------------------------- جدول
    def draw_table(self, it: dict, data: TableData) -> None:
        g = table_geometry(it, data)
        p = self.p
        fam = it.get("font", "Tahoma")
        bpen = self.pen(it.get("border_color", "#333"), it.get("border", 0.3))
        colx = {k: (a, b) for k, a, b in g.cols}
        rowy = {k: (a, b) for k, a, b in g.rows}
        hdr_y0, hdr_y1 = rowy["header"]
        # الخلفيات
        x_left, x_right = min(c[1] for c in g.cols), max(c[2] for c in g.cols)
        y_bot = g.rows[-1][2]
        p.fillRect(self.R(x_left, hdr_y0, x_right - x_left, hdr_y1 - hdr_y0), QColor(it.get("header_bg", "#E8EEF4")))
        a, b = colx["__day__"]
        p.fillRect(self.R(a, hdr_y1, b - a, y_bot - hdr_y1), QColor(it.get("day_bg", "#F3F4F6")))
        # الشبكة
        p.setPen(bpen)
        p.setBrush(Qt.NoBrush)
        for _, a, b in g.cols:
            for _, y0, y1 in g.rows:
                p.drawRect(self.R(a, y0, b - a, y1 - y0))
        # الرؤوس
        tcol = {c.key: c for c in g.timecols}
        for key, a, b in g.cols:
            r = self.R(a, hdr_y0, b - a, hdr_y1 - hdr_y0).adjusted(1, 1, -1, -1)
            if key == "__day__":
                label = "الأيام"
            elif key.startswith("__extra"):
                label = it["extra_cols"][int(key[7:-2])].get("title", "")
            else:
                c = tcol[key]
                label = f"{fmt(c.start)}\n{fmt(c.end)}"
            p.setFont(self.font(fam, it.get("header_size", 9), True))
            p.setPen(QColor("#111827"))
            p.drawText(r, Qt.AlignCenter | Qt.TextWordWrap, label)
        for d, y0, y1 in g.rows[1:]:
            a, b = colx["__day__"]
            p.setFont(self.font(fam, it.get("day_size", 10), True))
            p.setPen(QColor("#111827"))
            p.drawText(self.R(a, y0, b - a, y1 - y0), Qt.AlignCenter, DAY_NAMES[d])
        # الغداء: عمود مدمج عمودياً
        for c in g.timecols:
            if not c.is_lunch:
                continue
            a, b = colx[c.key]
            free = [(d, y0, y1) for d, y0, y1 in g.rows[1:]
                    if not any(les.day == d and les.start < c.end and les.end > c.start for les in data.lessons)]
            # تجميع الصفوف المتتالية الحرة في مقاطع مدمجة
            segs: list[list[float]] = []
            for _d, y0, y1 in free:
                if segs and abs(segs[-1][1] - y0) < 1e-6:
                    segs[-1][1] = y1
                else:
                    segs.append([y0, y1])
            for y0, y1 in segs:
                r = self.R(a, y0, b - a, y1 - y0)
                p.fillRect(r.adjusted(0.5, 0.5, -0.5, -0.5), QColor("#FFF7E6"))
                p.setPen(bpen)
                p.drawRect(r)
                p.save()
                p.translate(r.center())
                p.rotate(-90)
                p.setFont(self.font(fam, it.get("cell_size", 8.5), True))
                p.setPen(QColor("#92400E"))
                p.drawText(QRectF(-r.height() / 2, -r.width() / 2, r.height(), r.width()),
                           Qt.AlignCenter | Qt.TextWordWrap, it.get("lunch_label", "استراحة الغداء"))
                p.restore()
        # الحصص
        for les in data.lessons:
            if les.day not in rowy:
                continue
            xs = [colx[c.key] for c in g.timecols if c.start < les.end and c.end > les.start]
            if not xs:
                continue
            a = min(x[0] for x in xs)
            b = max(x[1] for x in xs)
            y0, y1 = rowy[les.day]
            r = self.R(a, y0, b - a, y1 - y0)
            p.fillRect(r, QColor(les.color if it.get("use_colors", True) else "#FFFFFF"))
            p.setPen(bpen)
            p.drawRect(r)
            lines = [(les.title, True, it.get("cell_size", 8.5))]
            if it.get("show_teacher", True) and les.teacher:
                lines.append((les.teacher, False, it.get("cell_size", 8.5) * 0.92))
            if it.get("show_time") and not les.full_day:
                lines.append((f"{fmt(les.start)} – {fmt(les.end)}", False, it.get("cell_size", 8.5) * 0.8))
            pad = 0.8 * self.k
            self.fit_text(r.adjusted(pad, pad, -pad, -pad), lines, fam)
        # الدمج (نص للطباعة فقط)
        keys = [k for k, _, _ in g.cols]
        for mg in it.get("merges", []):
            c0, c1 = mg.get("col", 0), mg.get("col", 0) + max(1, mg.get("cols", 1)) - 1
            r0, r1 = mg.get("row", 0), mg.get("row", 0) + max(1, mg.get("rows", 1)) - 1
            if c0 < 0 or c1 >= len(keys) or r0 < 0 or r1 >= len(g.rows):
                continue
            xa = min(colx[keys[i]][0] for i in range(c0, c1 + 1))
            xb = max(colx[keys[i]][1] for i in range(c0, c1 + 1))
            ya, yb = g.rows[r0][1], g.rows[r1][2]
            r = self.R(xa, ya, xb - xa, yb - ya)
            p.fillRect(r, QColor(mg.get("bg") or "#FFFFFF"))
            p.setPen(bpen)
            p.drawRect(r)
            self.fit_text(r.adjusted(2, 2, -2, -2), [(mg.get("text", ""), mg.get("bold", True),
                                                        mg.get("size", it.get("cell_size", 8.5)))], fam)


def render_page(painter: QPainter, layout: dict, ctx: RenderContext, k: float, ox: float = 0, oy: float = 0) -> list[str]:
    """يرسم الصفحة ويعيد الحقول الفارغة."""
    r = Renderer(painter, k, ox, oy)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    missing: list[str] = []
    for it in layout["items"]:
        if it["type"] == "table":
            r.draw_table(it, ctx.table)
        elif it["type"] == "text":
            missing += r.draw_text_box(it, ctx.values)
    return sorted(set(missing))
