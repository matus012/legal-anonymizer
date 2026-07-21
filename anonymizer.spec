# PyInstaller spec — Phase 7 (context.md §10): single-folder windowed build, no console.
# Build:  .\.venv\Scripts\python.exe -m PyInstaller anonymizer.spec --noconfirm
# Output: dist/Anonymizer/Anonymizer.exe
# NOTE: one-folder (not --onefile): faster start, simpler AV story, and the office
# copies one folder to each laptop. Gazetteers are v2; nothing extra to bundle in v1.

from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["gui\\__main__.py"],
    pathex=["."],
    binaries=[],
    datas=[],
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
