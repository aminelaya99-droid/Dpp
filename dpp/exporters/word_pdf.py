"""تحويل ملفات Word إلى PDF عبر Microsoft Word المثبّت (Windows)، بسكربت PowerShell يستعمل COM.

إذا لم يكن Word مثبّتاً (أو فشل التحويل) يعيد الملفات التي لم تتحول، فيستعمل البرنامج محركه الداخلي بدلها.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

PS = r"""
$ErrorActionPreference = 'Stop'
$pairs = Get-Content -LiteralPath '{list}' -Encoding UTF8
$w = New-Object -ComObject Word.Application
$w.Visible = $false
$w.DisplayAlerts = 0
try {{
  for ($i = 0; $i -lt $pairs.Count; $i += 2) {{
    $d = $w.Documents.Open($pairs[$i], $false, $true)
    $d.ExportAsFixedFormat($pairs[$i + 1], 17)
    $d.Close($false)
  }}
}} finally {{
  $w.Quit()
}}
"""


def word_installed() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"))
        return True
    except Exception:
        return False


def convert(pairs: list[tuple[Path, Path]], timeout: int = 900, poll=None) -> list[tuple[Path, Path]]:
    """يحوّل (docx، pdf) دفعة واحدة. يعيد الأزواج التي لم تُنشأ (لتُعالج بالمحرك الداخلي).
    poll: دالة تُستدعى أثناء الانتظار (لإبقاء الواجهة حية)."""
    if not pairs:
        return []
    if not word_installed():
        return list(pairs)
    tmp = Path(tempfile.mkdtemp(prefix="dpp_word_"))
    lst = tmp / "pairs.txt"
    lst.write_text("\n".join(f"{Path(a).resolve()}\n{Path(b).resolve()}" for a, b in pairs), encoding="utf-8-sig")
    ps1 = tmp / "conv.ps1"
    ps1.write_text(PS.format(list=str(lst).replace("'", "''")), encoding="utf-8-sig")
    for _a, b in pairs:
        try:
            Path(b).unlink()
        except OSError:
            pass
    flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
    try:
        pr = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        import time
        t0 = time.time()
        while pr.poll() is None:
            if time.time() - t0 > timeout:
                pr.kill()
                break
            if poll:
                poll()
            time.sleep(0.15)
    except Exception:
        return list(pairs)
    return [(a, b) for a, b in pairs if not Path(b).exists() or Path(b).stat().st_size == 0]
