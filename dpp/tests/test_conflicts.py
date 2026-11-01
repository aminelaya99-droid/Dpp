from dpp.services.conflicts import (EVENT, HOURS, LUNCH, SECTION, TEACHER, WEEKEND, Context, EventBlock,
                                    Item, SectionRules, find_conflicts)

D = 740000  # تاريخ ترتيبي


def it(i, sec, start, end, teacher=None, subj=None, shared=False, origin="manual", day=0, date=D):
    return Item(i, sec, date, day, start, end, teacher, subj, shared, False, origin, f"L{i}", f"S{sec}", "T")


def kinds(cs):
    return sorted(c.kind for c in cs)


def test_teacher_conflict():
    cs = find_conflicts([it(1, 1, 480, 540, teacher=7), it(2, 2, 510, 600, teacher=7)])
    assert kinds(cs) == [TEACHER]


def test_no_conflict_different_dates():
    cs = find_conflicts([it(1, 1, 480, 540, teacher=7), it(2, 2, 480, 540, teacher=7, date=D + 1)])
    assert cs == []


def test_shared_allowed_same_subject():
    cs = find_conflicts([it(1, 1, 480, 600, 7, subj=3, shared=True), it(2, 2, 480, 600, 7, subj=3, shared=True)])
    assert cs == []


def test_shared_not_allowed_for_normal_subject():
    cs = find_conflicts([it(1, 1, 480, 600, 7, subj=4), it(2, 2, 480, 600, 7, subj=4)])
    assert kinds(cs) == [TEACHER]


def test_shared_different_subjects_conflict():
    cs = find_conflicts([it(1, 1, 480, 600, 7, subj=3, shared=True), it(2, 2, 480, 600, 7, subj=5, shared=True)])
    assert kinds(cs) == [TEACHER]


def test_section_overlap():
    cs = find_conflicts([it(1, 1, 480, 600), it(2, 1, 570, 630)])
    assert kinds(cs) == [SECTION]


def test_adjacent_no_conflict():
    assert find_conflicts([it(1, 1, 480, 540, 7), it(2, 2, 540, 600, 7), it(3, 1, 540, 600)]) == []


def test_imported_ignored():
    cs = find_conflicts([it(1, 1, 480, 600, 7, origin="import"), it(2, 2, 480, 600, 7, origin="import")])
    assert cs == []
    cs = find_conflicts([it(1, 1, 480, 600, 7, origin="import"), it(2, 2, 480, 600, 7)])
    assert kinds(cs) == [TEACHER]


def test_rules_lunch_hours_weekend():
    ctx = Context(rules={1: SectionRules(480, 960, 720, 60, (5, 6))})
    assert kinds(find_conflicts([it(1, 1, 690, 750)], ctx)) == [LUNCH]
    assert kinds(find_conflicts([it(1, 1, 930, 1020)], ctx)) == [HOURS]
    assert kinds(find_conflicts([it(1, 1, 480, 540, day=5)], ctx)) == [WEEKEND]
    # نشاط يوم كامل لا يُعد تعارضاً مع الغداء
    assert find_conflicts([it(1, 1, 480, 960)], ctx) == []


def test_event_and_ignore():
    ev = EventBlock(1, "زيارة", D, 480, 720, frozenset({1}))
    ctx = Context(events=[ev])
    cs = find_conflicts([it(1, 1, 600, 660), it(2, 2, 600, 660)], ctx)
    assert kinds(cs) == [EVENT]
    ctx.ignored.add(cs[0].signature)
    assert find_conflicts([it(1, 1, 600, 660)], ctx) == []


def test_only_ids_filter():
    items = [it(1, 1, 480, 600), it(2, 1, 480, 600), it(3, 2, 480, 600), it(4, 2, 480, 600)]
    assert len(find_conflicts(items)) == 2
    cs = find_conflicts(items, only_ids={3})
    assert len(cs) == 1 and set(cs[0].lesson_ids) == {3, 4}
