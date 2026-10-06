"""After `paperpress add pdf`, copy MJP/Brown metadata into each issue.json.

The Crisis is monthly: PDFs are named YYYY-MM-01 only because the PDF importer needs a
day, so mark the date as month precision and add volume, number, source link and rights.
"""
import csv, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
meta = {r["filename"]: r for r in csv.DictReader(open(ROOT / "pdfs" / "manifest.csv"))}


def num(v):
    return int(v) if v and str(v).isdigit() else (v or None)


n = 0
for path in sorted((ROOT / "titles" / "crisis").glob("*/issue.json")):
    rec = json.loads(path.read_text())
    m = meta.get(rec["source"].get("filename"))
    if not m:
        print("no MJP metadata for", path.parent.name)
        continue
    rec["date_precision"] = "month"
    rec["date_from"] = "MJP MODS dateIssued"
    rec["volume"], rec["number"] = num(m["volume"]), num(m["number"])
    rec["source"].update({"url": m["mjp_url"], "bdr_id": m["bdr"], "pdf_url": m["pdf_url"],
                          "rights": m["rights"] or None,
                          "provider": "Modernist Journals Project / Brown Digital Repository"})
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    os.replace(tmp, path)
    n += 1
print(f"updated {n} issues")
