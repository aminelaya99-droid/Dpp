"""تشغيل البرنامج من المصدر: python run_dpp.py   |   فحص ذاتي: python run_dpp.py --selftest"""
import sys

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import os

        from dpp.selftest import run
        code = run()
        sys.stdout.flush()
        if os.name == "nt":   # إنهاء مباشر دون انتظار تفريغ مكتبات الخيوط
            import ctypes
            k = ctypes.windll.kernel32
            k.TerminateProcess(k.GetCurrentProcess(), code)
        os._exit(code)
    from dpp.app import main
    sys.exit(main())
