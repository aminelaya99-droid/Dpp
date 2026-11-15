"""الإصدار 1.7: واجهة «DPP الحديثة» نمطاً افتراضياً، والواجهات السابقة تبقى خيارات."""
from dpp.ui import theme
from dpp.ui.context import AppContext
from dpp.ui.main_window import PAGES, MainWindow
from dpp.ui.shell import ALL_STYLES, DEFAULT_STYLE, STYLES


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_default_style_is_command(seeded):
    """قاعدة جديدة ← النمط الافتراضي هو «DPP الحديثة»، ولوحته الفاتحة."""
    app = _app()
    db, _ids = seeded
    w = MainWindow(AppContext(db), app)
    w.show()
    app.processEvents()
    assert DEFAULT_STYLE == "command"
    assert w.ui_style == "command" and db.get_setting("ui_style") == "command"
    assert theme.CURRENT_NAME == "command"
    assert w.modern_side.isVisible() and w.header.isVisible()
    assert not w.ribbon.isVisible() and not w.top_nav.isVisible() and not w.focus_bar.isVisible()
    w.close()


def test_old_styles_still_available(seeded):
    """كل الواجهات السابقة تبقى مختارة من القائمة وتشتغل، والاختيار يُحفظ."""
    app = _app()
    db, _ids = seeded
    w = MainWindow(AppContext(db), app)
    w.show()
    assert [k for k, _ in STYLES] == ["command", "ops", "ledger", "daily"]
    for key, _lab in ALL_STYLES:
        w.apply_style(key)
        app.processEvents()
        assert w.ui_style == key and db.get_setting("ui_style") == key
    w.apply_style("command")
    w.close()


def test_command_header_crumbs_and_user(seeded):
    """الشريط العلوي: مسار التنقل واسم المستخدم والإشعارات تظهر في النمط الجديد فقط."""
    app = _app()
    db, _ids = seeded
    w = MainWindow(AppContext(db), app)
    w.show()
    w.navigate("master")
    app.processEvents()
    crumbs = [lab.text() for lab in w.header.crumb_labels if lab.isVisible()]
    assert crumbs and crumbs[0].startswith("DPP") and "الجدول العام" in crumbs[-1]
    assert w.header.crumb_box.isVisible() and w.header.user_btn.isVisible() and w.header.bell.isVisible()
    w.update_badges()
    app.processEvents()
    assert "admin" in w.header.user_btn.text()
    w.header.set_notifications(3)
    assert w.header.bell_badge.isVisible() and w.header.bell_badge.text() == "3"
    w.header.set_notifications(0)
    assert not w.header.bell_badge.isVisible()
    # قائمة الإشعارات تُبنى دون خطأ
    w.header.bell.menu().aboutToShow.emit()
    assert w.header.bell.menu().actions()
    # في الواجهة ب تختفي العناصر الغنية
    w.apply_style("ledger")
    app.processEvents()
    assert not w.header.user_btn.isVisible() and not w.header.crumb_box.isVisible()
    w.apply_style("command")
    w.close()


def test_command_palettes_light_and_dark(seeded):
    """لوحتا الألوان: فاتحة افتراضياً، وداكنة عند اختيار «داكن»، والصفحات تُفتح في الاثنتين."""
    app = _app()
    db, _ids = seeded
    w = MainWindow(AppContext(db), app)
    w.show()
    assert theme.resolve("style", "command") == "command"
    assert theme.resolve("dark", "command") == "command_dark"
    assert theme.resolve("light", "command") == "command"
    assert not theme.is_dark("command") and theme.is_dark("command_dark")
    for mode, pal in (("style", "command"), ("dark", "command_dark"), ("light", "command")):
        w.apply_theme(mode)
        app.processEvents()
        assert theme.CURRENT_NAME == pal
        for key, _t, _i in PAGES:
            w.navigate(key)
            app.processEvents()
    w.apply_theme("style")
    w.close()


def test_settings_sections_and_accent(seeded):
    """الإعدادات بأقسام جانبية، واللون الأساسي يُغيّر لوحة الألوان ويُحفظ."""
    app = _app()
    db, _ids = seeded
    w = MainWindow(AppContext(db), app)
    w.show()
    w.navigate("settings")
    app.processEvents()
    page = w.pages["settings"]
    assert page.nav.count() == page.stack.count() >= 8
    titles = [page.nav.item(i).text() for i in range(page.nav.count())]
    assert "المظهر" in titles and "المؤسسة والوقت" in titles and "النسخ الاحتياطي والبيانات" in titles
    for i in range(page.nav.count()):                       # كل قسم يُفتح بلا خطأ
        page.nav.setCurrentRow(i)
        app.processEvents()
        assert page.stack.currentIndex() == i

    before = theme.CURRENT["accent"]
    page._set_accent("blue")
    app.processEvents()
    assert db.get_setting("accent_color") == "blue"
    assert theme.CURRENT["accent"] != before == "#15803D"
    assert theme.CURRENT["accent"] == "#1D4ED8"
    w.apply_theme("dark")                                   # اللون له نسخة للوضع الداكن
    app.processEvents()
    assert theme.CURRENT_NAME == "command_dark" and theme.CURRENT["accent"] == "#60A5FA"
    page._set_accent("green")
    w.apply_theme("style")
    w.close()
