"""Package voted contents, cleaned regions and scaled page scans for the results browser.

Writes OUT/data/<issue>.json and OUT/img/<issue>/pNN.jpg (scans scaled to WIDTH px).
Usage: build_viewer.py OUT [--width 900]
"""
import argparse, json, re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SKIP_TYPES = {"masthead"}
PAGE_NUM = re.compile(r"^\[?(page number|\d+\.?)\]?$", re.I)


def build(out, width):
    issues = []
    for toc_path in sorted((ROOT / "titles/crisis").glob("*/toc.voted.json")):
        issue_dir = toc_path.parent
        iss = issue_dir.name
        rec = json.loads((issue_dir / "issue.json").read_text())
        toc = json.loads(toc_path.read_text())
        arts = [a for a in toc["articles"] if not a["is_advertisement"] and a["type"] not in SKIP_TYPES
                and not PAGE_NUM.match((a["title"] or "").strip())
                and (a["title"] or "").strip().upper() not in ("THE CRISIS", "THE CRISIS ADVERTISER")]
        needed = {}
        for a in arts:
            for r in a["regions"]:
                needed.setdefault(r["page"], set()).update(r["ids"])
        pages, regions = {}, {}
        (out / "img" / iss).mkdir(parents=True, exist_ok=True)
        for p in sorted(needed):
            d = json.loads((issue_dir / f"page_{p:02d}.clean.json").read_text())
            img = Image.open(issue_dir / d["image"]).convert("RGB")
            s = min(1.0, width / img.width)
            small = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
            name = f"img/{iss}/p{p:02d}.jpg"
            small.save(out / name, quality=55, optimize=True, progressive=True)
            pages[p] = {"img": name, "w": small.width, "h": small.height}
            def sc(v):
                return round(v * s)
            regs = {}
            for r in d["regions"]:
                b = r["bbox"]
                regs[r["id"]] = {
                    "b": [sc(b["x0"]), sc(b["y0"]), sc(b["x1"]), sc(b["y1"])],
                    "t": r["text"] if r["id"] in needed[p] else "",
                    "rh": r.get("role") == "running_head",
                    "x": [[sc(e[0]), sc(e[1]), sc(e[2]), sc(e[3]), e[4]] for e in r.get("exclude", [])
                          if len(e) == 5] if r["id"] in needed[p] else [],
                }
            regions[p] = regs
        articles = [{"id": a["id"], "title": a["title"], "author": a.get("author"),
                     "section": a.get("section"), "type": a["type"], "pages": a["pages"],
                     "regions": a["regions"], "agree": a.get("vote_agreement")} for a in arts]
        data = {"issue": iss, "volume": rec.get("volume"), "number": rec.get("number"),
                "mjp": rec["source"].get("url"), "pages": pages, "regions": regions,
                "articles": articles}
        (out / "data").mkdir(parents=True, exist_ok=True)
        (out / "data" / f"{iss}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        issues.append({"issue": iss, "volume": rec.get("volume"), "number": rec.get("number"),
                       "articles": len(articles), "pages": len(rec["pages"])})
        print(iss, len(articles), "articles,", len(pages), "page images")
    (out / "data" / "issues.json").write_text(json.dumps(issues))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("--width", type=int, default=900)
    a = ap.parse_args()
    build(Path(a.out), a.width)
