#!/usr/bin/env python3
"""분석 계획 5.1 의 사람 대조용 표를 만든다. 사람 글과 AI 글에서 문장 10개씩을 시드로 뽑아
형태소 분석 결과와 띄어쓰기 판정(의존명사·보조 용언 앞 공백 여부)을 원문 옆에 적는다.

    python3 spotcheck.py --out out/pilot
"""
import argparse
import pathlib
import random

from signals import is_morph, split


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-group", type=int, default=10)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    lines = ["# 형태소·띄어쓰기 대조표", "", "각 문장의 분석이 원문과 맞는지 사람이 표시합니다. 틀린 곳은 오른쪽 칸에 적습니다.", ""]
    for group in ("human", "ai"):
        pool = []
        for p in sorted((out / "clean" / group).glob("*.txt")):
            for s in split(p.read_text(encoding="utf-8")):
                if sum(1 for t in s["toks"] if is_morph(t[1])) >= 5:
                    pool.append((p.stem, s))
        for doc_id, s in random.Random(f"20260916:{group}").sample(pool, a.per_group):
            toks, line = s["toks"], s["line"]
            checks = []
            for i, (form, tag, start, _) in enumerate(toks):
                if tag in ("NNB", "VX") and i > 0 and start > 0:
                    checks.append(f"{form}/{tag}:{'띄움' if line[start - 1].isspace() else '붙임'}")
            lines += [f"## {doc_id}", "", f"> {s['text']}", "",
                      "| 형태소 분석 | 띄어쓰기 판정 | 틀린 곳 |", "| --- | --- | --- |",
                      f"| {' '.join(f'{t[0]}/{t[1]}' for t in toks)} | {', '.join(checks) or '해당 없음'} | |", ""]
    (out / "spotcheck.md").write_text("\n".join(lines), encoding="utf-8")
    print(out / "spotcheck.md")


if __name__ == "__main__":
    main()
