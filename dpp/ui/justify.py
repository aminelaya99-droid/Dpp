"""«ضبط» النص (Justify) كما في Word: تمتد الأسطر حتى تملأ العرض من الجهتين.

* بالمسافات: تتسع المسافات بين الكلمات.
* بالتطويل (الكشيدة «ـ»): تُمدّ الحروف العربية المتصلة أولاً، وما تبقى يوزَّع على المسافات.
* السطر الأخير من كل فقرة يبقى على اليمين، إلا إذا طُلب ضبطه أيضاً.
النص من اليمين إلى اليسار: تُرسم الكلمات كلمةً كلمة من الحافة اليمنى.

الرسم يتم بمسارات متجهة (QPainterPath.addText ثم fillPath) لا بـ drawText:
القياس يتم بمقاييس الخط المنطقية (QFontMetricsF)، أما drawText فيعيد حلّ الخط بدقة الجهاز
(PDF 300 نقطة/بوصة، الطابعة 600…) فوق تحويل المشهد، فتخرج الحروف ضخمة ومتراكبة.
المسار يُبنى بنفس المقاييس المنطقية، فيطابق المعاينة على أي جهاز.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPainter, QPainterPath

TATWEEL = "ـ"
# حروف لا تتصل بما بعدها (لا تُمد بعدها)
NON_JOIN_AFTER = set("اأإآدذرزوؤةىءٱ")
ARABIC = range(0x0620, 0x064B)


def _is_ar(ch: str) -> bool:
    return ord(ch) in ARABIC


def kashida_points(word: str) -> list[int]:
    """مواضع يمكن إدراج التطويل بعدها: حرف عربي متصل يليه حرف عربي."""
    out = []
    for i in range(len(word) - 1):
        a, b = word[i], word[i + 1]
        if _is_ar(a) and _is_ar(b) and a not in NON_JOIN_AFTER and a != TATWEEL:
            out.append(i)
    return out


def wrap(text: str, fm: QFontMetricsF, width: float) -> list[tuple[str, bool]]:
    """[(السطر، هل هو آخر سطر في فقرته)]."""
    out = []
    for para in (text or "").split("\n"):
        words = para.split()
        if not words:
            out.append(("", True))
            continue
        cur = ""
        for w in words:
            t = f"{cur} {w}".strip()
            if fm.horizontalAdvance(t) <= width or not cur:
                cur = t
            else:
                out.append((cur, False))
                cur = w
        out.append((cur, True))
    return out


def stretch_kashida(line: str, fm: QFontMetricsF, width: float) -> str:
    """يدرج التطويل بالتناوب على المواضع المتاحة حتى يقترب السطر من العرض دون تجاوزه."""
    words = line.split(" ")
    pts = [(wi, p) for wi, w in enumerate(words) for p in kashida_points(w)]
    if not pts:
        return line
    tw = fm.horizontalAdvance(TATWEEL) or 1
    gap = width - fm.horizontalAdvance(line)
    n = int(gap // tw)
    if n <= 0:
        return line
    n = min(n, len(pts) * 4)                                   # لا أكثر من 4 تطويلات في الموضع الواحد
    counts = {}
    # نوزع من الكلمات الأطول أولاً (أجمل)
    order = sorted(range(len(pts)), key=lambda k: -len(words[pts[k][0]]))
    k = 0
    while n > 0:
        key = pts[order[k % len(order)]]
        counts[key] = counts.get(key, 0) + 1
        n -= 1
        k += 1
    new = []
    for wi, w in enumerate(words):
        s = ""
        for i, ch in enumerate(w):
            s += ch + TATWEEL * counts.get((wi, i), 0)
        new.append(s)
    out = " ".join(new)
    while fm.horizontalAdvance(out) > width and TATWEEL in out:      # أمان: لا تجاوز
        j = out.rfind(TATWEEL)
        out = out[:j] + out[j + 1:]
    return out


def _put(path: QPainterPath, x: float, base: float, font: QFont, text: str) -> None:
    path.addText(QPointF(x, base), font, text)


def draw(p: QPainter, rect: QRectF, text: str, font: QFont, valign: str = "middle", kashida: bool = False,
         justify_last: bool = False, line_h: float = 1.0, color=None) -> float:
    """يرسم النص مضبوطاً داخل المستطيل. يعيد الارتفاع المستعمل."""
    fm = QFontMetricsF(font)
    width = rect.width()
    lines = wrap(text, fm, width)
    lh = fm.lineSpacing() * line_h
    total = lh * len(lines)
    if valign == "top":
        y = rect.top()
    elif valign == "bottom":
        y = rect.bottom() - total
    else:
        y = rect.center().y() - total / 2
    path = QPainterPath()
    for line, last in lines:
        base = y + fm.ascent()
        if not line:
            y += lh
            continue
        # السطر الأخير يُضبط فقط إذا طُلب ذلك وكان يملأ أكثر من نصف العرض (كلمة وحيدة لا تُمطّ إلى آخر السطر)
        justify = (not last) or (justify_last and fm.horizontalAdvance(line) >= width * 0.5)
        if justify and kashida:
            line = stretch_kashida(line, fm, width)
        words = line.split(" ")
        if not justify or len(words) < 2:
            _put(path, rect.right() - fm.horizontalAdvance(line), base, font, line)
            y += lh
            continue
        adv = [fm.horizontalAdvance(w) for w in words]
        gap = (width - sum(adv)) / (len(words) - 1)
        gap = max(fm.horizontalAdvance(" ") * 0.6, gap)
        x = rect.right()
        for w, a in zip(words, adv):
            x -= a
            _put(path, x, base, font, w)
            x -= gap
        y += lh
    col = color if color is not None else p.pen().color()
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    p.drawPath(path)
    p.restore()
    return total
