"""Clean OCR region boxes so every word on the page belongs to exactly one region.

Prototype. Reads titles/<title>/<issue>/page_NN.json (never modifies it) and writes
page_NN.clean.json next to it. Steps:

1. junk      drop empty reads and hallucinations (non-Latin script, lone CJK glyphs)
2. glyphs    find glyph blobs on the scan (connected ink; not words, which can bridge
             a narrow column gutter)
3. ownership give each glyph to the region holding the largest share of it (ties: the
             smaller region); words outside every region but touching one join it
4. reshape   each region's box becomes the bounding box of its words; `exclude` lists
             glyphs inside that box owned by other regions ([x0, y0, x1, y1, owner id]),
             so a clip can white them out;
             a region left with no words is dropped
5. reread    a region that lost or gained words is re-read by GLM-OCR on its new,
             masked crop (needs the MLX server on :8080; --no-reread to skip)
   guard     a reread that loses words found nowhere else on the page keeps its old text
             and gets needs_review (queue for an LLM/agent pass)
6. roles     short repeated `abandon` lines at the top/bottom (THE CRISIS, page numbers)
             become role=running_head, which article text skips

Usage: clean_boxes.py ISSUE PAGE [PAGE...] [--title crisis] [--no-reread]
"""
import argparse, json, re, unicodedata
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
RUNNING_HEADS = re.compile(r"^(the crisis( advertiser)?|\d{1,3}|[ivxlc]+|along the color line|opinion|"
                           r"editorial|the n\. ?a\. ?a\. ?c\. ?p\.?|what to read|letters|books)\.?$", re.I)
PICTURE = {"figure", "image", "isolate_formula"}


def junk_reason(text):
    t = text.strip()
    if not t:
        return "empty"
    letters = [c for c in t if c.isalpha()]
    if letters:
        foreign = sum(1 for c in letters if not unicodedata.name(c, "").startswith("LATIN"))
        if foreign / len(letters) > 0.3:
            return "non-latin hallucination"
    return None


DICT = None


def real_losses(before, after):
    """Words gone from the page that matter: dictionary words not part of a word still
    there. Garbled cross-column reads ("courtment") and fragments ("enlist" while
    "enlisted" remains) are what cleanup is meant to remove."""
    global DICT
    if DICT is None:
        try:
            DICT = {w.strip().lower() for w in open("/usr/share/dict/words")}
        except OSError:
            DICT = set()
    gone = before - after
    joined = " ".join(after)
    return {w for w in gone if (not DICT or w in DICT) and w not in joined}


def word_blobs(gray):
    """Connected word-sized blobs: (labels image, stats) with ink-only masks."""
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # no morphological opening: on low-res scans it erases 1-px strokes of small type;
    # specks are dropped by size below instead
    # glyph level: a word-level dilation bridges narrow gutters and hands a word in one
    # column to the box of the next; glyphs never cross a gutter
    joined = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    labels = np.where(ink > 0, labels, 0)
    speck = np.where(stats[:, cv2.CC_STAT_AREA] < 4)[0]
    if len(speck):
        labels[np.isin(labels, speck)] = 0
    return n, labels, stats


_band_cache = {}


def bands(labels, y0, y1, x0, x1, W):
    """Column bands across x0..x1, split at vertical white strips over rows y0..y1."""
    key = (y0, y1, x0, x1)
    if key not in _band_cache:
        prof = (labels[y0:y1, x0:x1] > 0).any(axis=0)
        gap = max(6, W // 250)
        out, start, white = [], None, 0
        for x, ink in enumerate(prof):
            if ink:
                if start is None:
                    start = x
                elif white >= gap:
                    out.append((x0 + start, x0 + x - white))
                    start = x
                white = 0
            else:
                white += 1
        if start is not None:
            out.append((x0 + start, x0 + len(prof) - white))
        _band_cache[key] = out
    return _band_cache[key]


def resolve_tie(k, cands, stats, core, boxes, labels, areas, W, regions):
    """A glyph inside several regions goes to the one whose own text shares its column.

    Over the rows where the candidate boxes overlap, split their union at white
    gutters; the glyph's band goes to the candidate whose core (uniquely held glyphs)
    overlaps that band most, counting only core glyphs in the overlap rows (a single
    full-width line elsewhere in a box mustn't claim the next column). Failing that, a
    detector region beats a residual one (label "text": newspaper-ocr's residual pass
    reads ink the detector missed), then the smaller region wins.
    """
    small = min(cands, key=lambda i: areas[i])
    sb = boxes[small]
    def inside(a, b):   # share of box a lying inside box b
        iw = max(0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
        ih = max(0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
        return iw * ih / max(1, areas[small])
    if all(inside(sb, boxes[i]) > 0.9 for i in cands if i != small):
        return small        # nested boxes: the inner, more specific one wins
    x, y, w, h, _ = stats[k]
    bs = [boxes[i] for i in cands]
    oy0, oy1 = max(b["y0"] for b in bs), min(b["y1"] for b in bs)
    ux0, ux1 = min(b["x0"] for b in bs), max(b["x1"] for b in bs)
    if oy1 > oy0:
        cx = x + w / 2
        for bx0, bx1 in bands(labels, oy0, oy1, ux0, ux1, W):
            if bx0 <= cx <= bx1:
                scores = {}
                for i in cands:
                    g = core[i]
                    g = g[(stats[g, 1] < oy1) & (stats[g, 1] + stats[g, 3] > oy0)]
                    if len(g):
                        scores[i] = max(0, min(bx1, (stats[g, 0] + stats[g, 2]).max()) - max(bx0, stats[g, 0].min()))
                if scores and max(scores.values()) > 0:
                    top = max(scores.values())
                    best = [i for i in scores if scores[i] == top]
                    return min(best, key=lambda i: areas[i])
                break
    detector = [i for i in cands if regions[i]["label"] != "text"]
    return min(detector or cands, key=lambda i: areas[i])


def clean_page(issue_dir, page, reread=True, recognizer=None):
    src = issue_dir / f"page_{page:02d}.json"
    d = json.loads(src.read_text())
    gray = np.array(Image.open(issue_dir / d["image"]).convert("L"))
    H, W = gray.shape
    log = []

    # 1. junk
    regions = []
    for r in d["regions"]:
        why = junk_reason(r["text"]) if r["label"] not in PICTURE else None
        if why:
            log.append(f"drop {r['id']} ({r['label']}): {why} {r['text'][:30]!r}")
        else:
            regions.append(dict(r))

    # 2-3. words and ownership
    n, labels, stats = word_blobs(gray)
    ink_per_blob = np.bincount(labels.ravel(), minlength=n)
    boxes = [r["bbox"] for r in regions]
    areas = [(b["x1"] - b["x0"]) * (b["y1"] - b["y0"]) for b in boxes]
    share = np.zeros((len(regions), n))
    for i, b in enumerate(boxes):
        sub = labels[b["y0"]:b["y1"], b["x0"]:b["x1"]]
        share[i] = np.bincount(sub.ravel(), minlength=n) / np.maximum(ink_per_blob, 1)
    share[:, 0] = 0
    owner = np.full(n, -1)
    ties = {}
    for k in range(1, n):
        if ink_per_blob[k] == 0:
            continue
        best = share[:, k].max()
        if best <= 0:
            continue
        cands = [i for i in range(len(regions)) if share[i, k] >= best - 0.05]
        if len(cands) == 1:
            owner[k] = cands[0]
        else:
            ties[k] = cands
    # each region's core: the glyphs only it holds
    core = {i: np.where(owner == i)[0] for i in range(len(regions))}
    for k, cands in ties.items():
        owner[k] = resolve_tie(k, cands, stats, core, boxes, labels, areas, W, regions)

    # unowned blobs touching a region (clipped edge letters) join the nearest one
    pad = max(6, H // 300)
    for k in np.where((owner == -1) & (ink_per_blob > 0))[0]:
        if k == 0:
            continue
        x, y, w, h, _ = stats[k]
        for i, b in enumerate(boxes):
            if x < b["x1"] + pad and x + w > b["x0"] - pad and y < b["y1"] + pad and y + h > b["y0"] - pad:
                owner[k] = i
                break

    # coverage: ink outside every region
    total_ink = ink_per_blob[1:].sum()
    unowned_ink = ink_per_blob[1:][owner[1:] == -1].sum()

    # 4. reshape
    out, dropped_ids = [], set()
    for i, r in enumerate(regions):
        mine = np.where(owner == i)[0]
        b = r["bbox"]
        before = set(np.where(share[i] > 0.5)[0])
        if not len(mine):
            if r["label"] in PICTURE:
                out.append({**r, "role": "picture", "exclude": [], "changed": False})
            else:
                log.append(f"drop {r['id']} ({r['label']}): owns no words (all ink belongs to other regions)")
                dropped_ids.add(r["id"])
            continue
        xs0, ys0 = stats[mine, 0], stats[mine, 1]
        xs1, ys1 = xs0 + stats[mine, 2], ys0 + stats[mine, 3]
        m = max(2, H // 600)                 # small margin so faint edges aren't cut
        nb = {"x0": max(0, int(xs0.min()) - m), "y0": max(0, int(ys0.min()) - m),
              "x1": min(W, int(xs1.max()) + m), "y1": min(H, int(ys1.max()) + m)}
        if r["label"] in PICTURE:            # keep the picture's frame, grow to cover its words
            nb = {"x0": min(nb["x0"], b["x0"]), "y0": min(nb["y0"], b["y0"]),
                  "x1": max(nb["x1"], b["x1"]), "y1": max(nb["y1"], b["y1"])}
        inside = set(np.unique(labels[nb["y0"]:nb["y1"], nb["x0"]:nb["x1"]])) - {0}
        exclude = [[int(stats[k, 0]), int(stats[k, 1]), int(stats[k, 0] + stats[k, 2]), int(stats[k, 1] + stats[k, 3]),
                    regions[owner[k]]["id"]]
                   for k in inside if owner[k] not in (i, -1)]
        lost = {k for k in before if owner[k] != i}
        gained = {k for k in mine if k not in before and stats[k, 4] > 0}
        lost_ink = ink_per_blob[list(lost)].sum() if lost else 0
        own_ink = ink_per_blob[mine].sum()
        gained_ink = ink_per_blob[list(gained)].sum() if gained else 0
        changed = lost_ink > 0.03 * (own_ink + lost_ink) or gained_ink > 0.03 * own_ink
        if changed:
            log.append(f"reshape {r['id']} ({r['label']}): lost {100 * lost_ink / (own_ink + lost_ink):.0f}% "
                       f"of its ink, gained {100 * gained_ink / own_ink:.0f}%")
        out.append({**r, "bbox": nb, "bbox_ocr": b, "exclude": exclude, "changed": bool(changed)})

    # 5. reread changed text regions on their masked crop
    for r in out:
        if not (r.get("changed") and reread and r.get("role") != "picture"):
            continue
        b = r["bbox"]
        crop = Image.fromarray(gray[b["y0"]:b["y1"], b["x0"]:b["x1"]].copy())
        arr = np.array(crop)
        for x0, y0, x1, y1, _ in r["exclude"]:
            arr[max(0, y0 - b["y0"]):max(0, y1 - b["y0"]), max(0, x0 - b["x0"]):max(0, x1 - b["x0"])] = 255
        crop = Image.fromarray(arr).convert("RGB")
        old = r["text"]
        r["text"], r["status"] = read(recognizer, crop, b)
        r["text_before_clean"] = old
        log.append(f"reread {r['id']}: {old[:40]!r} -> {r['text'][:40]!r}")

    # 6. roles
    for r in out:
        if "role" in r:
            continue
        b, t = r["bbox"], " ".join(r["text"].split())
        edge = b["y1"] < 0.09 * H or b["y0"] > 0.93 * H
        r["role"] = "running_head" if r["label"] == "abandon" and edge and RUNNING_HEADS.match(t) else "text"

    # report overlaps that remain between owned-word boxes (should be small)
    def inter(a, c):
        return max(0, min(a["x1"], c["x1"]) - max(a["x0"], c["x0"])) * max(0, min(a["y1"], c["y1"]) - max(a["y0"], c["y0"]))
    remaining = sum(1 for i in range(len(out)) for j in range(i + 1, len(out))
                    if inter(out[i]["bbox"], out[j]["bbox"]) > 0)
    def words(rs):
        return {w for r in rs for w in re.findall(r"[a-z]{4,}", r["text"].lower())}
    kept = {r["id"] for r in out} | dropped_ids
    before_words = words([r for r in d["regions"] if r["id"] in kept])
    # guard: a reread that loses words found nowhere else on the page (GLM sometimes
    # skips an indented first line) keeps its old text and is queued for review
    lost = real_losses(before_words, words(out))
    for r in out:
        if "text_before_clean" in r and lost & words([{"text": r["text_before_clean"]}]):
            gone = sorted(lost & words([{"text": r["text_before_clean"]}]))
            r["text_reread"], r["text"] = r["text"], r["text_before_clean"]
            r["needs_review"] = f"reread lost words: {' '.join(gone[:12])}"
            log.append(f"REVIEW {r['id']}: reread lost {' '.join(gone[:12])}; kept old text")
    lost_words = sorted(real_losses(before_words, words(out)))
    if lost_words:
        log.append(f"CHECK words lost from page text: {' '.join(lost_words[:30])}")
    summary = {"regions_before": len(d["regions"]), "regions_after": len(out), "lost_words": lost_words,
               "needs_review": [r["id"] for r in out if r.get("needs_review")],
               "unowned_ink_pct": round(100 * unowned_ink / max(total_ink, 1), 2),
               "box_overlaps_after": remaining, "log": log}
    clean = {**{k: v for k, v in d.items() if k != "regions"}, "regions": out, "clean": summary}
    (issue_dir / f"page_{page:02d}.clean.json").write_text(json.dumps(clean, indent=1, ensure_ascii=False))
    return clean


def read(recognizer, crop, b):
    from newspaper_ocr.models import BBox, Region
    reg = Region(bbox=BBox(b["x0"], b["y0"], b["x1"], b["y1"]), image=crop, label="text")
    res = recognizer.recognize(reg)
    return res.text, res.status


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("issue"); ap.add_argument("pages", type=int, nargs="+")
    ap.add_argument("--title", default="crisis"); ap.add_argument("--no-reread", action="store_true")
    a = ap.parse_args()
    rec = None
    if not a.no_reread:
        from newspaper_ocr.recognizers.glm_ocr import GlmOcrRecognizer
        rec = GlmOcrRecognizer(mode="api")
    for p in a.pages:
        c = clean_page(ROOT / "titles" / a.title / a.issue, p, reread=not a.no_reread, recognizer=rec)["clean"]
        print(f"{a.issue} p{p}: {c['regions_before']} -> {c['regions_after']} regions, "
              f"unowned ink {c['unowned_ink_pct']}%, box overlaps left {c['box_overlaps_after']}")
        for line in c["log"]:
            print("   ", line)
