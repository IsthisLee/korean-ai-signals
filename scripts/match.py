#!/usr/bin/env python3
"""짝마다 긴 쪽 글을 짧은 쪽의 한글 글자 수에 맞춰 문장 경계에서 자른 사본을 만든다.

2026-09-16 사용자 결정: AI 글이 요청한 분량보다 짧게 나오므로, 분량은 생성 때가 아니라 분석 때 맞춘다.
대개 사람 글이 잘리고, AI 글이 더 길면 AI 글이 잘린다. 짝이 되는 AI 글이 제외된 사람 글은 뺀다.

    python3 match.py --src out/main --dst out/main-matched
    python3 signals.py out/main-matched/clean/human/*.txt out/main-matched/clean/ai/*.txt --out out/main-matched/features
    python3 analyze.py --out out/main-matched
"""
import argparse
import csv
import pathlib
import shutil

from common import hangul_count, read_manifest
from signals import kiwi


def truncate(text, target):
    """문장 경계를 지키며 한글 글자 수가 target 에 닿을 때까지만 남긴다."""
    k = kiwi()
    kept, n = [], 0
    for line in text.split("\n"):
        if not line.strip():
            if kept and kept[-1] != "":
                kept.append("")
            continue
        sents = [s.text for s in k.split_into_sents(line)]
        taken = []
        for s in sents:
            if n >= target:
                break
            taken.append(s)
            n += hangul_count(s)
        if taken:
            kept.append(" ".join(taken))
        if n >= target:
            break
    return "\n".join(kept).strip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    a = ap.parse_args()
    src, dst = pathlib.Path(a.src), pathlib.Path(a.dst)
    for group in ("human", "ai"):
        (dst / "clean" / group).mkdir(parents=True, exist_ok=True)
    excluded = {r["id"] for r in read_manifest(src / "excluded.tsv")}
    rows = []
    for h in read_manifest(src / "human.tsv"):
        ai_id = f"ai-{h['id']}"
        h_path, a_path = src / "clean" / "human" / f"{h['id']}.txt", src / "clean" / "ai" / f"{ai_id}.txt"
        if ai_id in excluded or h["id"] in excluded or not h_path.exists() or not a_path.exists():
            excluded.update({h["id"], ai_id})
            continue
        h_text, a_text = h_path.read_text(encoding="utf-8"), a_path.read_text(encoding="utf-8")
        nh, na = hangul_count(h_text), hangul_count(a_text)
        target = min(nh, na)
        h_out = truncate(h_text, target) if nh > target else h_text
        a_out = truncate(a_text, target) if na > target else a_text
        (dst / "clean" / "human" / f"{h['id']}.txt").write_text(h_out, encoding="utf-8")
        (dst / "clean" / "ai" / f"{ai_id}.txt").write_text(a_out, encoding="utf-8")
        rows.append({"pair": h["id"], "human_before": nh, "ai_before": na, "target": target,
                     "human_after": hangul_count(h_out), "ai_after": hangul_count(a_out)})
    for name in ("human.tsv", "ai.tsv"):
        shutil.copy(src / name, dst / name)
    with (dst / "excluded.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["id", "reason"])
        for i in sorted(excluded):
            w.writerow([i, "원래 실행에서 제외했거나 짝이 되는 글이 제외됨"])
    with (dst / "matched.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(*r.values())


if __name__ == "__main__":
    main()
