# THIRD_PARTY.md — third-party code and data

Code dependencies below (pinned in `requirements.txt`; licence read from installed package
metadata, 2026-09-26). Bundled **data** lists (gazetteers, name lists) are covered in
`LICENSES.md` — that file stays the single source for data provenance.

| package | version | licence | role | ships in frozen .exe |
|---|---|---|---|---|
| pymupdf | 1.28.0 | **AGPL-3.0** or Artifex commercial | PDF read / redact | yes |
| PySide6 | 6.11.1 | LGPL-3.0 (or GPL-2.0/3.0) | desktop GUI | yes |
| python-docx | 1.2.0 | MIT | .docx read / write | yes |
| lxml | 6.1.1 | BSD-3-Clause | XML (via python-docx) | yes |
| typing_extensions | 4.16.0 | PSF-2.0 | typing backports | yes |
| pyinstaller | 6.21.0 | GPL-2.0-or-later + bootloader exception | build tool only | bootloader only (exception applies) |
| pytest | 9.1.1 | MIT | tests | no |
| iniconfig | 2.3.0 | MIT | pytest dep | no |
| pluggy | 1.6.0 | MIT | pytest dep | no |
| packaging | 26.2 | Apache-2.0 OR BSD-2-Clause | pytest dep | no |
| Pygments | 2.20.0 | BSD-2-Clause | pytest dep | no |
| colorama | 0.4.6 | BSD-3-Clause | pytest dep | no |

## Licence implications (open — owner decision)

- **PyMuPDF is AGPL-3.0.** Distributing the frozen application (the PyInstaller build handed to
  the office) conveys PyMuPDF, so the distributed program must be offered under AGPL-3.0 terms
  (corresponding source available to the recipient) — or an Artifex commercial licence is
  needed. Same class of issue as Ultralytics in the robotics repos.
- **PySide6 is LGPL-3.0.** The PyInstaller one-folder build keeps Qt as replaceable shared
  libraries, which satisfies LGPL relinking; keep it that way (no static linking).
- **This repository has no LICENSE file.** Without one the code is all-rights-reserved even
  though the repo is public. Choosing a licence is the owner's call; with PyMuPDF in the
  dependency set, AGPL-3.0 is the only choice that needs no commercial PyMuPDF licence.

## Data

- Bundled gazetteer / name lists: CC0-1.0, CC-BY-4.0 (ÚGKK SR, attribution required), MIT —
  see `LICENSES.md`.
- Evaluation corpus (`data/`): synthetic, produced by `corpus/generate.py` (seeded,
  deterministic); gitignored, never tracked. No client documents are, or ever were, tracked in
  this repository (history scanned 2026-09-26).
