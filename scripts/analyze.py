#!/usr/bin/env python3
"""사람 글과 AI 글의 지표를 비교해 보고서를 쓴다. 기준은 분석 계획 5.3 을 따른다.

    python3 analyze.py --out out/main

- 문서마다 값이 하나인 지표: Mann-Whitney U 양측 검정, Benjamini-Yekutieli 보정(q = 0.05).
- 방향: 연구가 보고한 방향(up/down)을 쓰고, 연구끼리 엇갈리거나 방향이 없으면(both) 표본에서 본 방향을 쓰고 표시한다.
- 적중: 방향이 up 이면 사람 글 최댓값보다 큰 AI 글, down 이면 최솟값보다 작은 AI 글.
- 반분: 사람 글을 장르마다 시드로 섞어 반으로 나누고, 선별용 반의 최댓값·최솟값을 문턱으로 삼아
  검증용 반에서 문턱을 넘는 사람 글 수와 AI 글 적중 수를 함께 센다.
"""
import argparse
import json
import math
import pathlib
import random
import statistics

from scipy.stats import false_discovery_control, mannwhitneyu

from common import read_manifest, write_json
from signals import FEATURES

SEED = "20260916"
Q = 0.05


def load(out):
    """excluded.tsv(id, reason)에 적힌 문서는 뺀다. 예: 글 대신 자료를 요청한 AI 응답."""
    excluded = {row["id"] for row in read_manifest(out / "excluded.tsv")}
    feats = {}
    for p in sorted((out / "features").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if d["id"] not in excluded:
            feats[d["id"]] = d
    docs = []
    for h in read_manifest(out / "human.tsv"):
        if h["id"] in feats:
            docs.append({"id": h["id"], "group": "human", "genre": h["genre"], "model": "", **feats[h["id"]]})
    for a in read_manifest(out / "ai.tsv"):
        if a["id"] in feats:
            docs.append({"id": a["id"], "group": "ai", "genre": a["genre"], "model": a["model"], "pair": a["pair"], **feats[a["id"]]})
    return docs


def split_half(humans):
    sel, val = [], []
    for genre in sorted({d["genre"] for d in humans}):
        g = sorted((d for d in humans if d["genre"] == genre), key=lambda d: d["id"])
        random.Random(f"{SEED}:{genre}").shuffle(g)
        sel += g[: len(g) // 2]
        val += g[len(g) // 2:]
    return sel, val


def vals(docs, key):
    return [d["features"][key] for d in docs if d["features"].get(key) is not None]


def over(docs, key, direction, lo, hi):
    out = []
    for d in docs:
        v = d["features"].get(key)
        if v is not None and ((direction == "up" and v > hi) or (direction == "down" and v < lo)):
            out.append(d["id"])
    return out


def sign(a, b):
    return "up" if a > b else "down" if a < b else "none"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    docs = load(out)
    humans = [d for d in docs if d["group"] == "human"]
    ais = [d for d in docs if d["group"] == "ai"]
    models = sorted({d["model"] for d in ais})
    genres = sorted({d["genre"] for d in docs})
    sel, val = split_half(humans)

    rows = []
    for key, no, name, research in FEATURES:
        H, A = vals(humans, key), vals(ais, key)
        row = {"key": key, "no": no, "name": name, "research": research, "n_h": len(H), "n_ai": len(A)}
        if len(H) < 3 or len(A) < 3:
            rows.append(row)
            continue
        test = mannwhitneyu(A, H, alternative="two-sided")
        observed = sign(statistics.median(A), statistics.median(H))
        direction = research if research in ("up", "down") else observed
        Hs = vals(sel, key)
        row.update({
            "median_h": statistics.median(H), "median_ai": statistics.median(A),
            "p_ai_gt_h": test.statistic / (len(A) * len(H)), "p": test.pvalue,
            "observed": observed, "direction": direction, "direction_from_sample": research == "both",
            "agrees_with_research": research == "both" or observed == research,
            "hits_full": over(ais, key, direction, min(H), max(H)),
            "val_human_over": over(val, key, direction, min(Hs), max(Hs)) if Hs else None,
            "hits_split": over(ais, key, direction, min(Hs), max(Hs)) if Hs else None,
            "model_dirs": {m: sign(statistics.median(vals([d for d in ais if d["model"] == m], key) or [math.nan]), statistics.median(H)) for m in models},
            "genre_dirs": {g: sign(statistics.median(vals([d for d in ais if d["genre"] == g], key) or [math.nan]),
                                   statistics.median(vals([d for d in humans if d["genre"] == g], key) or [math.nan])) for g in genres},
        })
        row["reversed_somewhere"] = any(v not in (direction, "none") for v in list(row["model_dirs"].values()) + list(row["genre_dirs"].values()))
        rows.append(row)

    tested = [r for r in rows if "p" in r]
    for r, q in zip(tested, false_discovery_control([r["p"] for r in tested], method="by")):
        r["q_by"] = float(q)

    hit_sets = {r["key"]: set(r["hits_full"]) for r in tested}
    for r in tested:
        others = set().union(*(s for k, s in hit_sets.items() if k != r["key"]))
        r["unique_hits_full"] = sorted(set(r["hits_full"]) - others)

    ai_meta = read_manifest(out / "ai.tsv")
    summary = {
        "n_human": len(humans), "n_ai": len(ais),
        "by_genre": {g: {"human": sum(d["genre"] == g for d in humans), "ai": sum(d["genre"] == g for d in ais)} for g in genres},
        "by_model": {m: sum(d["model"] == m for d in ais) for m in models},
        "cost_usd": round(sum(float(r["cost_usd"]) for r in ai_meta), 4),
        "length_ratio_out_of_range": [r["id"] for r in ai_meta if not 0.8 <= float(r["ratio"]) <= 1.2],
        "tested_features": len(tested),
        "significant_by": [r["key"] for r in tested if r["q_by"] < Q],
        "features_with_full_hits": [r["key"] for r in tested if r["hits_full"]],
        "features_split_clean": [r["key"] for r in tested if r["val_human_over"] == [] and r["hits_split"]],
        "ai_docs_hit_by_any_full": len(set().union(*hit_sets.values())),
    }
    write_json(out / "results.json", {"summary": summary, "features": rows})

    lines = ["# 분석 결과", "", "```json", json.dumps(summary, ensure_ascii=False, indent=2), "```", "",
             "| 번호 | 지표 | 연구 방향 | 사람 중앙값 | AI 중앙값 | P(AI>사람) | p | q(BY) | 전체 적중 | 단독 적중 | 반분 검증 사람 초과 | 반분 AI 적중 | 방향 뒤집힘 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        if "p" not in r:
            lines.append(f"| {r['no']} | {r['name']} | {r['research']} | 표본 부족 | | | | | | | | | |")
            continue
        mark = "*" if r["direction_from_sample"] else ""
        lines.append(f"| {r['no']} | {r['name']} | {r['research']}{mark} | {r['median_h']:.4g} | {r['median_ai']:.4g} | {r['p_ai_gt_h']:.2f} | {r['p']:.3g} | {r['q_by']:.3g} | "
                     f"{len(r['hits_full'])} | {len(r['unique_hits_full'])} | {len(r['val_human_over'])}/{len(val)} | {len(r['hits_split'])} | {'예' if r['reversed_somewhere'] else ''} |")
    lines += ["", "`*` 는 연구 방향이 엇갈리거나 없어 표본에서 본 방향으로 적중을 셌다는 뜻입니다.", ""]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:60]))


if __name__ == "__main__":
    main()
