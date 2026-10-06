"""Before/after overlay of OCR boxes vs cleaned boxes (excluded words shaded)."""
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

COL = {"title": "red", "plain_text": "blue", "text": "magenta", "abandon": "gray", "figure": "green"}
font = ImageFont.load_default(size=34)

def draw(img, regions, cleaned):
    im = img.copy(); dr = ImageDraw.Draw(im, "RGBA")
    for r in regions:
        b = r["bbox"]; c = COL.get(r["label"], "orange")
        if cleaned:
            for x0, y0, x1, y1, *_ in r.get("exclude", []):
                dr.rectangle((x0, y0, x1, y1), fill=(255, 160, 0, 110))
            if r.get("role") == "running_head": c = "#999999"
        dr.rectangle((b["x0"], b["y0"], b["x1"], b["y1"]), outline=c, width=5)
        tag = r["id"] + ("*" if cleaned and r.get("changed") else "") + (" RH" if r.get("role") == "running_head" else "")
        dr.text((b["x0"] + 6, b["y0"] + 2), tag, fill=c, font=font)
    return im

iss, pages = sys.argv[1], [int(p) for p in sys.argv[2:]]
for p in pages:
    base = Path("titles/crisis") / iss
    a = json.loads((base / f"page_{p:02d}.json").read_text())
    b = json.loads((base / f"page_{p:02d}.clean.json").read_text())
    img = Image.open(base / a["image"]).convert("RGB")
    L, R = draw(img, a["regions"], False), draw(img, b["regions"], True)
    out = Image.new("RGB", (L.width * 2 + 40, L.height), "white"); out.paste(L, (0, 0)); out.paste(R, (L.width + 40, 0))
    out.thumbnail((2000, 1500)); out.save(f"boxwork/compare_{iss}_p{p}.png")
