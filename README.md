# korean-ai-signals

한국어로 사람이 쓴 글과 Claude 가 쓴 글을 같은 제목으로 짝지어 모으고, 연구 근거가 있는 표층 지표를 재는 장비입니다.

무엇을 재는지와 판정 기준은 [분석 계획](docs/plan.md)에 결과보다 먼저 적었습니다. 용어 풀이와 배경부터 적어 두었으므로 처음 보는 분은 그 문서부터 읽으시면 됩니다. 이 문서에는 돌리는 순서만 적습니다.

이 결과는 Claude Code 플러그인 [korean-kit](https://github.com/IsthisLee/korean-kit) 의 검사 규칙과 윤문 도구를 고르는 근거로 씁니다. 표본은 어떤 모델의 학습에도 쓰지 않습니다.

수집한 사람 글 본문, AI 글, 지표, 보고서는 모두 `out/` 에 쌓이고 `.gitignore` 가 커밋을 막습니다. 표본 목록(URL, 날짜, 필자, 글자 수)만 결과를 기록할 때 따로 커밋합니다.

## 준비

```bash
python3 -m venv .venv
.venv/bin/pip install kiwipiepy==0.23.2 trafilatura==2.2.0 scipy==1.18.1 pyyaml==6.0.3
```

AI 글 생성에는 로그인된 `claude` 명령(2.1.272 에서 확인)이 필요합니다.

## 돌리는 순서

```bash
PY=.venv/bin/python
OUT=out/main

# 1. 사람 글: 위키 300, 기술 블로그 129, 개인 블로그 58 (수집을 마쳤습니다)
$PY scripts/collect_wiki.py --n 300 --out $OUT --prefix wiki
gh api repos/sarojaba/awesome-devblog/contents/db.yml?ref=1106089ee274c0846e422e45031cc9b48a289591 --jq .download_url \
  | xargs curl -sL -o $OUT/frames/awesome-devblog-1106089.yml
$PY scripts/collect_cc.py personal --db $OUT/frames/awesome-devblog-1106089.yml --n 150 --out $OUT --seed 20260916
curl -sL https://raw.githubusercontent.com/maczniak/awesome-korean-techblog/68fbe200f1fbe44bae1bad1449b71aff80986d09/README.md \
  -o $OUT/frames/techblog-68fbe20.md
python3 scripts/frames.py $OUT/frames/techblog-68fbe20.md > $OUT/frames/tech.tsv
$PY scripts/collect_cc.py tech --frame $OUT/frames/tech.tsv --out $OUT --seed 20260916

# 2. AI 글: 사람 글 한 편마다 한 편, 장르마다 opus-5 와 sonnet-5 를 번갈아
$PY scripts/generate.py --out $OUT

# 3. 정리, 짝 맞춤, 지표, 비교
# 글 대신 자료를 요청한 응답은 $OUT/excluded.tsv(id, reason)에,
# 본문 앞뒤에 붙은 사용자에게 하는 말은 $OUT/meta_paragraphs.tsv(id, prefix, reason)에 적는다
$PY scripts/clean.py --out $OUT
$PY scripts/match.py --src $OUT --dst $OUT-matched
$PY scripts/signals.py $OUT-matched/clean/human/*.txt $OUT-matched/clean/ai/*.txt --out $OUT-matched/features
$PY scripts/analyze.py --out $OUT-matched

# 4. 사람이 대조할 표, 지표를 합친 문서 점수
$PY scripts/spotcheck.py --out $OUT-matched
$PY scripts/score.py --train <훈련 실행> --test <시험 실행> --out <결과>
```

표본 목록과 제외 목록만 커밋합니다. 사람 글 문장이 그대로 든 `spotcheck.md` 와 보고서 사본은 `out/` 에만 둡니다.

수집 스크립트는 이미 저장한 글을 세어 이어서 받습니다. 도중에 멈추면 같은 명령을 다시 돌립니다.

## 구조

```
docs/plan.md   결과보다 먼저 적은 분석 계획. 배경·용어 풀이·판정 기준
prompts/       장르별 AI 글 프롬프트
scripts/       수집·생성·정리·측정 스크립트
results/       표본 목록과 수치 원본(본 측정 뒤에 커밋합니다)
out/           본문·지표·보고서. 커밋하지 않습니다
```

## 파일

아래는 모두 `scripts/` 안에 있습니다.


| 파일 | 하는 일 |
| --- | --- |
| `common.py` | 기준일, 최소 글자 수(한글 800자), 사람 글과 AI 글에 똑같이 적용하는 정리 함수, 표본 목록 읽기·쓰기 |
| `collect_wiki.py` | 위키백과 무작위 문서의 2022-11-30 이전 마지막 판에서 `<p>` 문단을 뽑음 |
| `frames.py` | 기업 기술 블로그 목록에서 Common Crawl 질의 형식을 붙인 표본 틀을 만듦 |
| `collect_cc.py` | Common Crawl 이 2022-11-30 전에 수집한 블로그 글을 수집본에서 뽑음 |
| `prompts/` | 장르별 AI 글 프롬프트 |
| `generate.py` | `claude -p` 로 AI 글을 씀 |
| `clean.py` | 사람 글과 AI 글에서 제목 줄, 위키 AI 글의 미디어위키 제목 줄, 기록한 메타 문단을 같은 규칙으로 빼고 제외 문서를 거름 |
| `signals.py` | 문서마다 검증된 지표 8개를 계산함 |
| `analyze.py` | 사람 글과 AI 글을 비교하고 `report.md`, `results.json` 을 씀 |
| `spotcheck.py` | 형태소 분석과 띄어쓰기 판정을 사람이 대조할 표를 만듦 |
| `match.py` | 짝마다 긴 쪽 글을 짧은 쪽의 한글 글자 수에 맞춰 문장 경계에서 자름 |
| `score.py` | 지표 묶음마다 대표 지표의 로그 우도비를 더한 문서 점수를 한 실행으로 만들고 다른 실행으로 확인함 |
