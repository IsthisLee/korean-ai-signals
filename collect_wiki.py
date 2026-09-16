#!/usr/bin/env python3
"""한국어 위키백과 무작위 문서의 2022-11-30 이전 마지막 판에서 본문 문단을 모은다.

    python3 collect_wiki.py --n 10 --out out/pilot --prefix wiki [--exclude 이전manifest.tsv ...]
"""
import argparse
import datetime
import json
import pathlib
import re
import time
import urllib.parse

import lxml.html

from common import CUTOFF, MIN_HANGUL, append_manifest, excluded_keys, hangul_count, http_get, normalize, write_json

API = "https://ko.wikipedia.org/w/api.php"


def api(params):
    q = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    time.sleep(0.3)
    return json.loads(http_get(f"{API}?{q}"))


def paragraphs(html):
    root = lxml.html.fromstring(html)
    for bad in root.xpath('//sup[contains(@class,"reference")] | //style | //*[contains(@class,"mwe-math")] | //*[contains(@class,"noprint")]'):
        bad.drop_tree()
    paras = []
    for p in root.xpath('//div[contains(@class,"mw-parser-output")]/p'):
        t = re.sub(r"\s+", " ", p.text_content()).strip()
        t = re.sub(r"\[(?:주 )?\d+\]", "", t).strip()
        if t:
            paras.append(t)
    return "\n\n".join(paras)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="wiki")
    ap.add_argument("--exclude", nargs="*", default=[])
    a = ap.parse_args()

    out = pathlib.Path(a.out)
    (out / "human").mkdir(parents=True, exist_ok=True)
    manifest = out / "human.tsv"
    ex_urls, ex_titles, _ = excluded_keys(a.exclude + [str(manifest)])
    stats = {"random_titles": 0, "no_revision_before_cutoff": 0, "disambiguation": 0, "too_short": 0, "accepted": 0}
    have = sum(1 for p in (out / "human").glob(f"{a.prefix}-*.txt"))

    while have < a.n:
        for item in api({"action": "query", "list": "random", "rnnamespace": 0, "rnlimit": 20})["query"]["random"]:
            if have >= a.n:
                break
            title = item["title"]
            stats["random_titles"] += 1
            if title in ex_titles:
                continue
            ex_titles.add(title)
            page = api({"action": "query", "prop": "revisions", "titles": title, "rvlimit": 1,
                        "rvstart": CUTOFF, "rvdir": "older", "rvprop": "ids|timestamp"})["query"]["pages"][0]
            if not page.get("revisions"):
                stats["no_revision_before_cutoff"] += 1
                continue
            rev = page["revisions"][0]
            parsed = api({"action": "parse", "oldid": rev["revid"], "prop": "text|categories"})
            if "error" in parsed:
                stats["no_revision_before_cutoff"] += 1
                continue
            if any("동음이의" in c["category"] for c in parsed["parse"].get("categories", [])):
                stats["disambiguation"] += 1
                continue
            text = normalize(paragraphs(parsed["parse"]["text"]))
            n = hangul_count(text)
            if n < MIN_HANGUL:
                stats["too_short"] += 1
                continue
            url = f"https://ko.wikipedia.org/w/index.php?oldid={rev['revid']}"
            if url in ex_urls:
                continue
            have += 1
            doc_id = f"{a.prefix}-{have:02d}"
            (out / "human" / f"{doc_id}.txt").write_text(text + "\n", encoding="utf-8")
            append_manifest(manifest, {
                "id": doc_id, "genre": "wiki", "author": "위키백과 편집자", "title": title, "raw_title": title,
                "url": url, "date": rev["timestamp"], "date_evidence": "위키백과 판 저장 시각(API)",
                "hangul": n, "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            })
            stats["accepted"] += 1
            print(doc_id, title, n, rev["timestamp"], flush=True)
    write_json(out / f"collect-{a.prefix}-stats.json", stats)
    print(stats)


if __name__ == "__main__":
    main()
