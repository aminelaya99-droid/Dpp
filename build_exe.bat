@echo off
chcp 65001 >nul
REM ===== بناء DPP.exe على Windows =====
REM المتطلبات: Python 3.11 أو 3.12 (64-bit) مثبت ومضاف إلى PATH
cd /d "%~dp0"
if not exist .venv (
    echo [1/4] إنشاء بيئة افتراضية...
    py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
echo [2/4] تثبيت المكتبات...
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt || goto :error
echo [3/4] تشغيل الاختبارات...
python -m pytest -q tests || echo تحذير: بعض الاختبارات فشلت - راجع النتائج أعلاه
echo [4/4] بناء البرنامج...
pyinstaller --noconfirm dpp.spec || goto :error
echo.
echo تم البناء: dist\DPP\DPP.exe
echo جرّب التشغيل:  dist\DPP\DPP.exe
pause
exit /b 0
:error
echo فشل البناء. راجع الرسائل أعلاه.
pause
exit /b 1
