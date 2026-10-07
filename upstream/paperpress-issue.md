# More reliable article tables of contents: layout notes in profiles, voting across enrich runs, and article clip export

**Labels:** enhancement

Tested in [nealcaren/crisis-archive](https://github.com/nealcaren/crisis-archive) on nine issues of *The Crisis* (Nov. 1910–July 1911; 332 pages), with regions
cleaned first by a newspaper-ocr post-pass (see nealcaren/newspaper-ocr#34).

## 1. `enrich` varies a lot between runs

Two `enrich` runs on identical input (same pages, same models, temperature 0) produced
the same multi-region grouping on only 15/20 and 19/36 pages. The differences are real
article boundaries, not cosmetic: a whole Opinion page as one article in one run and nine
quotations in the other; Education and The Church merged; a four-page essay split.
The share of articles all runs agree on moved by up to 18 points per issue between rounds, so one run can't be used to
judge a change in prompt or profile.

**Proposal: `paperpress enrich --runs N`.** Run the per-page pass N times (cache each run
separately) and combine:

- Per page, take the grouping of the **medoid run**: the run whose pairwise
  same-article/different-article votes agree most with the others. (Joining pairs that
  a majority agree on can produce groupings no run made, which shows up as duplicate
  articles.)
- Join page groups across pages when a majority of runs put them in one article.
- Each article takes metadata (title, author, type, section) from the best-overlapping
  run article and gets `vote_agreement`, the share of runs that produced exactly it.
  Low agreement plus the pages where runs disagree make a natural review queue.

Prototype: [`toc_vote.py`](https://github.com/nealcaren/crisis-archive/blob/main/scripts/toc_vote.py); results in `titles/crisis/*/toc.voted.json`. Cost with the default models is about 2–4 cents per
issue per run, so 3 runs is about $10 for 148 issues.

## 2. Layout notes in the profile

`profile.json` already passes `notes` to the prompt. Most grouping errors were about the
magazine's layout, and a few sentences fixed them ([profile](https://github.com/nealcaren/crisis-archive/blob/main/titles/crisis/profile.json)):

- Opinion = a run of quotations, each its own article with its source.
- Along the Color Line = short items under small-caps subheads; never merge across subheads.
- Each Editorial heading starts a new piece, continuing across page breaks.
- Letters: a heading owns everything to the next heading, including a quoted motion.
- Long signed features own their internal parts, chapters and reproduced headlines.
- Men of the Month: one article per person; Little Letters: one per signed letter.

With these notes, Villard's "The Manufacture of Prejudice" went from two fragments plus
three stray "news items" to one article over pp. 35–37 (871 → 1,826 words). The letters
on a Letters page each became separate, and Opinion quotations came out per source.

**Proposal:**
- have `paperpress profile` draft a "layout" section (how each recurring section is
  divided into items), not just names, contributors and ads;
- document `notes` in the README as the place to fix systematic grouping errors.

Also, the draft listed "Along the Color Line" and "Opinion" as *columns*. A section vs.
column distinction in the merge prompt would help.

## 3. Use cleaned regions, and export article clips

- `enrich` reads `page_NN.json`. Let it prefer a cleaned file (`page_NN.clean.json`, or
  an `[ocr] cleanup = true` step) so regions don't span two articles. On the cleaned
  regions, the first Letters item, which both runs on the raw regions put into the
  preceding article ("Talks About Women"), was grouped on its own.
- **`paperpress clip`** (or an `export --clips` option): per article, its text in reading
  order without running heads, and a PNG of only its regions across pages, with other
  articles' glyphs whited out (uses the cleanup's `exclude` lists). Prototype:
  [`clip_article.py`](https://github.com/nealcaren/crisis-archive/blob/main/scripts/clip_article.py). Examples: [Boas, "The Real Race Problem",
  pp. 22–25](https://raw.githubusercontent.com/nealcaren/crisis-archive/main/docs/images/clip_boas_real-race-problem.jpg); [Schomburg, "The Fight for Liberty in St. Lucia",
  pp. 33–34](https://raw.githubusercontent.com/nealcaren/crisis-archive/main/docs/images/clip_schomburg_st-lucia.jpg).

## Small things noticed

- `enrich` treats page numbers and running heads as articles ("[Page number]", "THE
  CRISIS"). The profile note helps, but a filter before grouping would be cheaper.
- `paperpress add pdf` needs a day in file names; monthly magazines get `YYYY-MM-01` and
  `issue.json` has to be edited to set `date_precision: "month"`. An option for
  month-precision file dates would help.
