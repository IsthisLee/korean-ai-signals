"""표본 수집, 생성, 분석이 함께 쓰는 값과 함수."""
import csv
import http.client
import json
import pathlib
import re
import time
import urllib.error
import urllib.request

# ChatGPT 가 처음 공개된 날. 사람 글은 이 시각보다 앞선 판이나 수집본만 쓴다.
CUTOFF = "2022-11-30T00:00:00Z"
CUTOFF_CDX = "20221130000000"
MIN_HANGUL = 800
USER_AGENT = "korean-writing-signals/0.1 (+https://github.com/IsthisLee/korean-writing)"

MANIFEST_FIELDS = [
    "id", "genre", "author", "title", "raw_title", "url",
    "date", "date_evidence", "hangul", "fetched_at",
]

# 2026-09-16 1차 파일럿 뒤 결정: 본문에 명시적인 번역 표시가 있는 블로그 글은 뺀다.
TRANSLATION_MARK = re.compile(
    r"원문은|원문 ?보기|원문으로 가기|원문 ?링크|원문:|한국어 번역|번역한 (?:것|글)|번역했습니다|옮긴이|역자 주"
    r"|Translated by|originally (?:published|posted)", re.I)

_HANGUL = re.compile(r"[가-힣]")
_FENCE = re.compile(r"^(```|~~~)[^\n]*\n.*?^\1[^\n]*$", re.S | re.M)


def hangul_count(text):
    return len(_HANGUL.findall(text))


def normalize(text):
    """사람 글 추출본과 AI 글에 똑같이 적용하는 정리. 코드 블록, 표, 마크다운 기호를 뺀다."""
    text = text.replace("\r\n", "\n")
    text = _FENCE.sub("", text)
    lines = []
    for line in text.split("\n"):
        s = line.rstrip()
        if re.match(r"^\s*\|.*\|\s*$", s) or re.match(r"^\s*([-*_]\s*){3,}$", s):
            continue
        s = re.sub(r"^\s{0,3}#{1,6}\s+", "", s)
        s = re.sub(r"^\s*>\s?", "", s)
        s = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", s)
        s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
        s = re.sub(r"`([^`\n]*)`", r"\1", s)
        s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
        s = re.sub(r"<[^>\n]+>", "", s)
        lines.append(s.strip())
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def http_get(url, headers=None, timeout=90, tries=6):
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 403, 410) or attempt == tries - 1:
                raise
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError):
            if attempt == tries - 1:
                raise
        time.sleep(5 * (attempt + 1))


def read_manifest(path):
    path = pathlib.Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def append_manifest(path, row):
    path = pathlib.Path(path)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, delimiter="\t", extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def excluded_keys(paths):
    """이미 쓴 표본(파일럿 등)의 URL, 제목, 필자. 본 실행과 겹치지 않게 한다."""
    urls, titles, authors = set(), set(), set()
    for p in paths:
        for row in read_manifest(p):
            urls.add(row["url"])
            titles.add(row["title"])
            authors.add(row["author"])
    return urls, titles, authors


def write_json(path, obj):
    pathlib.Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
