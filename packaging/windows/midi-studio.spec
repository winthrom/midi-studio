# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for MIDI-Studio (v22ze-122).  Run via build_windows.ps1,
# or:  pyinstaller packaging/windows/midi-studio.spec
# One folder, two programs sharing the same libraries:
#   MIDI-Studio.exe           the app (no console window)
#   MIDI-Studio-selftest.exe  console program that checks the bundle
import os, sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
PAYLOAD = os.path.join(ROOT, "packaging", "windows", "payload")
ICON = os.path.join(SPECPATH, "midi-studio.ico") if sys.platform == "win32" else None

# Payload folders become <bundle>/lib and <bundle>/sound, which is where
# app_resources.py looks (sys._MEIPASS/lib, sys._MEIPASS/sound).
datas = []
for sub in ("lib", "sound"):
    d = os.path.join(PAYLOAD, sub)
    has_files = os.path.isdir(d) and any(
        f != ".gitkeep" for _r, _d, fs in os.walk(d) for f in fs)
    if has_files:
        datas.append((d, sub))
        print("midi-studio.spec: bundling", sub + "/")
    else:
        print("midi-studio.spec: no payload", sub + "/ (system one will be used)")

hidden = ["mido.backends.rtmidi", "rtmidi", "fluidsynth"] + collect_submodules("ly")
datas += collect_data_files("ly")

EXCLUDES = ["test", "unittest", "pydoc_data", "matplotlib", "numpy", "scipy", "pandas", "PIL"]

a_app = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT], datas=datas, hiddenimports=hidden, excludes=EXCLUDES,
)
a_self = Analysis(
    [os.path.join(ROOT, "packaging", "linux", "selftest.py")],
    pathex=[ROOT], datas=[], hiddenimports=hidden, excludes=EXCLUDES,
)
MERGE((a_app, "MIDI-Studio", "MIDI-Studio"),
      (a_self, "MIDI-Studio-selftest", "MIDI-Studio-selftest"))

pyz_app = PYZ(a_app.pure)
pyz_self = PYZ(a_self.pure)

exe_app = EXE(
    pyz_app, a_app.scripts, [], exclude_binaries=True,
    name="MIDI-Studio", console=False, icon=ICON, upx=False,
)
exe_self = EXE(
    pyz_self, a_self.scripts, [], exclude_binaries=True,
    name="MIDI-Studio-selftest", console=True, icon=ICON, upx=False,
)
coll = COLLECT(
    exe_app, a_app.binaries, a_app.datas,
    exe_self, a_self.binaries, a_self.datas,
    strip=False, upx=False, name="MIDI-Studio",
)
