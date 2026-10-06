#!/bin/zsh
# Box cleanup -> 3 enrich runs on cleaned boxes -> majority-vote toc, for OCR'd issues.
# Usage: scripts/run_chain.sh ISSUE [ISSUE...]      (e.g. 1911-01-01)
# Safe to re-run: pages already cleaned and issues already enriched are skipped.
set -e
ROOT=${0:A:h:h}
PY=~/.local/share/uv/tools/paperpress/bin/python
BOX=$ROOT/boxwork
cd $ROOT

for iss in "$@"; do
  dir=titles/crisis/$iss
  [[ -f $dir/full_text.json ]] || { echo "$iss: not OCR'd yet, skipping"; continue; }
  todo=()
  for f in $dir/page_??.json; do
    n=${${f:t:r}#page_}
    [[ -f $dir/page_$n.clean.json ]] || todo+=($((10#$n)))
  done
  if (( ${#todo} )); then
    echo "$iss: cleaning ${#todo} pages"
    $PY scripts/clean_boxes.py $iss $todo > $BOX/clean_$iss.log 2>&1
  fi
  for i in 1 2 3; do
    V=$BOX/vote$i
    mkdir -p $V/titles/crisis/$iss
    cp paper.toml $V/; cp titles/crisis/profile.json $V/titles/crisis/
    cp $dir/issue.json $dir/full_text.json $V/titles/crisis/$iss/
    [[ -e $V/titles/crisis/$iss/images ]] || ln -s $ROOT/$dir/images $V/titles/crisis/$iss/images
    for f in $dir/page_*.clean.json; do cp $f $V/titles/crisis/$iss/${${f:t}%.clean.json}.json; done
  done
done

echo "enrich x3"
for i in 1 2 3; do (cd $BOX/vote$i && paperpress enrich crisis >> enrich.log 2>&1) & done
wait
tail -qn1 $BOX/vote*/enrich.log

for iss in "$@"; do
  [[ -f $BOX/vote1/titles/crisis/$iss/toc.json ]] || continue
  python3 scripts/toc_vote.py $iss $BOX/vote1 $BOX/vote2 $BOX/vote3 \
    --toc-out $BOX/consensus/$iss/toc.json | tail -1
done
