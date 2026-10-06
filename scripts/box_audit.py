"""Audit OCR region boxes: overlaps, containment, duplicated text, tiny/empty/flagged regions."""
import json, sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

def area(b): return max(0, b["x1"]-b["x0"]) * max(0, b["y1"]-b["y0"])
def inter(a, b):
    return area({"x0": max(a["x0"], b["x0"]), "y0": max(a["y0"], b["y0"]),
                 "x1": min(a["x1"], b["x1"]), "y1": min(a["y1"], b["y1"])})

c, examples = Counter(), []
for p in sorted(Path("titles/crisis").glob(sys.argv[1] if len(sys.argv) > 1 else "*/page_*.json")):
    d = json.loads(p.read_text()); R = d["regions"]; W, H = d["width"], d["height"]
    c["pages"] += 1; c["regions"] += len(R)
    for r in R:
        c["label:" + r["label"]] += 1
        if r["status"] != "ok": c["status:" + r["status"]] += 1
        if not r["text"].strip(): c["empty text"] += 1
        if area(r["bbox"]) < 0.0005 * W * H: c["tiny (<0.05% of page)"] += 1
    for i in range(len(R)):
        for j in range(i+1, len(R)):
            a, b = R[i]["bbox"], R[j]["bbox"]; I = inter(a, b)
            if not I: continue
            small = min(area(a), area(b)) or 1
            frac = I / small
            if frac > 0.9: kind = "contained (>90% of smaller)"
            elif frac > 0.3: kind = "heavy overlap (30-90%)"
            else: kind = "light overlap (<30%)"
            c[kind] += 1
            ta, tb = R[i]["text"].strip(), R[j]["text"].strip()
            sim = SequenceMatcher(None, ta[:400], tb[:400]).ratio() if ta and tb else 0
            if frac > 0.3 and sim > 0.5: c["overlap with duplicated text"] += 1
            if frac > 0.3 and len(examples) < 6:
                examples.append(f"{p.parent.name} {p.stem} {R[i]['id']}({R[i]['label']}) x {R[j]['id']}({R[j]['label']}) "
                                f"overlap={frac:.0%} textsim={sim:.2f} | {ta[:50]!r} | {tb[:50]!r}")
for k, v in sorted(c.items()): print(f"{v:6}  {k}")
print("\nexamples:"); print("\n".join(examples))
