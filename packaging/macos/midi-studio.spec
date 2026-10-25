# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for MIDI-Studio on macOS (v22ze-223).  Run via build_macos.sh, or:
#   pyinstaller packaging/macos/midi-studio.spec
# One .app; MIDI-Studio-selftest sits next to the app program inside it (Contents/MacOS).
import os, re
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
PAYLOAD = os.path.join(SPECPATH, "payload")
REL = re.search(r'APP_RELEASE = "([^"]+)"', open(os.path.join(ROOT, "sys_platform.py"), encoding="utf-8").read())
VERSION = (REL.group(1) if REL else "0.0.0").replace("-dev", "")

datas = []
for sub in ("lib", "sound"):
    d = os.path.join(PAYLOAD, sub)
    if os.path.isdir(d) and any(f != ".gitkeep" for _r, _d, fs in os.walk(d) for f in fs):
        datas.append((d, sub))
        print("midi-studio.spec: bundling", sub + "/")
    else:
        print("midi-studio.spec: no payload", sub + "/ (system one will be used)")
GUIDE = os.path.join(ROOT, "docs", "MIDI-Studio-User-Guide.pdf")
if os.path.isfile(GUIDE):
    datas.append((GUIDE, "."))

hidden = ["mido.backends.rtmidi", "rtmidi", "fluidsynth"] + collect_submodules("ly")
datas += collect_data_files("ly")
try:
    datas += collect_data_files("certifi")
    hidden += ["certifi"]
except Exception:
    pass

EXCLUDES = ["test", "unittest", "pydoc_data", "matplotlib", "numpy", "scipy", "pandas", "PIL"]

a_app = Analysis([os.path.join(ROOT, "main.py")], pathex=[ROOT], datas=datas, hiddenimports=hidden, excludes=EXCLUDES)
a_self = Analysis([os.path.join(ROOT, "packaging", "linux", "selftest.py")], pathex=[ROOT], datas=[],
                  hiddenimports=hidden, excludes=EXCLUDES)
MERGE((a_app, "MIDI-Studio", "MIDI-Studio"), (a_self, "MIDI-Studio-selftest", "MIDI-Studio-selftest"))

pyz_app = PYZ(a_app.pure)
pyz_self = PYZ(a_self.pure)
exe_app = EXE(pyz_app, a_app.scripts, [], exclude_binaries=True, name="MIDI-Studio", console=False, upx=False)
exe_self = EXE(pyz_self, a_self.scripts, [], exclude_binaries=True, name="MIDI-Studio-selftest", console=True, upx=False)
coll = COLLECT(exe_app, a_app.binaries, a_app.datas, exe_self, a_self.binaries, a_self.datas,
               strip=False, upx=False, name="MIDI-Studio")
app = BUNDLE(
    coll, name="MIDI-Studio.app", icon=None, bundle_identifier="io.github.winthrom.midi-studio",
    info_plist={
        "CFBundleName": "MIDI Studio",
        "CFBundleDisplayName": "MIDI Studio",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
    },
)
