#!/usr/bin/env python3
"""기업 기술 블로그 표본 틀을 만든다.

maczniak/awesome-korean-techblog 의 2022-11-30 이전 마지막 커밋(68fbe20, 2022-06-17) README 에서
「기업 블로그」 절의 항목만 읽고, 항목마다 Common Crawl 색인 질의 형식과 글 주소 식을 붙인다.

    curl -sL https://raw.githubusercontent.com/maczniak/awesome-korean-techblog/68fbe200f1fbe44bae1bad1449b71aff80986d09/README.md -o techblog-68fbe20.md
    python3 frames.py techblog-68fbe20.md > out/main/frames/tech.tsv
"""
import csv
import re
import sys
import urllib.parse

SKIP_HOSTS = ("youtube.com", "slideshare.net", "facebook.com", "twitter.com", "github.com/")
# 2026-09-16 1차 파일럿 뒤 결정: 외국 본사 글을 한국어로 옮겨 싣는 블로그는 표본 틀에서 뺀다.
# 표본 글에서 번역 근거를 확인한 곳만 넣었다. 근거는 분석 계획 4.1.
TRANSLATION_BLOGS = {"Amazon Web Services", "Elastic", "Mozilla"}
LISTING = r"/(?:tag|tags|tagged|category|categories|page|author|authors|search|archives?|about|feed|rss)(?:/|$)"
# 목록·태그·소개 쪽이 아닌 경로. 글 쪽인지는 collect_cc.py 가 og:type article 이나 JSON-LD 로 한 번 더 본다.
POST_RE = r"^https?://[^/]+/(?!(?:[^?#]*/)?(?:tag|tags|tagged|category|categories|page|author|authors|search|archives?|about|feed|rss)(?:/|$))[^?#]+$"


def pattern_for(url):
    u = urllib.parse.urlsplit(url)
    host = u.netloc.lower().removeprefix("www.")
    if any(h in host + "/" for h in SKIP_HOSTS):
        return None
    if host == "blog.naver.com":
        blog_id = urllib.parse.parse_qs(u.query).get("blogId", [u.path.strip("/").split("/")[0]])[0]
        return f"m.blog.naver.com/{blog_id}/*"
    path = urllib.parse.unquote(u.path)
    if host.endswith("tistory.com") or path in ("", "/") or re.search(LISTING, path):
        return f"{host}/*"
    if host == "medium.com":
        return f"medium.com/{path.strip('/').split('/')[0]}/*"
    return f"{host}{path.rstrip('/')}/*"


def main():
    text = open(sys.argv[1], encoding="utf-8").read()
    section = text.split("## 기업 블로그", 1)[1].split("\n## ", 1)[0]
    w = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    w.writerow(["company", "url", "pattern", "post_re"])
    seen = set()
    for m in re.finditer(r"^\*\s+\[([^\]]+)\]\((\S+?)\)", section, re.M):
        company, url = m.group(1), m.group(2)
        pattern = pattern_for(url)
        if pattern and company not in seen and company not in TRANSLATION_BLOGS:
            seen.add(company)
            w.writerow([company, url, pattern, POST_RE])


if __name__ == "__main__":
    main()
