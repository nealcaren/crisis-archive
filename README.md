# The Crisis Archive

*The Crisis: A Record of the Darker Races* (NAACP, ed. W. E. B. Du Bois), 148 issues,
November 1910 to December 1922, built with [paperpress](https://github.com/nealcaren/paperpress).

**Source.** Scans are from the [Modernist Journals Project](https://modjourn.org/journal/crisis/)
via the Brown Digital Repository (rights: No Copyright - United States). Each issue's
`issue.json` links back to its MJP page and Brown PDF.

**OCR.** DocLayout-YOLO + GLM-OCR (newspaper-ocr 0.10.0), using a local MLX server:

    mlx_vlm.server --host 127.0.0.1 --port 8080 --model mlx-community/GLM-OCR-bf16
    paperpress ocr crisis

**Rebuilding from scratch.**

    python3 scripts/fetch_mjp.py            # PDFs -> /Volumes/Lightning/crisis-pdfs, manifest -> pdfs/
    paperpress add pdf crisis /Volumes/Lightning/crisis-pdfs
    python3 scripts/apply_mjp_metadata.py   # month precision, volume/number, source links

The Crisis is monthly, so PDFs are named `YYYY-MM-01` and then marked month precision.

**Corrections to MJP metadata** (in `scripts/fetch_mjp.py`, `OVERRIDES`):

| Brown id | MJP date | Used | Why |
|---|---|---|---|
| bdr:522172 | 1912-06 | 1911-06 | Vol. 2, No. 2 is June 1911 |
| bdr:509928 | 1916-06 | 1916-05 | Vol. 12, No. 1 is May 1916 |
| bdr:510193 | 1916-07 | 1916-07 supplement | "The Waco Horror" supplement (8 pp.) |
| bdr:510907 | 1917-05 | 1917-07 supplement | Memphis supplement, printed "July, 1917, Vol. 14, No. 3" (4 pp.) |

Not in git: PDFs (on the external drive), page images (`titles/*/*/images/`), caches, `site/`.
