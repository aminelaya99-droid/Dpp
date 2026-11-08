"""تشغيل البرنامج من المصدر: python run_dpp.py   |   فحص ذاتي: python run_dpp.py --selftest

ملاحظة مهمة للفحص الذاتي من DPP.exe: الملف التنفيذي مبني بلا نافذة طرفية (console=False)،
فـ PyInstaller يجعل sys.stdout و sys.stderr بقيمة None. لذلك كل كتابة إليهما تُحمى هنا:
استثناء غير ملتقط قبل TerminateProcess كان يترك العملية معلّقة إلى الأبد عند الإغلاق
بسبب خيوط Qt وOR-Tools (كان يوقف البناء في GitHub Actions عند خطوة «فحص ذاتي من exe»).
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
    if os.name == "nt":   # إنهاء مباشر دون انتظار تفريغ مكتبات الخيوط
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
            from dpp.selftest import run
            code = run()
        except BaseException:                      # noqa: BLE001 - لا شيء يمنع الخروج بكود واضح
            import traceback
            try:
                if sys.stderr is not None:
                    traceback.print_exc()
            except Exception:
                pass
            code = 2
        _exit(int(code or 0))
    from dpp.app import main
    sys.exit(main())
