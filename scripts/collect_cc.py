#!/usr/bin/env python3
"""Common Crawl 이 2022-11-30 전에 수집한 블로그 글을 모은다.

수집 시각이 게시일의 상한이 되고, 본문도 그 수집본에서 뽑으므로 나중에 고친 글이 섞이지 않는다.

    # 개인 블로그: awesome-devblog db.yml 의 개인 목록에서 필자를 무작위로 고른다
    python3 collect_cc.py personal --db db.yml --n 10 --out out/main --seed 20260916
    # 기업 기술 블로그: frame tsv(company, pattern, post_regex)에서 회사를 고르고 회사마다 글을 고른다
    python3 collect_cc.py tech --frame frames/tech.tsv --companies 5 --per-company 2 --out out/main --seed 20260916
"""
import argparse
import signal
import csv
import datetime
import gzip
import html
import json
import pathlib
import random
import re
import time
import urllib.error
import urllib.parse

import trafilatura
import yaml

from common import CUTOFF_CDX, MIN_HANGUL, TRANSLATION_MARK, append_manifest, excluded_keys, hangul_count, http_get, normalize, write_json

INDEX = "https://index.commoncrawl.org/{}-index"
DATA = "https://data.commoncrawl.org/"
CRAWLS = ["CC-MAIN-2022-40", "CC-MAIN-2022-33", "CC-MAIN-2022-21"]

# 플랫폼: (db.yml 의 blog 주소에서 계정을 뽑는 식, 색인 질의 형식, 글 주소 식)
PLATFORMS = {
    "tistory": (r"^https?://([a-z0-9-]+)\.tistory\.com", "{0}.tistory.com/*",
                r"^https?://[a-z0-9-]+\.tistory\.com/(?:\d+|entry/[^/?#]+)/?$"),
    "velog": (r"^https?://velog\.io/@([^/?#]+)", "velog.io/@{0}/*",
              r"^https?://velog\.io/@[^/?#]+/(?!series/|series$|about$|followers$|following$)[^/?#]+/?$"),
    "brunch": (r"^https?://brunch\.co\.kr/@([^/?#]+)", "brunch.co.kr/@{0}/*",
               r"^https?://brunch\.co\.kr/@[^/?#]+/\d+/?$"),
    "naver": (r"^https?://(?:m\.)?blog\.naver\.com/([^/?#]+)", "m.blog.naver.com/{0}/*",
              r"^https?://(?:m\.)?blog\.naver\.com/[^/?#]+/\d+/?$"),
}


class UnitTimeout(Exception):
    pass


def _unit_timeout(signum, frame):
    raise UnitTimeout()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def cc_index(crawl, pattern, sleep=1.0, timeout=180, tries=6):
    q = urllib.parse.urlencode({"url": pattern, "output": "json", "limit": 3000})
    time.sleep(sleep)
    try:
        body = http_get(f"{INDEX.format(crawl)}?{q}", timeout=timeout, tries=tries)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]


def candidates(records, post_re):
    best = {}
    for r in records:
        if r.get("status") != "200" or "html" not in r.get("mime", ""):
            continue
        if "kor" not in r.get("languages", "") or r["timestamp"] >= CUTOFF_CDX:
            continue
        url = r["url"].split("#")[0]
        if "?" in url or not re.match(post_re, url):
            continue
        key = re.sub(r"^https?://(?:www\.|m\.)?", "", url).rstrip("/")
        if key not in best or r["timestamp"] > best[key]["timestamp"]:
            best[key] = r
    return [best[k] for k in sorted(best)]


def dechunk(body):
    out, rest = b"", body
    while rest:
        size_line, _, rest = rest.partition(b"\r\n")
        size = int(size_line.split(b";")[0] or b"0", 16)
        if size == 0:
            break
        out, rest = out + rest[:size], rest[size + 2:]
    return out


def fetch_html(r):
    start = int(r["offset"])
    end = start + int(r["length"]) - 1
    raw = gzip.decompress(http_get(DATA + r["filename"], headers={"Range": f"bytes={start}-{end}"}, timeout=180))
    _, _, rest = raw.partition(b"\r\n\r\n")
    head_bytes, _, body = rest.partition(b"\r\n\r\n")
    head = head_bytes.decode("latin-1").lower()
    if re.search(r"^transfer-encoding:\s*chunked", head, re.M):
        body = dechunk(body)
    if re.search(r"^content-encoding:\s*gzip", head, re.M):
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
    m = re.search(r"charset=([\w-]+)", head)
    enc = r.get("encoding") or (m.group(1) if m else "utf-8")
    return body.decode(enc, errors="replace")


def meta_content(page, prop):
    # 값을 감싼 따옴표와 같은 종류가 나올 때까지 읽는다. 「'언택트'가 대세다」처럼 값 안에 다른 따옴표가 있을 수 있다.
    for pat in (rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]*content=(["\'])(.*?)\1',
                rf'<meta[^>]+content=(["\'])(.*?)\1[^>]*(?:property|name)=["\']{prop}["\']'):
        m = re.search(pat, page, re.I | re.S)
        if m:
            return html.unescape(m.group(2)).strip()
    return ""


def page_title(page, fallback):
    """og:title 을 먼저 쓰고, 끝이 「구분자 + og:site_name」일 때만 그 부분을 뗀다.

    구분자로 무조건 자르면 「모바일 UI 디자인 기본용어 - 컨트롤」 같은 제목이 잘린다.
    """
    title = meta_content(page, "og:title") or (fallback or "").strip()
    site = meta_content(page, "og:site_name")
    if site:
        cut = re.match(rf"^(.*\S)\s+(?:\||::|-|–|—)\s+{re.escape(site)}$", title)
        if cut:
            return cut.group(1)
    return title


def take(r, genre, author, doc_id, out):
    page = fetch_html(r)
    text = trafilatura.extract(page, url=r["url"], output_format="markdown", include_comments=False,
                               include_tables=False, include_images=False, favor_precision=True) or ""
    text = normalize(text)
    n = hangul_count(text)
    if n < MIN_HANGUL:
        return None, n
    if TRANSLATION_MARK.search(text):
        return None, -2  # 명시적 번역 표시가 있는 글은 뺀다(2026-09-16 파일럿 뒤 결정)
    if genre == "tech" and not re.search(r'og:type["\']?\s+content=["\']article|"@type"\s*:\s*"(?:Blog)?Posting|"@type"\s*:\s*"(?:Tech)?Article', page):
        return None, -1  # 글 목록이나 소개 쪽을 거르려고 글 쪽 표시(og:type article, JSON-LD)를 요구한다
    meta = trafilatura.extract_metadata(page, default_url=r["url"])
    raw_title = (meta.title if meta else "") or ""
    page_date = (meta.date if meta else "") or ""
    ts = r["timestamp"]
    (out / "human" / f"{doc_id}.txt").write_text(text + "\n", encoding="utf-8")
    (out / "human-html").mkdir(exist_ok=True)
    (out / "human-html" / f"{doc_id}.html").write_text(page, encoding="utf-8")
    row = {
        "id": doc_id, "genre": genre, "author": author, "title": page_title(page, raw_title), "raw_title": raw_title,
        "url": r["url"], "date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}Z",
        "date_evidence": f"Common Crawl {r['filename'].split('/')[1]} 수집 시각" + (f"; 페이지 추출 날짜 {page_date}" if page_date else ""),
        "hangul": n, "fetched_at": now(),
    }
    return row, n


def personal_frame(db_path):
    frame = []
    for entry in yaml.safe_load(pathlib.Path(db_path).read_text(encoding="utf-8")):
        blog = (entry.get("blog") or "").strip()
        for platform, (acct_re, pattern, post_re) in PLATFORMS.items():
            m = re.match(acct_re, blog)
            if m:
                frame.append({"author": entry["name"], "pattern": pattern.format(m.group(1)), "post_re": post_re, "platform": platform})
                break
    return sorted(frame, key=lambda e: (e["author"], e["pattern"]))


def tech_frame(path):
    with open(path, encoding="utf-8", newline="") as f:
        return sorted(csv.DictReader(f, delimiter="\t"), key=lambda e: e["company"])


def collect(units, genre, prefix, per_unit, total, out, seed, stats, ex_urls, ex_authors, tries_per_unit=8,
            sleep=1.0, max_index_errors=0, index_timeout=180, index_tries=6, unit_timeout=0):
    manifest = out / "human.tsv"
    have = len(list((out / "human").glob(f"{prefix}-*.txt")))
    streak = 0  # 색인 오류가 연달아 나면 서버가 죽은 것이다. 표본 틀을 헛되이 소진하지 않게 멈춘다
    for unit in units:
        if have >= total:
            break
        author = unit.get("author") or unit["company"]
        if author in ex_authors:
            continue
        recs = []
        if unit_timeout:
            signal.signal(signal.SIGALRM, _unit_timeout)
            signal.alarm(unit_timeout)
        try:
            last = None
            for crawl in CRAWLS:
                # 색인 하나가 죽어도 다음 수집본 색인으로 넘어간다. 셋이 모두 실패할 때만 오류로 센다.
                try:
                    recs = candidates(cc_index(crawl, unit["pattern"], sleep, index_timeout, index_tries),
                                      unit["post_re"])
                    last = None
                except UnitTimeout:
                    raise
                except Exception as e:
                    last = e
                    continue
                if recs:
                    break
            if last is not None:
                raise last
        except UnitTimeout:
            signal.alarm(0)
            stats["unit_timeout"] = stats.get("unit_timeout", 0) + 1
            print("unit-timeout", author, unit["pattern"], f"{unit_timeout}초", flush=True)
            continue
        except Exception as e:  # 재시도 뒤에도 색인이 응답하지 않으면 이 필자를 건너뛰고 기록한다
            signal.alarm(0)
            stats["index_error"] = stats.get("index_error", 0) + 1
            streak += 1
            print("index-error", author, unit["pattern"], type(e).__name__, flush=True)
            if max_index_errors and streak >= max_index_errors:
                stats["stopped_on_index_errors"] = streak
                print(f"index-down {streak}회 연달아 실패해 멈춘다. 색인이 살아나면 같은 명령으로 이어 받는다", flush=True)
                break
            continue
        signal.alarm(0)
        streak = 0
        if not recs:
            stats["no_capture"] += 1
            continue
        picked = 0
        order = random.Random(f"{seed}:{author}").sample(recs, len(recs))
        for r in order[:tries_per_unit]:
            if picked >= per_unit or have >= total:
                break
            if r["url"] in ex_urls:
                continue
            try:
                row, n = take(r, genre, author, f"{prefix}-{have + 1:02d}", out)
            except Exception as e:  # 수집본 하나가 깨져도 다음 후보로 넘어간다
                stats["fetch_error"] += 1
                print("skip", r["url"], type(e).__name__, e, flush=True)
                continue
            if row is None:
                reason = {-2: "translation_marker", -1: "not_article"}.get(n, "too_short")
                stats[reason] = stats.get(reason, 0) + 1
                continue
            have += 1
            picked += 1
            ex_urls.add(r["url"])
            append_manifest(manifest, row)
            stats["accepted"] += 1
            print(row["id"], author, row["title"], n, row["date"], flush=True)
        print(f"unit {author} 후보 {len(recs)} 열어봄 {min(len(order), tries_per_unit)} 받음 {picked} 누적 {have}/{total}", flush=True)
        if picked:
            ex_authors.add(author)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("genre", choices=["personal", "tech"])
    ap.add_argument("--db")
    ap.add_argument("--frame")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--companies", type=int, default=5)
    ap.add_argument("--per-company", type=int, default=2)
    ap.add_argument("--per-author", type=int, default=1, help="개인 블로그 필자당 글 수(계획 4.1: 두 편까지)")
    ap.add_argument("--tech-total", type=int, help="기술 블로그 전체 편수. 주지 않으면 companies × per-company")
    ap.add_argument("--exclude-urls-only", action="store_true", help="이전 표본과 글 주소만 겹치지 않게 하고 회사·필자는 다시 쓸 수 있게 함")
    ap.add_argument("--tries-per-unit", type=int, default=8, help="필자·회사 하나에서 열어 볼 수집본 글의 최대 수")
    ap.add_argument("--sleep", type=float, default=1.0, help="색인 조회 사이에 쉬는 시간(초). 서버를 덜 두드리려면 늘린다")
    ap.add_argument("--max-index-errors", type=int, default=0, help="색인 오류가 이만큼 연달아 나면 멈춘다. 0 이면 끝까지 돈다")
    ap.add_argument("--index-timeout", type=int, default=180, help="색인 조회 하나의 시간 초과(초)")
    ap.add_argument("--index-tries", type=int, default=6, help="색인 조회 재시도 횟수. 색인이 느릴 때 줄이면 빨리 건너뛴다")
    ap.add_argument("--unit-timeout", type=int, default=0, help="회사·필자 하나의 색인 조회에 두는 시간 상한(초). 0 이면 두지 않는다")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", default="20260916")
    ap.add_argument("--exclude", nargs="*", default=[])
    a = ap.parse_args()

    out = pathlib.Path(a.out)
    (out / "human").mkdir(parents=True, exist_ok=True)
    ex_urls, _, ex_authors = excluded_keys(a.exclude + [str(out / "human.tsv")])
    if a.exclude_urls_only:
        _, _, ex_authors = excluded_keys([str(out / "human.tsv")])
    stats = {"no_capture": 0, "too_short": 0, "fetch_error": 0, "accepted": 0}
    if a.genre == "personal":
        units = personal_frame(a.db)
        random.Random(a.seed).shuffle(units)
        stats["frame_size"] = len(units)
        collect(units, "personal", "personal", a.per_author, a.n, out, a.seed, stats, ex_urls, ex_authors,
                sleep=a.sleep, max_index_errors=a.max_index_errors,
                index_timeout=a.index_timeout, index_tries=a.index_tries, unit_timeout=a.unit_timeout)
    else:
        units = tech_frame(a.frame)
        random.Random(a.seed).shuffle(units)
        stats["frame_size"] = len(units)
        total = a.tech_total or a.companies * a.per_company
        collect(units, "tech", "tech", a.per_company, total, out, a.seed, stats, ex_urls, ex_authors, a.tries_per_unit,
                sleep=a.sleep, max_index_errors=a.max_index_errors,
                index_timeout=a.index_timeout, index_tries=a.index_tries, unit_timeout=a.unit_timeout)
    write_json(out / f"collect-{a.genre}-stats.json", stats)
    print(stats)


if __name__ == "__main__":
    main()
