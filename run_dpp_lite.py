"""تشغيل النسخة الخفيفة (ويندوز 7):  python run_dpp_lite.py   |   فحص ذاتي: --selftest

كما في النسخة الكاملة: الملف التنفيذي يُبنى بلا نافذة طرفية، فـ sys.stdout قد يكون None،
وكل كتابة إليه محمية، والخروج يمر عبر TerminateProcess حتى لا تعلق خيوط Qt.
"""
import sys


def _exit(code: int) -> None:
    import os
    try:
        if sys.stdout is not None:
            sys.stdout.flush()
        if sys.stderr is not None:
            sys.stderr.flush()
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.TerminateProcess(k.GetCurrentProcess(), code)
        except Exception:
            pass
    os._exit(code)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        try:
            from dpp_lite.app import selftest
            code = selftest()
        except BaseException:                      # noqa: BLE001
            import traceback
            try:
                if sys.stderr is not None:
                    traceback.print_exc()
            except Exception:
                pass
            code = 2
        _exit(int(code or 0))
    from dpp_lite.app import main
    sys.exit(main())
