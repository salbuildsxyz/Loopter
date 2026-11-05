# PyInstaller build definition. Run through scripts/build.ps1, or: pyinstaller loop.spec --noconfirm
from pathlib import Path

root = Path(SPECPATH)

a = Analysis(
    [str(root / "loop" / "__main__.py")],
    pathex=[str(root)],
    datas=[(str(root / "loop" / "assets"), "loop/assets")],
    excludes=["tkinter", "matplotlib", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick"],
)
# LOOP never decodes video or renders OpenGL, so these large DLLs are dead weight.
UNUSED_BINARIES = ("opencv_videoio_ffmpeg", "opengl32sw")
a.binaries = [b for b in a.binaries if not any(name in b[0] for name in UNUSED_BINARIES)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LOOP",
    icon=str(root / "loop" / "assets" / "loop.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LOOP", upx=False)
