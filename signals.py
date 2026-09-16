#!/usr/bin/env python3
"""문서마다 분석 계획 5.2 의 후보 지표를 계산해 JSON 으로 낸다. 알리기만 하고 글을 고치지 않는다.

    python3 signals.py out/pilot/human/*.txt out/pilot/ai/*.txt --out out/pilot/features

같은 입력에는 늘 같은 출력을 낸다. 형태소 분석은 Kiwi(kiwipiepy 0.23.2) 기본 모델, 의존 거리는
spaCy ko_core_news_sm 3.8.0 으로 잰다. 지표 번호는 분석 계획 5.2 표의 번호다.
"""
import argparse
import collections
import json
import math
import pathlib
import statistics

# (키, 5.2 표 번호, 이름, 연구가 보고한 AI 쪽 방향: up=AI 가 높음, down=AI 가 낮음, both=연구끼리 엇갈리거나 방향 미보고)
FEATURES = [
    ("comma_inclusion", 1, "쉼표가 든 문장 비율", "up"),
    ("comma_rate", 2, "문장별 쉼표÷형태소 평균", "up"),
    ("comma_position", 3, "쉼표의 문장 안 상대 위치", "up"),
    ("comma_segment", 4, "쉼표로 나뉜 구간의 형태소 수(쉼표 있는 문장)", "up"),
    ("comma_pos_pair_div", 5, "쉼표 앞뒤 품사 쌍 종류÷전체", "up"),
    ("punct_per_1k", 6, "1,000자당 문장부호", "down"),
    ("spacing_adherence", 7, "의존명사·보조 용언 앞 띄어쓰기 비율", "up"),
    ("mattr", 8, "형태소 MATTR(창 100)", "both"),
    ("lexical_density", 9, "내용 형태소 비율", "down"),
    ("pos_ngram_div", 11, "품사 1~5-gram 종류÷전체 평균", "down"),
    ("noun_ratio", 16, "명사 비율", "down"),
    ("adj_ratio", 16, "형용사 비율", "down"),
    ("adnominal_per_1k", 16, "1,000형태소당 관형형 어미·관형사", "down"),
    ("nominalization_per_1k", 17, "1,000형태소당 -성·-화·명사형 어미", "up"),
    ("aux_per_1k", 18, "1,000형태소당 보조 용언", "up"),
    ("pronoun_per_1k", 19, "1,000형태소당 대명사", "up"),
    ("num_symbol_per_1k", 20, "1,000자당 숫자·기호", "up"),
    ("jkg_per_1k", 21, "1,000형태소당 관형격 조사 -의", "up"),
    ("topic_share", 22, "은/는 ÷ (은/는 + 이/가)", "up"),
    ("geot_ttaemun_per_1k", 23, "1,000형태소당 것/거·때문", "up"),
    ("sent_len", 24, "문장당 어절 수", "down"),
    ("sent_len_cv", 25, "문장 길이 변동계수", "down"),
    ("clauses_per_sent", 26, "문장당 연결어미(보조 용언 앞 제외)", "up"),
    ("dep_distance", 27, "평균 의존 거리(어절)", "up"),
    ("coord_per_1k", 28, "1,000형태소당 접속 조사와 '및'", "both"),
    ("long_causative_per_1k", 29, "1,000형태소당 -게 하다/만들다", "up"),
    ("short_neg_share", 30, "안/못 ÷ (안/못 + -지 않다/못하다)", "down"),
    ("modal_per_1k", 31, "1,000형태소당 -ㄹ 수 있다/없다, -아야 하다/되다", "down"),
    ("epistemic_per_1k", 32, "1,000형태소당 인식 표지", "down"),
    ("discourse_per_1k", 33, "1,000형태소당 담화 표지", "down"),
    ("downtoner_per_1k", 34, "1,000형태소당 완화어", "up"),
    ("degree_adv_per_1k", 35, "1,000형태소당 가장·매우·아주·너무", "up"),
    ("example_emphasis_share", 36, "예시·강조 ÷ (예시·강조 + 조건) 접속 표현", "up"),
    ("contrast_share", 37, "그러나·하지만 ÷ (그러나·하지만 + 그런데)", "up"),
    ("translationese_verbs_per_1k", 39, "1,000형태소당 대하다·의하다·만들다·가지다", "up"),
    ("passive_per_1k", 40, "1,000형태소당 -아/어 지다와 -에 의하여", "both"),
    ("tonghada_per_1k", 41, "1,000형태소당 통하다", "down"),
    ("honorific_ep_per_1k", 42, "1,000형태소당 선어말 어미 -(으)시-", "down"),
    ("demonstrative_per_1k", 43, "1,000형태소당 지시 관형사·지시 대명사", "both"),
    ("quote_per_1k", 43, "1,000형태소당 인용격 조사", "both"),
]
# 5.2 의 10(과용 스타일 어휘)과 12~15(분포 비교)는 문서 하나의 값이 아니라 항목 목록이라 lists 에 센다.
# 38(감정 표현)은 한국어 감성 측정 수단을 정하지 않아 파일럿에서 재지 않는다.
NOT_MEASURED = {38: "한국어 감성 측정 수단을 아직 정하지 않음"}

# Kiwi 는 괄호·따옴표를 SSO(여는)·SSC(닫는)로, 「1.」 같은 글머리 번호를 SB 로 태그한다.
PUNCT = {"SF", "SP", "SS", "SSO", "SSC", "SE", "SO"}
NON_MORPH = {"SW", "SB"}
CONTENT = {"NNG", "NNP", "VV", "VA", "MAG", "XR"}
DISCOURSE = {"그런데", "근데", "사실", "아무튼", "어쨌든", "그러니까", "말하자면", "솔직히", "글쎄", "뭐", "참"}
DOWNTONERS = {"거의", "약간", "조금", "다소", "좀", "살짝", "그다지", "별로", "비교적"}
DEGREE = {"가장", "매우", "아주", "너무"}
EXAMPLE_EMPHASIS = {"예컨대", "이를테면", "특히", "즉"}
CONDITIONAL = {"만약", "만일", "그러면"}
DEMONSTRATIVE_NP = {"이것", "그것", "저것", "이거", "그거", "저거"}

_kiwi = None
_nlp = None


def tools():
    global _kiwi, _nlp
    if _kiwi is None:
        from kiwipiepy import Kiwi
        import spacy
        _kiwi = Kiwi()
        _nlp = spacy.load("ko_core_news_sm")
    return _kiwi, _nlp


def base(tag):
    return str(tag).split("-")[0]


def is_morph(tag):
    return tag not in PUNCT and tag not in NON_MORPH and not tag.startswith("W_")


def ratio(a, b):
    return a / b if b else None


def per1k(a, b):
    return 1000 * a / b if b else None


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
    kiwi, _ = tools()
    sents = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        for s in kiwi.split_into_sents(line, return_tokens=True):
            toks = [(t.form, base(t.tag), t.start, t.len) for t in s.tokens]
            if any(is_morph(t[1]) for t in toks):
                sents.append({"line": line, "text": s.text, "toks": toks})
    return sents


def seq(toks, i, *pairs):
    """toks[i:] 가 (형태 집합 또는 None, 품사 집합 또는 None) 순서와 맞는지."""
    for k, (forms, tags) in enumerate(pairs):
        j = i + k
        if j >= len(toks):
            return False
        form, tag = toks[j][0], toks[j][1]
        if (forms is not None and form not in forms) or (tags is not None and tag not in tags):
            return False
    return True


def features(text):
    _, nlp = tools()
    sents = split(text)
    all_toks = [t for s in sents for t in s["toks"]]
    morphs = [t for t in all_toks if is_morph(t[1])]
    n_m = len(morphs)
    n_chars = sum(1 for ch in text if not ch.isspace())
    tags = collections.Counter(t[1] for t in morphs)
    f = {}

    # 가. 문장부호와 표기
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
    f["punct_per_1k"] = per1k(sum(1 for t in all_toks if t[1] in PUNCT), n_chars)

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

    # 나. 어휘
    f["mattr"] = mattr([f"{t[0]}/{t[1]}" for t in morphs])
    f["lexical_density"] = ratio(sum(tags[t] for t in CONTENT), n_m)

    # 다. 품사와 문법 형태
    scores = []
    for n in range(1, 6):
        grams = [tuple(t[1] for t in s["toks"][i:i + n]) for s in sents for i in range(len(s["toks"]) - n + 1)]
        if grams:
            scores.append(len(set(grams)) / len(grams))
    f["pos_ngram_div"] = statistics.fmean(scores) if scores else None
    f["noun_ratio"] = ratio(tags["NNG"] + tags["NNP"], n_m)
    f["adj_ratio"] = ratio(tags["VA"], n_m)
    f["adnominal_per_1k"] = per1k(tags["ETM"] + tags["MM"], n_m)
    f["nominalization_per_1k"] = per1k(sum(1 for t in morphs if t[1] == "XSN" and t[0] in ("성", "화")) + tags["ETN"], n_m)
    f["aux_per_1k"] = per1k(tags["VX"], n_m)
    f["pronoun_per_1k"] = per1k(tags["NP"], n_m)
    f["num_symbol_per_1k"] = per1k(sum(1 for t in all_toks if t[1] in ("SN", "SW")), n_chars)
    f["jkg_per_1k"] = per1k(tags["JKG"], n_m)
    topic = sum(1 for t in morphs if t[1] == "JX" and t[0] in ("은", "는", "ᆫ"))
    subj = sum(1 for t in morphs if t[1] == "JKS" and t[0] in ("이", "가"))
    f["topic_share"] = ratio(topic, topic + subj)
    f["geot_ttaemun_per_1k"] = per1k(sum(1 for t in morphs if t[0] in ("것", "거", "때문") and t[1] in ("NNB", "NNG")), n_m)

    # 라. 문장 구조
    lens = [len(s["text"].split()) for s in sents]
    f["sent_len"] = statistics.fmean(lens) if lens else None
    f["sent_len_cv"] = (statistics.pstdev(lens) / statistics.fmean(lens)) if len(lens) > 1 else None
    clause_counts = []
    for s in sents:
        toks = s["toks"]
        clause_counts.append(sum(1 for i, t in enumerate(toks) if t[1] == "EC" and not seq(toks, i + 1, (None, {"VX"}))))
    f["clauses_per_sent"] = statistics.fmean(clause_counts) if clause_counts else None
    dists = []
    for line in text.split("\n"):
        if line.strip():
            for t in nlp(line):
                if t.dep_ != "ROOT" and not t.is_punct and t.dep_ != "punct":
                    dists.append(abs(t.i - t.head.i))
    f["dep_distance"] = statistics.fmean(dists) if dists else None

    counts = collections.Counter()
    for s in sents:
        toks = s["toks"]
        for i, (form, tag, _, _) in enumerate(toks):
            if tag == "JC" or (tag in ("MAJ", "MAG") and form == "및"):
                counts["coord"] += 1
            if seq(toks, i, ({"게"}, {"EC"}), ({"하", "만들"}, {"VV", "VX"})):
                counts["long_causative"] += 1
            if tag == "MAG" and form in ("안", "못"):
                counts["short_neg"] += 1
            if tag in ("VX", "VV") and form in ("않", "못하") and i > 0 and toks[i - 1][1] == "EC" and toks[i - 1][0] == "지":
                counts["long_neg"] += 1
            if seq(toks, i, ({"수"}, {"NNB"}), ({"있", "없"}, {"VA", "VV", "VX"})):
                counts["modal"] += 1
            if seq(toks, i, ({"아야", "어야", "여야"}, {"EC"}), ({"하", "되"}, {"VV", "VX"})):
                counts["modal"] += 1
            if tag == "MAG" and form in ("아마", "아마도", "어쩌면", "아무래도"):
                counts["epistemic"] += 1
            if seq(toks, i, ({"것", "거"}, {"NNB"}), ({"같"}, {"VA"})) or seq(toks, i, ({"듯"}, {"NNB"}), ({"하", "싶"}, None)):
                counts["epistemic"] += 1
            if seq(toks, i, ({"것"}, {"NNB"}), ({"으로"}, {"JKB"}), ({"보이"}, {"VV"})):
                counts["epistemic"] += 1
            if tag == "EC" and form.endswith("지") and seq(toks, i + 1, ({"도"}, {"JX"}), ({"모르"}, {"VV"})):
                counts["epistemic"] += 1
            if tag in ("MAJ", "MAG", "IC") and form in DISCOURSE:
                counts["discourse"] += 1
            if tag == "MAG" and form in DOWNTONERS:
                counts["downtoner"] += 1
            if tag == "MAG" and form in DEGREE:
                counts["degree"] += 1
            if (tag in ("MAJ", "MAG") and form in EXAMPLE_EMPHASIS) or seq(toks, i, ({"예"}, {"NNG"}), ({"를"}, {"JKO"}), ({"들"}, {"VV"})) \
                    or seq(toks, i, ({"무엇"}, {"NP"}), ({"보다"}, {"JKB"})):
                counts["example_emphasis"] += 1
            if (tag in ("MAJ", "MAG") and form in CONDITIONAL) or seq(toks, i, ({"그렇"}, {"VA"}), ({"다면"}, {"EC"})):
                counts["conditional"] += 1
            if tag == "MAJ" and form in ("그러나", "하지만"):
                counts["contrast"] += 1
            if tag == "MAJ" and form == "그런데":
                counts["transition"] += 1
            if tag == "VV" and form in ("대하", "의하", "만들", "가지"):
                counts["translationese_verbs"] += 1
            if seq(toks, i, ({"아", "어", "여"}, {"EC"}), ({"지"}, {"VX"})) or seq(toks, i, ({"에"}, {"JKB"}), ({"의하"}, {"VV"})):
                counts["passive"] += 1
            if tag == "VV" and form == "통하":
                counts["tonghada"] += 1
            if tag == "EP" and form in ("시", "으시"):
                counts["honorific"] += 1
            if (tag == "MM" and form in ("이", "그", "저")) or (tag == "NP" and form in DEMONSTRATIVE_NP):
                counts["demonstrative"] += 1
            if tag == "JKQ":
                counts["quote"] += 1

    f["coord_per_1k"] = per1k(counts["coord"], n_m)
    f["long_causative_per_1k"] = per1k(counts["long_causative"], n_m)
    f["short_neg_share"] = ratio(counts["short_neg"], counts["short_neg"] + counts["long_neg"])
    f["modal_per_1k"] = per1k(counts["modal"], n_m)
    f["epistemic_per_1k"] = per1k(counts["epistemic"], n_m)
    f["discourse_per_1k"] = per1k(counts["discourse"], n_m)
    f["downtoner_per_1k"] = per1k(counts["downtoner"], n_m)
    f["degree_adv_per_1k"] = per1k(counts["degree"], n_m)
    f["example_emphasis_share"] = ratio(counts["example_emphasis"], counts["example_emphasis"] + counts["conditional"])
    f["contrast_share"] = ratio(counts["contrast"], counts["contrast"] + counts["transition"])
    f["translationese_verbs_per_1k"] = per1k(counts["translationese_verbs"], n_m)
    f["passive_per_1k"] = per1k(counts["passive"], n_m)
    f["tonghada_per_1k"] = per1k(counts["tonghada"], n_m)
    f["honorific_ep_per_1k"] = per1k(counts["honorific"], n_m)
    f["demonstrative_per_1k"] = per1k(counts["demonstrative"], n_m)
    f["quote_per_1k"] = per1k(counts["quote"], n_m)

    # 10, 12~15: 항목 목록(분석 단계에서 로그 오즈 z 로 비교)
    lists = {
        "lemmas": collections.Counter(f"{t[0]}/{t[1]}" for t in morphs if t[1] in CONTENT),
        "pos_bigrams": collections.Counter(),
        "function_words": collections.Counter(f"{t[0]}/{t[1]}" for t in morphs if t[1][0] in "JE" or t[1].startswith("XS")),
        "josa_bigrams": collections.Counter(),
        "eojeol_patterns": collections.Counter(),
    }
    for s in sents:
        toks, line = s["toks"], s["line"]
        tg = [t[1] for t in toks]
        lists["pos_bigrams"].update(f"{a}+{b}" for a, b in zip(tg, tg[1:]))
        josa = [t[0] + "/" + t[1] for t in toks if t[1].startswith("J")]
        lists["josa_bigrams"].update(f"{a}+{b}" for a, b in zip(josa, josa[1:]))
        words = collections.defaultdict(list)
        for form, tag, start, _ in toks:
            prefix = line[:start]
            words[len(prefix.split()) - (0 if not prefix or prefix[-1].isspace() else 1)].append(tag)
        lists["eojeol_patterns"].update("+".join(v) for v in words.values())

    meta = {"chars": n_chars, "sentences": len(sents), "morphemes": n_m, "spacing_checked": checked,
            "negations": counts["short_neg"] + counts["long_neg"]}
    return f, {k: dict(sorted(v.items())) for k, v in lists.items()}, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for path in sorted(a.files):
        p = pathlib.Path(path)
        f, lists, meta = features(p.read_text(encoding="utf-8"))
        clean = {k: (None if v is None or (isinstance(v, float) and math.isnan(v)) else round(v, 6)) for k, v in f.items()}
        (out / f"{p.stem}.json").write_text(json.dumps(
            {"id": p.stem, "meta": meta, "features": clean, "lists": lists, "not_measured": NOT_MEASURED},
            ensure_ascii=False, sort_keys=True), encoding="utf-8")
        print(p.stem, meta, flush=True)


if __name__ == "__main__":
    main()
