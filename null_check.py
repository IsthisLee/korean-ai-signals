#!/usr/bin/env python3
"""사후 진단: 사람/AI 라벨을 무작위로 섞었을 때도 같은 수의 적중이 나오는지 본다.

    python3 null_check.py --out out/pilot --n 1000

analyze.py 와 같은 규칙(방향, 사람 글 최댓값·최솟값 문턱, 장르별 반분)으로 세고,
관찰값이 섞은 라벨 분포의 어디쯤인지(관찰값 이상이 나온 비율)를 적는다. 사전 등록 판정이 아니다.
"""
import argparse
import json
import pathlib
import random
import statistics

from analyze import SEED, load, sign, split_half
from signals import FEATURES


def counts(docs):
    humans = [d for d in docs if d["group"] == "human"]
    ais = [d for d in docs if d["group"] == "ai"]
    sel, val = split_half(humans)
    any_hit, total_full, total_split, val_over, clean_features = set(), 0, 0, 0, 0
    for key, _, _, research in FEATURES:
        H = [d["features"][key] for d in humans if d["features"].get(key) is not None]
        A = [d["features"][key] for d in ais if d["features"].get(key) is not None]
        S = [d["features"][key] for d in sel if d["features"].get(key) is not None]
        if len(H) < 3 or len(A) < 3 or not S:
            continue
        direction = research if research in ("up", "down") else sign(statistics.median(A), statistics.median(H))

        def over(group, lo, hi):
            return [d["id"] for d in group if d["features"].get(key) is not None and
                    ((direction == "up" and d["features"][key] > hi) or (direction == "down" and d["features"][key] < lo))]

        full = over(ais, min(H), max(H))
        split = over(ais, min(S), max(S))
        vo = over(val, min(S), max(S))
        any_hit.update(full)
        total_full += len(full)
        total_split += len(split)
        val_over += len(vo)
        clean_features += 1 if (not vo and split) else 0
    return {"ai_docs_hit_by_any_full": len(any_hit), "total_full_hits": total_full, "total_split_hits": total_split,
            "val_human_over": val_over, "split_clean_features": clean_features}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=1000)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    docs = load(out)
    observed = counts(docs)
    rng = random.Random(f"{SEED}:null")
    n_h = sum(d["group"] == "human" for d in docs)
    sims = []
    for _ in range(a.n):
        order = docs[:]
        rng.shuffle(order)
        relabeled = []
        for i, d in enumerate(order):
            relabeled.append({**d, "group": "human" if i < n_h else "ai"})
        sims.append(counts(relabeled))
    summary = {}
    for k, v in observed.items():
        vals = [s[k] for s in sims]
        summary[k] = {"observed": v, "null_median": statistics.median(vals),
                      "null_p95": sorted(vals)[int(0.95 * len(vals)) - 1],
                      "share_null_ge_observed": sum(x >= v for x in vals) / len(vals)}
    (out / "null_check.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
