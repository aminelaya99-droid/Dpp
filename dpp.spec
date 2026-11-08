# -*- mode: python ; coding: utf-8 -*-
# بناء DPP بـ PyInstaller:  pyinstaller --noconfirm dpp.spec
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = [("dpp/assets", "dpp/assets"), ("dpp/db/schema.sql", "dpp/db")]
datas += collect_data_files("qtawesome")
datas += collect_data_files("arabic_reshaper")
datas += collect_data_files("docx")
datas += [("dpp/assets/_keep", "docx/parts")]  # python-docx يحل المسار عبر docx/parts/..
datas += collect_data_files("reportlab")
datas += collect_data_files("openpyxl")
binaries = collect_dynamic_libs("ortools")
hiddenimports = collect_submodules("ortools.sat") + collect_submodules("dpp") + ["arabic_reshaper", "bidi.algorithm"]

a = Analysis(["run_dpp.py"], pathex=["."], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["tkinter", "matplotlib", "scipy", "fontTools", "pytest", "IPython",
                       "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
                       "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQuick3D",
                       "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
                       "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort",
                       "PySide6.QtWebSockets", "PySide6.QtNetworkAuth", "PySide6.QtRemoteObjects", "PySide6.QtSql",
                       "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
                       "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtLocation", "PySide6.QtScxml",
                       "PySide6.QtGraphs"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="DPP", console=False, icon="dpp/assets/logo.ico",
          version=None, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DPP")
