#!/usr/bin/env python3
"""사후 진단: 사람 글을 짝이 되는 AI 글의 한글 글자 수에 맞춰 문장 경계에서 자른 사본을 만든다.

    python3 lenmatch.py --src out/pilot --dst out/pilot-lenmatch
    python3 signals.py out/pilot-lenmatch/clean/human/*.txt --out out/pilot-lenmatch/features
    python3 analyze.py --out out/pilot-lenmatch

AI 글이 사람 글보다 짧게 나와 길이에 민감한 지표가 길이 차이를 잴 수 있으므로 만든 진단이다.
AI 글이 제외된 짝의 사람 글도 뺀다. AI 글과 그 지표는 원래 실행의 것을 그대로 쓴다. 사전 등록 판정이 아니다.
"""
import argparse
import csv
import pathlib
import shutil

from common import hangul_count, read_manifest
from signals import tools


def truncate(text, target):
    kiwi, _ = tools()
    kept, n = [], 0
    for line in text.split("\n"):
        if not line.strip():
            if kept and kept[-1] != "":
                kept.append("")
            continue
        sents = [s.text for s in kiwi.split_into_sents(line)]
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
    (dst / "clean" / "human").mkdir(parents=True, exist_ok=True)
    (dst / "features").mkdir(exist_ok=True)
    excluded = {r["id"] for r in read_manifest(src / "excluded.tsv")}
    clean_rows = {r["id"]: r for r in read_manifest(src / "clean.tsv")}
    rows = []
    for h in read_manifest(src / "human.tsv"):
        ai_id = f"ai-{h['id']}"
        if ai_id in excluded or ai_id not in clean_rows:
            excluded.add(h["id"])
            continue
        target = int(clean_rows[ai_id]["hangul_after"])
        text = (src / "clean" / "human" / f"{h['id']}.txt").read_text(encoding="utf-8")
        cut = truncate(text, target)
        (dst / "clean" / "human" / f"{h['id']}.txt").write_text(cut, encoding="utf-8")
        rows.append((h["id"], hangul_count(text), target, hangul_count(cut)))
    for name in ("human.tsv", "ai.tsv"):
        shutil.copy(src / name, dst / name)
    for p in (src / "features").glob("ai-*.json"):
        shutil.copy(p, dst / "features" / p.name)
    with (dst / "excluded.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["id", "reason"])
        for i in sorted(excluded):
            w.writerow([i, "원래 실행에서 제외했거나 짝이 되는 AI 글이 제외됨"])
    for r in rows:
        print(*r)


if __name__ == "__main__":
    main()
