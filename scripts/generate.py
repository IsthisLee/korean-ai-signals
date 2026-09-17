#!/usr/bin/env python3
"""사람 글 한 편마다 같은 제목, 같은 장르, 비슷한 분량으로 Claude 글을 한 편 쓰게 한다.

    python3 generate.py --out out/main            # human.tsv 의 모든 글
    python3 generate.py --out out/main --only wiki-01

모델은 장르마다 id 순서로 claude-opus-5 와 claude-sonnet-5 를 번갈아 쓴다.
사용자 설정, 훅, MCP, 도구를 모두 빼고 빈 폴더에서 돌린다. output style 은 켜지 않는다.
1차 파일럿(2026-09-16)은 분량이 목표의 ±20% 를 벗어나면 한 번 다시 쓰게 했다. 다시 써도 대부분 짧았고
분량은 분석 때 짝 맞춤(match.py)으로 맞추기로 했으므로, 그 뒤로는 한 번만 쓴다(MAX_ATTEMPTS).
"""
import argparse
import csv
import datetime
import json
import pathlib
import re
import subprocess
import tempfile

from common import hangul_count, normalize, read_manifest, write_json

MODELS = ["claude-opus-5", "claude-sonnet-5"]
MAX_ATTEMPTS = 1
HERE = pathlib.Path(__file__).resolve().parent
AI_FIELDS = ["id", "pair", "genre", "model", "title", "target_hangul", "hangul", "ratio", "attempts",
             "cost_usd", "duration_ms", "generated_at"]


def prose_only(text):
    """위키 사람 글은 <p> 문단만 뽑았으므로 AI 글에서도 제목, 목록, 인용 줄을 뺀다."""
    kept = [line for line in text.split("\n")
            if not re.match(r"^\s{0,3}(#{1,6}\s|[-*+]\s|\d+[.)]\s|>)", line)]
    return "\n".join(kept)


def run_claude(model, prompt, workdir):
    cmd = ["claude", "-p", prompt, "--model", model, "--tools", "", "--setting-sources", "",
           "--strict-mcp-config", "--no-session-persistence", "--max-turns", "1", "--output-format", "json"]
    proc = subprocess.run(cmd, cwd=workdir, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f"claude 종료 코드 {proc.returncode}: {proc.stderr[:500]}")
    data = json.loads(proc.stdout)
    if data.get("is_error"):
        raise RuntimeError(f"claude 오류: {str(data.get('result'))[:500]}")
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()

    out = pathlib.Path(a.out)
    (out / "ai").mkdir(parents=True, exist_ok=True)
    (out / "ai-raw").mkdir(exist_ok=True)
    manifest = out / "ai.tsv"
    done = {row["pair"] for row in read_manifest(manifest)}
    humans = sorted(read_manifest(out / "human.tsv"), key=lambda r: (r["genre"], r["id"]))
    index_in_genre = {}
    workdir = tempfile.mkdtemp(prefix="kw-gen-")

    for h in humans:
        k = index_in_genre.get(h["genre"], 0)
        index_in_genre[h["genre"]] = k + 1
        if h["id"] in done or (a.only and h["id"] not in a.only):
            continue
        model = MODELS[k % 2]
        target = int(round(int(h["hangul"]), -1))
        template = (HERE.parent / "prompts" / f"{h['genre']}.txt").read_text(encoding="utf-8")
        prompt = template.format(title=h["title"], chars=f"{target:,}")
        cost = duration = 0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            data = run_claude(model, prompt, workdir)
            cost += data.get("total_cost_usd") or 0
            duration += data.get("duration_ms") or 0
            raw = data.get("result") or ""
            text = normalize(prose_only(raw) if h["genre"] == "wiki" else raw)
            n = hangul_count(text)
            write_json(out / "ai-raw" / f"ai-{h['id']}-{attempt}.json", {"prompt": prompt, "model": model, "response": data})
            if 0.8 <= n / target <= 1.2:
                break
        doc_id = f"ai-{h['id']}"
        (out / "ai" / f"{doc_id}.txt").write_text(text + "\n", encoding="utf-8")
        new = not manifest.exists()
        with manifest.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=AI_FIELDS, delimiter="\t")
            if new:
                w.writeheader()
            w.writerow({"id": doc_id, "pair": h["id"], "genre": h["genre"], "model": model, "title": h["title"],
                        "target_hangul": target, "hangul": n, "ratio": f"{n / target:.2f}", "attempts": attempt,
                        "cost_usd": f"{cost:.4f}", "duration_ms": duration,
                        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")})
        print(doc_id, model, target, n, f"{n / target:.2f}", attempt, f"${cost:.4f}", flush=True)


if __name__ == "__main__":
    main()
