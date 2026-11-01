# -*- mode: python ; coding: utf-8 -*-
# بناء DPP بـ PyInstaller:  pyinstaller dpp.spec
# الناتج: dist/DPP/DPP.exe (مجلد واحد، تشغيل أسرع من ملف واحد)

block_cipher = None

a = Analysis(
    ["run_dpp.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[
        "dpp.ui.dashboard_view", "dpp.ui.structure_view", "dpp.ui.planner.planner_page",
        "dpp.ui.scheduler_view", "dpp.ui.data_view", "dpp.ui.curriculum_view", "dpp.ui.progress_view",
        "dpp.ui.events_view", "dpp.ui.shooting_view", "dpp.ui.print_view", "dpp.ui.import_view",
        "dpp.ui.settings_view", "PySide6.QtPrintSupport", "sqlalchemy.dialects.sqlite",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "dpp.tests", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="DPP",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="DPP")
