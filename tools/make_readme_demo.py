"""Build the README demo GIF from a synthetic document, through the real GUI.

    uv pip install pillow==12.0.0               # only this script needs it; the app does not
    python -m tools.make_readme_demo            # writes docs/demo.gif + docs/demo_before_after.png

Dev-only. Nothing here is used by the app.

Selection rule (fixed before the first render, not tuned afterwards):
- corpus: ``corpus.generate --n 70 --seed 42 --formats docx,pdf`` into a temp folder (synthetic only);
- document: the FIRST generated PDF in sorted filename order, whatever it is;
- run twice through the Qt wizard (offscreen): once with the "names of the parties" box empty and once
  with the parties' canonical names typed in, as the app's input page asks;
- both results are checked against the document's ground truth with ``eval.leak.find_leaks`` (the
  must-redact items) and BOTH are printed on the GIF's last card, together with every "flag for review"
  item that is still in the output because the review table leaves it unticked by default. The walk-through frames come from the run with names typed in.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")  # offscreen Qt finds no fonts otherwise

import json  # noqa: E402

import fitz  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from corpus.generate import generate  # noqa: E402
from eval.extract import extract  # noqa: E402
from eval.leak import find_leaks, surface_present  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
W, H, CAP = 960, 620, 64


def _run_gui(src: Path, known: str, workdir: Path) -> dict:
    """Scan + export one file through MainWindow; return grabs, counts and the leak check."""
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from gui.app import MainWindow

    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("Segoe UI", 10))
    workdir.mkdir(parents=True, exist_ok=True)
    local = workdir / src.name
    local.write_bytes(src.read_bytes())
    cwd = os.getcwd()
    os.chdir(workdir)  # relative path, so the file list shows a bare file name and no user folder
    try:
        w = MainWindow()
        w.resize(1120, 470)
        w.show()
        w.add_files([local.name])
        w.known_edit.setPlainText(known)
        app.processEvents()
        grabs = {"input": w.grab().toImage()}
        w.start_scan(blocking=True)
        app.processEvents()
        grabs["review"] = w.grab().toImage()
        rows = len(w.scans[local.name].rows)
        w.start_export(blocking=True)
        app.processEvents()
        out = workdir / (local.stem + "_anon.pdf")
    finally:
        os.chdir(cwd)
    gt = json.loads(Path(str(src) + ".gt.json").read_text(encoding="utf-8"))
    ex = extract(str(out))
    leaks = find_leaks(gt, ex)
    must = {(p["surface"], p["type"]) for p in gt["pii"] if p["auto_redact"]}
    # PII the generator marks "flag for human review": the app lists it unticked, so by default it stays.
    review_left = sorted({p["surface"] for p in gt["pii"] if p["should_flag"] and not p["auto_redact"]
                          and surface_present(ex.full_text, p["surface"])})
    shots = {}
    for k, img in grabs.items():
        p = workdir / f"gui_{k}.png"
        img.save(str(p))
        shots[k] = p
    boxes = []
    for name, pdf in (("before", local), ("after", out)):
        p = workdir / f"{name}_p1.png"
        page = fitz.open(str(pdf))[0]
        page.get_pixmap(dpi=110).save(str(p))
        shots[name] = p
        if name == "after":
            boxes = [[v * 110 / 72 for v in r] for s in review_left for r in page.search_for(s)]
    return {"rows": rows, "must": len(must), "leaks": len(leaks), "review_left": review_left,
            "boxes": boxes, "shots": shots}


def _font(size: int, bold: bool = False):
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _compose(named: dict, empty: dict, out_gif: Path, out_png: Path) -> None:
    bg = (246, 246, 246)

    def canvas(cap: str) -> Image.Image:
        c = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(c)
        d.rectangle([0, H - CAP, W, H], fill=(30, 34, 40))
        d.text((24, H - CAP + 15), cap, font=_font(24, True), fill=(255, 255, 255))
        d.text((W - 210, 8), "synthetic document", font=_font(15), fill=(150, 60, 60))
        return c

    def fit(img: Image.Image, bw: int, bh: int) -> Image.Image:
        s = min(bw / img.width, bh / img.height)
        return img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)

    def gui(path: Path, cap: str) -> Image.Image:
        g = fit(Image.open(path).convert("RGB"), W - 40, H - CAP - 44)
        c = canvas(cap)
        x = (W - g.width) // 2
        ImageDraw.Draw(c).rectangle([x - 2, 28, x + g.width + 1, 31 + g.height], outline=(160, 160, 160))
        c.paste(g, (x, 30))
        return c

    def page(path: Path) -> Image.Image:
        p = Image.open(path).convert("RGB")
        return fit(p.crop((60, 70, p.width - 60, 830)), W - 80, H - CAP - 44)

    sh = named["shots"]
    ann = Image.open(sh["after"]).convert("RGB")
    da = ImageDraw.Draw(ann)
    for x0, y0, x1, y1 in named["boxes"]:
        da.rectangle([x0 - 4, y0 - 3, x1 + 4, y1 + 3], outline=(230, 120, 0), width=3)
        tag, f = "^ uncertain: shown for review, left unticked by default", _font(16, True)
        tb = da.textbbox((x0, y1 + 6), tag, font=f)
        da.rectangle([tb[0] - 4, tb[1] - 3, tb[2] + 4, tb[3] + 3], fill=(255, 244, 228), outline=(230, 120, 0))
        da.text((x0, y1 + 6), tag, font=f, fill=(200, 95, 0))
    sh = dict(sh, after=sh["after"].with_name("after_annotated.png"))
    ann.save(sh["after"])
    s1 = gui(sh["input"], "1  Add a contract, type the parties' names")
    s2 = gui(sh["review"], "2  Check what it found (ticked = will be redacted)")
    before, after = page(sh["before"]), page(sh["after"])

    def wipe(t: float) -> Image.Image:
        c = canvas("3  Get a redacted copy (plus a report of every change)")
        x0 = (W - before.width) // 2
        m = Image.new("L", before.size, 0)
        ImageDraw.Draw(m).rectangle([0, 0, round(before.width * t), before.height], fill=255)
        c.paste(Image.composite(after, before, m), (x0, 30))
        d = ImageDraw.Draw(c)
        if 0 < t < 1:
            lx = x0 + round(before.width * t)
            d.line([lx, 30, lx, 30 + before.height], fill=(20, 90, 170), width=4)
        d.rectangle([x0 - 1, 29, x0 + before.width, 30 + before.height], outline=(160, 160, 160))
        return c

    end = Image.new("RGB", (W, H), (30, 34, 40))
    d = ImageDraw.Draw(end)
    review = ", ".join(f"'{s}'" for s in named["review_left"]) or "none"
    lines = [
        ("What happened on this document", _font(34, True), (255, 255, 255)),
        ("", _font(10), None),
        (f"Parties' names typed in:   {named['leaks']} of {named['must']} must-redact items left",
         _font(26, True), (140, 220, 140)),
        (f"Names box left empty:       {empty['leaks']} of {empty['must']} left "
         "(one surname the name lists don't know)", _font(22), (240, 190, 120)),
        (f"Left for the reviewer to decide (unticked by default): {review}", _font(20), (240, 190, 120)),
        ("", _font(10), None),
        ("Checked against the generator's ground truth, every text surface of the file.", _font(20),
         (210, 210, 210)),
        ("Synthetic contract: the first file of corpus.generate --seed 42, not hand-picked.", _font(20),
         (210, 210, 210)),
        ("Runs fully offline. A human still reviews every output.", _font(20), (210, 210, 210)),
    ]
    y = 120
    for text, f, col in lines:
        if text:
            d.text((48, y), text, font=f, fill=col)
        y += f.size + 18

    frames = [(s1, 2600), (s2, 3600), (wipe(0), 1400)]
    frames += [(wipe(k / 10), 90) for k in range(1, 10)] + [(wipe(1), 3200), (end, 4200)]
    pal_src = Image.new("RGB", (W, H * 3))
    for i, im in enumerate((s2, wipe(0.5), end)):
        pal_src.paste(im, (0, i * H))
    pal = pal_src.quantize(colors=160, method=Image.Quantize.MEDIANCUT)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f, _ in frames]
    out_gif.parent.mkdir(parents=True, exist_ok=True)
    q[0].save(out_gif, save_all=True, append_images=q[1:], duration=[ms for _, ms in frames], loop=0, optimize=True)

    full_b, full_a = Image.open(sh["before"]).convert("RGB"), Image.open(sh["after"]).convert("RGB")
    pair = Image.new("RGB", (full_b.width + full_a.width + 30, max(full_b.height, full_a.height)), (255, 255, 255))
    pair.paste(full_b, (0, 0))
    pair.paste(full_a, (full_b.width + 30, 0))
    ImageDraw.Draw(pair).line([full_b.width + 15, 0, full_b.width + 15, pair.height], fill=(160, 160, 160), width=2)
    pair.quantize(colors=64).save(out_png, optimize=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="readme_demo_") as tmp:
        corpus = Path(tmp) / "synthetic"
        generate(70, corpus, 42, ["docx", "pdf"])
        src = sorted(corpus.glob("*.pdf"))[0]
        gt = json.loads(Path(str(src) + ".gt.json").read_text(encoding="utf-8"))
        parties = "\n".join(e["canonical"] for e in gt["entities"])
        empty = _run_gui(src, "", Path(tmp) / "empty")
        named = _run_gui(src, parties, Path(tmp) / "named")
        print(f"{src.name}: names typed -> {named['leaks']}/{named['must']} must-redact left ({named['rows']} rows); "
              f"names empty -> {empty['leaks']}/{empty['must']} left ({empty['rows']} rows); "
              f"review items left: {named['review_left']}")
        _compose(named, empty, REPO / "docs" / "demo.gif", REPO / "docs" / "demo_before_after.png")
    print("wrote docs/demo.gif and docs/demo_before_after.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
