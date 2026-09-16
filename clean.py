#!/usr/bin/env python3
"""지표를 계산하기 전에 사람 글과 AI 글을 같은 규칙으로 정리해 out/<실행>/clean/ 에 쓴다. 원본은 고치지 않는다.

    python3 clean.py --out out/pilot

규칙
1. 모든 글: 제목과 같은 줄(앞의 # 과 공백 차이는 무시)을 뺀다. 사람 글 추출본과 AI 글 모두 제목을 본문 첫 줄에 넣기도 한다.
2. 위키 AI 글: 미디어위키 제목 줄(== 제목 ==)을 뺀다. 위키 사람 글은 <p> 문단만 뽑았기 때문이다.
3. meta_paragraphs.tsv(id, prefix, reason)에 적은 문단을 뺀다. 글 본문이 아니라 사용자에게 하는 말(주의 문구, 확인 요청)이다.
4. excluded.tsv(id, reason)에 적은 문서는 쓰지 않는다.
"""
import argparse
import csv
import pathlib
import re

from common import hangul_count, read_manifest

FIELDS = ["id", "group", "genre", "hangul_before", "hangul_after", "removed"]


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"^\s*#+\s*", "", s)).strip()


def clean(text, title, genre, group, meta_prefixes):
    removed = []
    paragraphs = re.split(r"\n\s*\n", text.strip())
    kept_pars = []
    for par in paragraphs:
        if any(par.strip().startswith(p) for p in meta_prefixes):
            removed.append("메타 문단")
            continue
        lines = []
        for line in par.split("\n"):
            if title and norm(line) == norm(title):
                removed.append("제목 줄")
                continue
            if group == "ai" and genre == "wiki" and re.match(r"^\s*=+\s*[^=].*?\s*=+\s*$", line):
                removed.append("미디어위키 제목 줄")
                continue
            lines.append(line)
        if any(l.strip() for l in lines):
            kept_pars.append("\n".join(lines))
    return "\n\n".join(kept_pars) + "\n", removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    excluded = {r["id"] for r in read_manifest(out / "excluded.tsv")}
    meta = {}
    for r in read_manifest(out / "meta_paragraphs.tsv"):
        meta.setdefault(r["id"], []).append(r["prefix"])
    docs = [("human", r) for r in read_manifest(out / "human.tsv")] + [("ai", r) for r in read_manifest(out / "ai.tsv")]
    rows = []
    for group, r in docs:
        if r["id"] in excluded:
            continue
        src = out / group / f"{r['id']}.txt"
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8")
        cleaned, removed = clean(text, r["title"], r["genre"], group, meta.get(r["id"], []))
        dst = out / "clean" / group / f"{r['id']}.txt"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(cleaned, encoding="utf-8")
        rows.append({"id": r["id"], "group": group, "genre": r["genre"], "hangul_before": hangul_count(text),
                     "hangul_after": hangul_count(cleaned), "removed": ";".join(removed)})
    with (out / "clean.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    for row in rows:
        if row["removed"]:
            print(row["id"], row["hangul_before"], "->", row["hangul_after"], row["removed"])
    print(len(rows), "docs written to", out / "clean")


if __name__ == "__main__":
    main()
