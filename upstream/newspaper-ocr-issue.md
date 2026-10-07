# Region cleanup pass: one owner per glyph, so boxes don't overlap and every article can be clipped

**Labels:** enhancement

## Problem

After recognition, page regions often overlap, cut letters off at column edges, or span
two articles. That's fine for reading text in order, but it breaks anything that needs
the boxes themselves: clipping an article as an image, drawing it in a viewer, or
grouping regions into articles. The regions are the units downstream tools (paperpress
`enrich`) assign to articles, so a box that holds the end of one article and the start
of the next can't be grouped correctly by anything downstream.

On 332 pages of *The Crisis* (Nov. 1910–July 1911, Modernist Journals Project scans,
DocLayout-YOLO + GLM-OCR, newspaper-ocr 0.10.0):

- 617 region pairs overlap by more than 30% of the smaller box (3,652 regions).
- 255 regions are hallucinated reads, mostly Arabic-script text or lone CJK glyphs
  from ornaments and rules (cf. #30), 88 of them on article pages.
- Residual-pass regions (`label="text"`) are drawn around uncovered ink but their
  rectangles stretch over detector boxes. One on a Letters page covers the section banner
  and both columns.
- Detector boxes clip the first or last letter of lines, and some reach into the
  next column, so their text duplicates the neighbor's (cf. #13).
- 336 boxes contain a heading partway through, i.e. span two articles: for example
  the end of one editorial and the start of the next ("…degrade American citizens." /
  THE GHETTO.), or the end of one letter and the heading of the next.

## Prototype

A post-recognition pass, non-destructive like `RegionRepair`: it returns new regions and
leaves the input untouched. Script: [`clean_boxes.py`](https://github.com/nealcaren/crisis-archive/blob/main/scripts/clean_boxes.py), in [nealcaren/crisis-archive](https://github.com/nealcaren/crisis-archive).

1. **Junk.** Drop empty reads and reads that are mostly non-Latin script (configurable
   by expected script/language).
2. **Glyph ownership.** Connected components of ink (glyph level, not words: a word
   dilation bridges narrow gutters) are each given to exactly one region: the region
   holding the largest share of the glyph. Ties:
   - nested boxes: the inner one wins;
   - partial overlaps: split the candidates' union at white vertical gutters over the
     overlap rows, and give the glyph's column band to the region whose own uniquely held
     glyphs (in those rows) sit in that band;
   - then detector regions beat residual (`text`) regions, then the smaller region.
   Glyphs outside every box but touching one join it (recovers clipped letters).
3. **Reshape.** Each region's box becomes the bounding box of its glyphs (plus a small
   margin). Glyphs of other regions inside that box are listed in `exclude`
   (`[x0, y0, x1, y1, owner_id]`), so a clip can white them out. A region left with no
   glyphs is dropped.
4. **Re-read** regions that lost or gained >3% of their ink, on a crop with other
   regions' glyphs whited out.
5. **Guard.** If a re-read loses dictionary words found nowhere else on the page, keep
   the old text and set `needs_review`. (Garbled cross-column reads like "courtment",
   or fragments of words still present, don't count.)
6. **Split at headings.** A region whose text has an all-caps heading line partway
   through is cut at the white gap nearest the heading's relative position (trying the
   3 nearest). Both halves are re-read; the split is kept only if the heading now
   starts the lower half and no words are lost, otherwise `needs_review`.

Results on the same 332 pages: 3,652 → 3,610 regions; overlaps between region boxes
are gone except where one box's rectangle surrounds another's glyphs (handled by
`exclude`); median unowned ink 0.11% (90th percentile 3.8%, mostly covers and
ornaments); 336 heading splits; words lost from a page's text on 5 pages. On article
pages (pp. 5–30), 23 regions are flagged for review. The rest of the 230 flags are on
covers and ad pages, where ad slogans look like headings.

Before (left) and after (right). Shaded glyphs belong to another region:

![Talks About Women / Letters page, before and after](https://raw.githubusercontent.com/nealcaren/crisis-archive/main/docs/images/compare_1910-12-01_p28.jpg)

Article clips built from the cleaned regions: [Boas, "The Real Race Problem"](https://raw.githubusercontent.com/nealcaren/crisis-archive/main/docs/images/clip_boas_real-race-problem.jpg),
[Villard, "The Manufacture of Prejudice"](https://raw.githubusercontent.com/nealcaren/crisis-archive/main/docs/images/clip_villard_manufacture-of-prejudice.jpg),
[Storey, "Athens and Brownsville"](https://raw.githubusercontent.com/nealcaren/crisis-archive/main/docs/images/clip_athens-and-brownsville.jpg).

## GLM-OCR behavior found along the way

On a crop that begins with a short heading or an indented first line, GLM-OCR often
returns the text **without that line** ("THE GHETTO.", "FROM DUTCH WORKINGMEN.",
"A press dispatch from Panama says:"). The split step works around it by restoring the
heading when the lower half's text starts exactly where the original read continued
after it. This may deserve its own issue (padding the crop top?).

## Proposal

- `newspaper_ocr.RegionCleanup` (or `Pipeline(region_cleanup=True)`), returning a new
  `PageLayout`; JSON gains `exclude`, `bbox_ocr`, `needs_review`, `split_from`, and a
  page-level summary (unowned ink %, lost words, review list).
- Options: expected script(s) for the junk filter; heading pattern (the all-caps rule
  is English/period-specific); whether to re-read (needs a region recognizer).

Open questions:
- Should the junk filter live here or in the recognizer wrapper (#30)?
- Heading detection is text-based. A layout-based signal (centered short line,
  small caps, rule above) would generalize better.
- Cost: re-reads are about 1.5 per page here; on a Mac with the MLX server that's
  roughly 8 minutes per 36-page issue.
