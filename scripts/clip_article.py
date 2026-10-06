"""Clip one article from a cleaned issue: its full text and a PNG of just its regions.

Uses toc.json (from `paperpress enrich`) for which regions make up the article, and
page_NN.clean.json (from clean_boxes.py) for the cleaned boxes. Pages without a clean
file fall back to the raw OCR boxes, with a warning.

The PNG has one panel per page, stacked: the union of the article's boxes on that page,
on white, with every glyph owned by another article's region whited out.

Usage: clip_article.py ISSUE "title words" [--title crisis] [--out boxwork/clips]
       clip_article.py ISSUE --id p22a1
"""
import argparse, json, re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent


def find_article(toc, query=None, aid=None):
    arts = [a for a in toc["articles"] if not a["is_advertisement"]]
    if aid:
        return next(a for a in arts if a["id"] == aid)
    q = query.lower()
    hits = [a for a in arts if q in (a["title"] or "").lower()]
    if not hits:
        raise SystemExit(f"no article title contains {query!r}")
    return max(hits, key=lambda a: len(a["pages"]))


def load_page(issue_dir, page):
    clean = issue_dir / f"page_{page:02d}.clean.json"
    if clean.exists():
        return json.loads(clean.read_text()), True
    return json.loads((issue_dir / f"page_{page:02d}.json").read_text()), False


def clip(issue_dir, art):
    texts, panels, warnings = [], [], []
    for ref in art["regions"]:
        page = ref["page"]
        d, cleaned = load_page(issue_dir, page)
        if not cleaned:
            warnings.append(f"p{page}: no clean file, using raw OCR boxes")
        byid = {r["id"]: r for r in d["regions"]}
        regs = [byid[i] for i in ref["ids"] if i in byid]
        missing = [i for i in ref["ids"] if i not in byid]
        if missing:
            warnings.append(f"p{page}: regions {missing} dropped by cleaning")
        if not regs:
            continue
        ids = {r["id"] for r in regs}
        for r in regs:
            if r.get("role") != "running_head" and r["text"].strip():
                texts.append(r["text"].strip())
        img = Image.open(issue_dir / d["image"]).convert("RGB")
        x0 = min(r["bbox"]["x0"] for r in regs); y0 = min(r["bbox"]["y0"] for r in regs)
        x1 = max(r["bbox"]["x1"] for r in regs); y1 = max(r["bbox"]["y1"] for r in regs)
        panel = Image.new("RGB", (x1 - x0, y1 - y0), "white")
        for r in regs:
            b = r["bbox"]
            panel.paste(img.crop((b["x0"], b["y0"], b["x1"], b["y1"])), (b["x0"] - x0, b["y0"] - y0))
        draw = ImageDraw.Draw(panel)
        for r in regs:   # white out glyphs owned by regions outside this article
            for ex in r.get("exclude", []):
                if len(ex) == 5 and ex[4] in ids:
                    continue
                draw.rectangle((ex[0] - x0, ex[1] - y0, ex[2] - x0, ex[3] - y0), fill="white")
        # the union box can take in other regions' boxes that sit between ours
        for r in d["regions"]:
            if r["id"] in ids:
                continue
            b = r["bbox"]
            if b["x1"] > x0 and b["x0"] < x1 and b["y1"] > y0 and b["y0"] < y1:
                draw.rectangle((b["x0"] - x0, b["y0"] - y0, b["x1"] - x0, b["y1"] - y0), fill="white")
                for o in regs:
                    ob = o["bbox"]
                    ix0, iy0 = max(ob["x0"], b["x0"]), max(ob["y0"], b["y0"])
                    ix1, iy1 = min(ob["x1"], b["x1"]), min(ob["y1"], b["y1"])
                    if ix1 > ix0 and iy1 > iy0:   # overlap: restore ours, minus that region's glyphs
                        panel.paste(img.crop((ix0, iy0, ix1, iy1)), (ix0 - x0, iy0 - y0))
                        for ex in o.get("exclude", []):
                            if len(ex) == 5 and ex[4] not in ids:
                                draw.rectangle((ex[0] - x0, ex[1] - y0, ex[2] - x0, ex[3] - y0), fill="white")
        panels.append((page, panel))
    return "\n\n".join(texts), panels, warnings


def stack(panels, label):
    font = ImageFont.load_default(size=22)
    gap, head = 24, 34
    W = max(p.width for _, p in panels)
    H = sum(p.height + head + gap for _, p in panels)
    out = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(out)
    y = 0
    for page, p in panels:
        d.text((4, y + 6), f"{label}, p. {page}", fill="#666", font=font)
        d.line((0, y + head - 4, W, y + head - 4), fill="#ccc", width=2)
        out.paste(p, (0, y + head))
        y += head + p.height + gap
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("issue"); ap.add_argument("query", nargs="?")
    ap.add_argument("--id"); ap.add_argument("--title", default="crisis")
    ap.add_argument("--out", default="boxwork/clips")
    a = ap.parse_args()
    issue_dir = ROOT / "titles" / a.title / a.issue
    art = find_article(json.loads((issue_dir / "toc.json").read_text()), a.query, a.id)
    text, panels, warnings = clip(issue_dir, art)
    out = ROOT / a.out; out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", (art["title"] or art["id"]).lower()).strip("-")[:40]
    stem = out / f"{a.issue}_{slug}"
    label = f"The Crisis, {a.issue[:7]}: {art['title']}"
    stack(panels, label).save(f"{stem}.png")
    Path(f"{stem}.txt").write_text(f"{art['title']}\n{art.get('author') or ''}\n\n{text}\n")
    print(f"{art['id']} {art['title']!r} pages {art['pages']} -> {stem}.png / .txt "
          f"({len(text.split())} words)")
    for w in warnings:
        print("  warning:", w)
