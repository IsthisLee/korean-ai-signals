#!/usr/bin/env python3
"""문서마다 분석 계획 6.1 의 지표 8개를 계산해 JSON 으로 낸다. 알리기만 하고 글을 고치지 않는다.

    python3 signals.py out/main/clean/human/*.txt out/main/clean/ai/*.txt --out out/main/features

같은 입력에는 늘 같은 출력을 낸다. 형태소 분석은 Kiwi(kiwipiepy 0.23.2) 기본 모델을 쓴다.
번호는 KatFishNet 이 한국어에서 확인한 지표의 번호이고 계획 6.1 의 표와 같다.
"""
import argparse
import collections
import json
import math
import pathlib
import statistics

# (키, 번호, 이름, 연구가 보고한 AI 쪽 방향: up=AI 가 높음, down=AI 가 낮음, both=연구끼리 엇갈림)
FEATURES = [
    ("comma_inclusion", 1, "쉼표가 든 문장 비율", "up"),
    ("comma_rate", 2, "문장별 쉼표÷형태소 평균", "up"),
    ("comma_position", 3, "쉼표의 문장 안 상대 위치", "up"),
    ("comma_segment", 4, "쉼표로 나뉜 구간의 형태소 수(쉼표 있는 문장)", "up"),
    ("comma_pos_pair_div", 5, "쉼표 앞뒤 품사 쌍 종류÷전체", "up"),
    ("spacing_adherence", 7, "의존명사·보조 용언 앞 띄어쓰기 비율", "up"),
    ("mattr", 8, "형태소 MATTR(창 100)", "both"),
    ("pos_ngram_div", 11, "품사 1~5-gram 종류÷전체 평균", "down"),
]

# Kiwi 는 괄호·따옴표를 SSO(여는)·SSC(닫는)로, 「1.」 같은 글머리 번호를 SB 로 태그한다.
PUNCT = {"SF", "SP", "SS", "SSO", "SSC", "SE", "SO"}
NON_MORPH = {"SW", "SB"}

_kiwi = None


def kiwi():
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return _kiwi


def base(tag):
    return str(tag).split("-")[0]


def is_morph(tag):
    return tag not in PUNCT and tag not in NON_MORPH and not tag.startswith("W_")


def ratio(a, b):
    return a / b if b else None


def mattr(items, window=100):
    if not items:
        return None
    if len(items) <= window:
        return len(set(items)) / len(items)
    counts = collections.Counter(items[:window])
    total = len(counts) / window
    steps = 1
    for i in range(window, len(items)):
        old = items[i - window]
        counts[old] -= 1
        if counts[old] == 0:
            del counts[old]
        counts[items[i]] += 1
        total += len(counts) / window
        steps += 1
    return total / steps


def split(text):
    k = kiwi()
    sents = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        for s in k.split_into_sents(line, return_tokens=True):
            toks = [(t.form, base(t.tag), t.start, t.len) for t in s.tokens]
            if any(is_morph(t[1]) for t in toks):
                sents.append({"line": line, "text": s.text, "toks": toks})
    return sents


def features(text):
    sents = split(text)
    all_toks = [t for s in sents for t in s["toks"]]
    morphs = [t for t in all_toks if is_morph(t[1])]
    f = {}

    # 1~5. 쉼표
    with_comma, comma_rates, positions, segments, pairs = 0, [], [], [], []
    for s in sents:
        toks = s["toks"]
        m_in = [t for t in toks if is_morph(t[1])]
        commas = [i for i, t in enumerate(toks) if t[0] == "," and t[1] == "SP"]
        comma_rates.append(len(commas) / len(m_in))
        if not commas:
            continue
        with_comma += 1
        seg = 0
        for i, t in enumerate(toks):
            if i in commas:
                positions.append(sum(1 for u in toks[:i] if is_morph(u[1])) / len(m_in))
                segments.append(seg)
                seg = 0
                if 0 < i < len(toks) - 1:
                    pairs.append((toks[i - 1][1], toks[i + 1][1]))
            elif is_morph(t[1]):
                seg += 1
        segments.append(seg)
    f["comma_inclusion"] = ratio(with_comma, len(sents))
    f["comma_rate"] = statistics.fmean(comma_rates) if comma_rates else None
    f["comma_position"] = statistics.fmean(positions) if positions else None
    f["comma_segment"] = statistics.fmean(segments) if segments else None
    f["comma_pos_pair_div"] = ratio(len(set(pairs)), len(pairs))

    # 7. 의존명사·보조 용언 앞 띄어쓰기
    spaced = checked = 0
    for s in sents:
        toks, line = s["toks"], s["line"]
        for i, (form, tag, start, _) in enumerate(toks):
            if tag not in ("NNB", "VX") or i == 0 or start == 0:
                continue
            prev = toks[i - 1]
            if not is_morph(prev[1]) or prev[1] == "SN":
                continue
            if tag == "VX" and form in ("지", "하") and prev[1] == "EC" and prev[0] in ("아", "어", "여"):
                continue  # -아/어 지다 등은 붙여 쓰는 것이 규칙이라 뺀다(KatFishNet 과 같은 예외)
            checked += 1
            spaced += 1 if line[start - 1].isspace() else 0
    f["spacing_adherence"] = ratio(spaced, checked)

    # 8. 어휘 다양도
    f["mattr"] = mattr([f"{t[0]}/{t[1]}" for t in morphs])

    # 11. 품사 n-gram 다양도
    scores = []
    for n in range(1, 6):
        grams = [tuple(t[1] for t in s["toks"][i:i + n]) for s in sents for i in range(len(s["toks"]) - n + 1)]
        if grams:
            scores.append(len(set(grams)) / len(grams))
    f["pos_ngram_div"] = statistics.fmean(scores) if scores else None

    meta = {"chars": sum(1 for ch in text if not ch.isspace()), "sentences": len(sents),
            "morphemes": len(morphs), "spacing_checked": checked}
    return f, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for path in sorted(a.files):
        p = pathlib.Path(path)
        f, meta = features(p.read_text(encoding="utf-8"))
        clean = {k: (None if v is None or (isinstance(v, float) and math.isnan(v)) else round(v, 6)) for k, v in f.items()}
        (out / f"{p.stem}.json").write_text(json.dumps(
            {"id": p.stem, "meta": meta, "features": clean},
            ensure_ascii=False, sort_keys=True), encoding="utf-8")
        print(p.stem, meta, flush=True)


if __name__ == "__main__":
    main()
