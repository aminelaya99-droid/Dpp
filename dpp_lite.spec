# -*- mode: python ; coding: utf-8 -*-
# بناء النسخة الخفيفة (ويندوز 7، 32 بت):  pyinstaller --noconfirm dpp_lite.spec
# تُبنى بـ Python 3.8 (x86) و PySide2؛ بلا OR-Tools ولا Word ولا Excel.
from PyInstaller.utils.hooks import collect_submodules

datas = [("dpp/db/schema.sql", "dpp/db")]
try:                                     # الخطوط والشعار إن وُجدت
    import os
    if os.path.isdir("dpp/assets/fonts"):
        datas.append(("dpp/assets/fonts", "dpp/assets/fonts"))
    if os.path.isfile("dpp/assets/logo.ico"):
        datas.append(("dpp/assets/logo.ico", "dpp/assets"))
except Exception:
    pass

hiddenimports = collect_submodules("dpp_lite") + [
    "dpp.db.database", "dpp.db.migrations", "dpp.utils", "dpp.demo",
    "dpp.services.grid", "dpp.services.conflicts", "dpp.services.teachers",
    "dpp.services.timetables", "dpp.services.calendar", "dpp.services.periods",
    "dpp.services.templates", "dpp.services.fullday", "dpp.services.structure",
]

# كل ما لا تحتاجه النسخة الخفيفة يُستبعد ليصغر الحجم ويبقى الإقلاع سريعاً على جهاز قديم
excludes = ["ortools", "numpy", "pandas", "scipy", "matplotlib", "docx", "openpyxl", "reportlab",
            "qtawesome", "PIL", "tkinter", "pytest", "IPython", "PySide6",
            "PySide2.QtWebEngineCore", "PySide2.QtWebEngineWidgets", "PySide2.QtQml", "PySide2.QtQuick",
            "PySide2.QtMultimedia", "PySide2.QtCharts", "PySide2.QtDataVisualization", "PySide2.Qt3DCore",
            "PySide2.QtBluetooth", "PySide2.QtPositioning", "PySide2.QtSensors", "PySide2.QtSerialPort",
            "PySide2.QtWebSockets", "PySide2.QtNetworkAuth", "PySide2.QtRemoteObjects", "PySide2.QtSql",
            "PySide2.QtTest", "PySide2.QtDesigner", "PySide2.QtHelp", "PySide2.QtScxml", "PySide2.QtScript",
            "PySide2.QtLocation", "PySide2.QtTextToSpeech", "PySide2.Qt3DRender"]

a = Analysis(["run_dpp_lite.py"], pathex=["."], binaries=[], datas=datas,
             hiddenimports=hiddenimports, excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="DPP-Lite", console=False,
          icon="dpp/assets/logo.ico" if __import__("os").path.isfile("dpp/assets/logo.ico") else None,
          version=None, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DPP-Lite")
