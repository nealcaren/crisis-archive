"""Majority-vote consensus across several toc.json runs of one issue (paperpress enrich).

1. Within a page, two regions belong together if a majority of runs put them in the
   same article.
2. Across pages, two of those page groups are one article (a continuation) if a majority
   of runs give their regions the same article.
3. Each consensus article takes its title, author, type, section, etc. from the run
   article that overlaps it most (ties: the title most runs agree on).

Prints pairwise page agreement and the pages where runs disagree (a review queue).
With --toc-out, writes a toc.json in paperpress's format.

Usage: toc_vote.py ISSUE RUN_DIR [RUN_DIR...] [--toc-out FILE] [--title crisis]
"""
import argparse, itertools, json
from collections import Counter
from pathlib import Path


def rid_key(rid):            # "r12", and split regions "r12b", "r12bb" right after it
    num = rid[1:].rstrip("b")
    return int(num), len(rid) - 1 - len(num)


def load(run, title, issue):
    return json.loads((Path(run) / "titles" / title / issue / "toc.json").read_text())


def by_page(toc):
    g = {}
    for a in toc["articles"]:
        for r in a["regions"]:
            g.setdefault(r["page"], []).append(frozenset(r["ids"]))
    return g


def multi(sets):             # agreement ignores one-region groups (page numbers, heads)
    return frozenset(s for s in sets if len(s) > 1)


class UF:
    def __init__(self, items):
        self.p = {i: i for i in items}

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def consensus(tocs):
    need = len(tocs) // 2 + 1
    # region -> article index, per run
    owner = []
    for t in tocs:
        m = {}
        for ai, a in enumerate(t["articles"]):
            for r in a["regions"]:
                for rid in r["ids"]:
                    m[(r["page"], rid)] = ai
        owner.append(m)
    regions = sorted(set().union(*owner), key=lambda x: (x[0], rid_key(x[1])))

    # 1. within-page groups
    uf = UF(regions)
    pages = sorted({p for p, _ in regions})
    for p in pages:
        rs = [x for x in regions if x[0] == p]
        for u, v in itertools.combinations(rs, 2):
            votes = sum(1 for m in owner if u in m and v in m and m[u] == m[v])
            if votes >= need:
                uf.union(u, v)
    pgroups = {}
    for x in regions:
        pgroups.setdefault(uf.find(x), []).append(x)
    groups = list(pgroups.values())

    # 2. join page groups on different pages that most runs treat as one article
    def run_article(m, g):
        c = Counter(m[x] for x in g if x in m)
        return c.most_common(1)[0][0] if c else None
    guf = UF(range(len(groups)))
    for i, j in itertools.combinations(range(len(groups)), 2):
        if groups[i][0][0] == groups[j][0][0]:
            continue
        votes = 0
        for m in owner:
            ai, aj = run_article(m, groups[i]), run_article(m, groups[j])
            votes += ai is not None and ai == aj
        if votes >= need:
            guf.union(i, j)
    arts = {}
    for i, g in enumerate(groups):
        arts.setdefault(guf.find(i), []).extend(g)

    # 3. metadata from the best-overlapping run article
    out = []
    for members in arts.values():
        mset = set(members)
        cands = []
        for t, m in zip(tocs, owner):
            c = Counter(m[x] for x in members if x in m)
            for ai, n in c.items():
                a = t["articles"][ai]
                size = sum(len(r["ids"]) for r in a["regions"])
                cands.append((n / (len(mset) + size - n), a))     # Jaccard
        titles = Counter(a["title"] for _, a in cands)
        best = max(cands, key=lambda c: (round(c[0], 3), titles[c[1]["title"]]))[1]
        byp = {}
        for p, rid in sorted(members, key=lambda x: (x[0], rid_key(x[1]))):
            byp.setdefault(p, []).append(rid)
        pg = sorted(byp)
        art = {k: v for k, v in best.items() if k not in ("id", "regions", "pages", "start_page",
                                                          "continued", "continued_from", "continued_to")}
        art.update({"start_page": pg[0], "pages": pg, "continued": len(pg) > 1,
                    "continued_from": None, "continued_to": None,
                    "regions": [{"page": p, "ids": byp[p]} for p in pg],
                    # share of runs that produced exactly this article
                    "vote_agreement": round(sum(
                        any({(r["page"], i) for r in x["regions"] for i in r["ids"]} == mset
                            for x in t["articles"]) for t in tocs) / len(tocs), 2)})
        out.append(art)
    out.sort(key=lambda a: (a["start_page"], rid_key(a["regions"][0]["ids"][0])))
    seen = Counter()
    for a in out:
        seen[a["start_page"]] += 1
        a["id"] = f"p{a['start_page']}v{seen[a['start_page']]}"
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("issue"); ap.add_argument("runs", nargs="+")
    ap.add_argument("--toc-out"); ap.add_argument("--title", default="crisis")
    a = ap.parse_args()
    tocs = [load(r, a.title, a.issue) for r in a.runs]
    G = [by_page(t) for t in tocs]
    pages = sorted(set().union(*G))
    for (i, x), (j, y) in itertools.combinations(enumerate(G), 2):
        same = sum(multi(x.get(p, [])) == multi(y.get(p, [])) for p in pages)
        print(f"{a.issue} run{i+1} vs run{j+1}: same grouping on {same}/{len(pages)} pages")
    disputed = [p for p in pages if len({multi(g.get(p, [])) for g in G}) > 1]
    print(f"{a.issue}: runs disagree on pages {disputed}")
    if a.toc_out:
        arts = consensus(tocs)
        toc = {"title": tocs[0]["title"], "date": tocs[0]["date"],
               "enrich": {**tocs[0]["enrich"], "vote": {"runs": a.runs, "disputed_pages": disputed}},
               "articles": arts}
        Path(a.toc_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.toc_out).write_text(json.dumps(toc, indent=1, ensure_ascii=False))
        print(f"wrote {a.toc_out}: {len(arts)} articles "
              f"({sum(x['is_advertisement'] for x in arts)} ads, {sum(x['continued'] for x in arts)} continued)")
