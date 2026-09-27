# PyInstaller spec — Phase 7 (context.md §10): single-folder windowed build, no console.
# Build:  .\.venv\Scripts\python.exe -m PyInstaller anonymizer.spec --noconfirm
# Output: dist/Anonymizer/Anonymizer.exe
# NOTE: one-folder (not --onefile): faster start, simpler AV story, and the office
# copies one folder to each laptop.
#
# v1.1: the gazetteers are no longer deferred. detect/gazetteer_data/*.json (obce, ulice,
# katastralne_uzemia, first_names, surnames, stoplist -- ~330 KB total, every source CC0 or
# CC BY 4.0, see LICENSES.md) MUST be bundled: they are plain data files, so PyInstaller's
# import analysis cannot see them and would ship an .exe whose gazetteer silently matches
# nothing. That failure mode is invisible in testing on the dev machine, where the files are
# found on disk next to the source -- which is exactly why it is called out here.
# The loader in detect/gazetteer.py resolves its data directory through sys._MEIPASS when
# frozen and falls back to the package directory otherwise.

from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["gui\\__main__.py"],
    pathex=["."],
    binaries=[],
    datas=[("detect/gazetteer_data/*.json", "detect/gazetteer_data")],
    hiddenimports=(
        collect_submodules("detect")
        + collect_submodules("writer")
        + collect_submodules("gui")
    ),
    hookspath=[],
    runtime_hooks=[],
    # Heavy libs the app never imports — keep the folder small.
    excludes=["tkinter", "corpus", "eval", "pytest", "PIL", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Anonymizer",
    debug=False,
    upx=False,
    console=False,  # context.md §10: no console window
    version="version_info.txt",  # metadata lowers AV heuristic score of the unsigned exe
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Anonymizer",
)

# AGPL-3.0 (PyMuPDF, see THIRD_PARTY.md): the licence text must travel with the program.
# Copied next to Anonymizer.exe, NOT via `datas` -- PyInstaller >= 6 puts datas under
# _internal/, where a recipient would never look. LICENSES.md carries the CC BY 4.0
# attribution the bundled ÚGKK gazetteer requires.
import os
import shutil

for _name in ("LICENSE", "THIRD_PARTY.md", "LICENSES.md"):
    shutil.copy2(_name, os.path.join(DISTPATH, "Anonymizer", _name))
