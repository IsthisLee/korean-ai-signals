#!/usr/bin/env python3
"""여러 지표를 합친 문서 점수(분석 계획 5.3 의 2단계). 한 실행으로 만들고 다른 실행으로 확인한다.

    python3 score.py --train out/train-matched --test out/main-matched --out out/main-score

1. 지표를 성격이 같은 묶음(GROUPS)으로 나눈다.
2. 훈련 실행에서 지표마다 사람 글과 AI 글의 평균과 표준편차를 구한다. 표준편차는 두 묶음을 합친
   표준편차의 1/4 보다 작아지지 않게 한다(값이 거의 0 인 지표에서 우도비가 튀지 않게).
3. 묶음마다 훈련 실행에서 효과 크기(|Cohen's d|)가 가장 큰 지표 하나를 대표로 고른다. 서로 얽힌 지표를
   함께 더하지 않으려는 것이다.
4. 문서 점수는 묶음 대표 지표의 로그 우도비(정규분포 가정) 합이다. 지표 하나의 로그 우도비는 ±3 으로
   자른다. 한 지표가 판정을 좌우하지 않게 하려는 것이다. 값이 없는 지표는 0 으로 둔다.
5. 문턱은 훈련 실행 사람 글 점수의 최댓값이다(Neyman-Pearson). 시험 실행에서 문턱을 넘는 사람 글과
   AI 글을 센다.
6. 시험 실행의 AUROC 와, 시험 실행의 사람/AI 표시를 1,000번 섞었을 때 AUROC 가 관찰값 이상인 비율을 낸다.
"""
import argparse
import json
import math
import pathlib
import random
import statistics

from analyze import load

GROUPS = {
    "쉼표": ["comma_inclusion", "comma_rate", "comma_position", "comma_segment", "comma_pos_pair_div"],
    "문장부호와 기호": ["punct_per_1k", "num_symbol_per_1k"],
    "띄어쓰기": ["spacing_adherence"],
    "어휘와 품사 다양도": ["mattr", "pos_ngram_div"],
    "어휘 밀도": ["lexical_density", "noun_ratio"],
    "수식": ["adj_ratio", "adnominal_per_1k"],
    "명사화": ["nominalization_per_1k"],
    "보조 용언": ["aux_per_1k"],
    "대명사와 지시어": ["pronoun_per_1k", "demonstrative_per_1k"],
    "조사": ["jkg_per_1k", "topic_share"],
    "의존명사": ["geot_ttaemun_per_1k"],
    "문장 길이": ["sent_len", "sent_len_cv"],
    "절과 의존 구조": ["clauses_per_sent", "dep_distance"],
    "접속": ["coord_per_1k", "example_emphasis_share", "contrast_share"],
    "사동·부정·피동": ["long_causative_per_1k", "short_neg_share", "passive_per_1k"],
    "양태와 인식": ["modal_per_1k", "epistemic_per_1k"],
    "담화·완화·정도": ["discourse_per_1k", "downtoner_per_1k", "degree_adv_per_1k"],
    "번역투 동사": ["translationese_verbs_per_1k", "tonghada_per_1k"],
    "높임": ["honorific_ep_per_1k"],
    "인용": ["quote_per_1k"],
}
CLIP = 3.0
SD_FLOOR = 0.25
SEED = "20260916:score"


def vals(docs, key):
    return [d["features"][key] for d in docs if d["features"].get(key) is not None]


def fit(train):
    humans = [d for d in train if d["group"] == "human"]
    ais = [d for d in train if d["group"] == "ai"]
    model = {}
    for group, keys in GROUPS.items():
        best = None
        for key in keys:
            H, A = vals(humans, key), vals(ais, key)
            if len(H) < 3 or len(A) < 3:
                continue
            pooled = statistics.pstdev(H + A)
            if pooled == 0:
                continue
            floor = SD_FLOOR * pooled
            sh, sa = max(statistics.pstdev(H), floor), max(statistics.pstdev(A), floor)
            mh, ma = statistics.fmean(H), statistics.fmean(A)
            d = (ma - mh) / math.sqrt((sh ** 2 + sa ** 2) / 2)
            cand = {"key": key, "mean_h": mh, "sd_h": sh, "mean_ai": ma, "sd_ai": sa, "d": d}
            if best is None or abs(d) > abs(best["d"]):
                best = cand
        if best:
            model[group] = best
    return model


def log_pdf(x, m, s):
    return -0.5 * math.log(2 * math.pi * s * s) - (x - m) ** 2 / (2 * s * s)


def score(doc, model):
    total = 0.0
    for p in model.values():
        x = doc["features"].get(p["key"])
        if x is None:
            continue
        total += max(-CLIP, min(CLIP, log_pdf(x, p["mean_ai"], p["sd_ai"]) - log_pdf(x, p["mean_h"], p["sd_h"])))
    return total


def auroc(pos, neg):
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--test", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=1000)
    a = ap.parse_args()
    train, test = load(pathlib.Path(a.train)), load(pathlib.Path(a.test))
    model = fit(train)
    threshold = max(score(d, model) for d in train if d["group"] == "human")
    scored = [{"id": d["id"], "group": d["group"], "genre": d["genre"], "model": d.get("model", ""), "score": score(d, model)} for d in test]
    pos = [s["score"] for s in scored if s["group"] == "ai"]
    neg = [s["score"] for s in scored if s["group"] == "human"]
    observed = auroc(pos, neg)
    rng = random.Random(SEED)
    all_scores = pos + neg
    ge = 0
    for _ in range(a.n):
        rng.shuffle(all_scores)
        ge += auroc(all_scores[:len(pos)], all_scores[len(pos):]) >= observed
    result = {
        "train": a.train, "test": a.test, "n_train": len(train), "n_test_human": len(neg), "n_test_ai": len(pos),
        "representatives": model, "threshold_train_human_max": threshold,
        "test_human_over_threshold": [s["id"] for s in scored if s["group"] == "human" and s["score"] > threshold],
        "test_ai_over_threshold": [s["id"] for s in scored if s["group"] == "ai" and s["score"] > threshold],
        "test_auroc": observed, "share_shuffled_auroc_ge_observed": ge / a.n,
        "scores": sorted(scored, key=lambda s: -s["score"]),
    }
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "score.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("scores", "representatives")}, ensure_ascii=False, indent=2))
    for g, p in model.items():
        print(f"  {g}: {p['key']} d={p['d']:+.2f}")


if __name__ == "__main__":
    main()
