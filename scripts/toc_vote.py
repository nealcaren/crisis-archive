"""Agreement and majority-vote consensus across several toc.json runs of one issue.

Two regions on a page belong together in the consensus if a majority of runs put
them in the same article. Prints pairwise page agreement; with --out, writes the
consensus groups and the pages where runs disagree (for review).
Usage: toc_vote.py ISSUE RUN_DIR [RUN_DIR...] [--out FILE]
"""
import argparse, itertools, json
from collections import Counter
from pathlib import Path


def groups(path):
    g = {}
    for a in json.loads(Path(path).read_text())["articles"]:
        for r in a["regions"]:
            g.setdefault(r["page"], []).append((frozenset(r["ids"]), a))
    return g


def partition(gp):           # ignore singletons (page numbers, running heads, one-box items)
    return {ids for ids, _ in gp if len(ids) > 1}


ap = argparse.ArgumentParser()
ap.add_argument("issue"); ap.add_argument("runs", nargs="+"); ap.add_argument("--out")
a = ap.parse_args()
G = [groups(Path(r) / "titles/crisis" / a.issue / "toc.json") for r in a.runs]
pages = sorted(set().union(*G))
for (i, x), (j, y) in itertools.combinations(enumerate(G), 2):
    same = sum(partition(x.get(p, [])) == partition(y.get(p, [])) for p in pages)
    print(f"{a.issue} run{i+1} vs run{j+1}: same grouping on {same}/{len(pages)} pages")

need = len(G) // 2 + 1
consensus, disputed = {}, []
for p in pages:
    pair = Counter()
    ids = set()
    for g in G:
        for members, _ in g.get(p, []):
            ids |= members
            for u, v in itertools.combinations(sorted(members), 2):
                pair[(u, v)] += 1
    parent = {i: i for i in ids}
    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i
    for (u, v), n in pair.items():
        if n >= need:
            parent[find(u)] = find(v)
    comp = {}
    for i in ids:
        comp.setdefault(find(i), set()).add(i)
    consensus[p] = sorted(sorted(c, key=lambda s: int(s[1:])) for c in comp.values())
    if len({frozenset(partition(g.get(p, []))) for g in G}) > 1:
        disputed.append(p)
print(f"{a.issue}: runs disagree on pages {disputed}")
if a.out:
    Path(a.out).write_text(json.dumps({"issue": a.issue, "runs": a.runs, "consensus": consensus,
                                       "disputed_pages": disputed}, indent=1))
