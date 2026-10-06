"""Download The Crisis (1910-1922) PDFs from the Modernist Journals Project.

Issue list from modjourn.org; metadata and PDFs from the Brown Digital Repository.
Writes PDFs to the external drive (PDF_DIR) and the manifest to pdfs/manifest.csv. Safe to re-run.
"""
import csv, json, re, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pdfs"
PDF_DIR = Path("/Volumes/Lightning/crisis-pdfs")
PDF_DIR.mkdir(exist_ok=True)
# MJP metadata errors and supplements, checked against volume/number and the printed text.
# bdr id -> (corrected YYYY-MM, filename suffix, note)
OVERRIDES = {
    "bdr:522172": ("1911-06", "", "MJP dates Vol. 2, No. 2 as 1912-06; it is June 1911"),
    "bdr:509928": ("1916-05", "", "MJP dates Vol. 12, No. 1 as 1916-06; it is May 1916"),
    "bdr:510193": ("1916-07", "_supplement", "Supplement, July 1916: 'The Waco Horror'"),
    "bdr:510907": ("1917-07", "_supplement", "Supplement, July 1917 (Memphis); MJP dates it 1917-05"),
}
UA = {"User-Agent": "paperpress-crisis-archive (neal.caren@unc.edu)"}


def get(url, binary=False):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                data = r.read()
                return data if binary else data.decode()
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


page = get("https://modjourn.org/journal/crisis/")
ids = sorted(set(re.findall(r"modjourn\.org/issue/(bdr\d+)/", page)))
print(f"{len(ids)} issues listed", flush=True)

rows = []
for i, bdr in enumerate(ids, 1):
    pid = bdr.replace("bdr", "bdr:")
    d = json.loads(get(f"https://repository.library.brown.edu/api/items/{pid}/"))
    date = d["mods_dateIssued_ssim"][0]          # e.g. 1910-11
    mjp_date = date
    date, suffix, note = OVERRIDES.get(pid, (date, "", ""))
    pdf_url = d["links"]["views"].get("PDF View")
    row = {"bdr": pid, "date": date, "mjp_date": mjp_date, "note": note,
           "volume": d.get("mods_title_part_volume_ssi"),
           "number": d.get("mods_title_part_number_ssi"),
           "partnumber": (d.get("partnumber") or [""])[0] if isinstance(d.get("partnumber"), list) else d.get("partnumber"),
           "mjp_url": f"https://modjourn.org/issue/{bdr}/",
           "pdf_url": pdf_url,
           "rights": (d.get("mods_access_condition_rights_text_tsim") or [""])[0]}
    name = f"crisis_{date}-01{suffix}.pdf" if re.fullmatch(r"\d{4}-\d{2}", date) else f"crisis_{bdr}.pdf"
    row["filename"] = name
    dest = PDF_DIR / name
    if pdf_url and not dest.exists():
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(get(pdf_url, binary=True))
        tmp.rename(dest)
    print(f"[{i}/{len(ids)}] {date} {row['partnumber']} -> {name}", flush=True)
    rows.append(row)

with open(OUT / "manifest.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(sorted(rows, key=lambda r: r["date"]))
print("done", flush=True)
