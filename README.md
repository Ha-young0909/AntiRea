# Anti-REA — 코드 난독화 연습

> "보호 전엔 코드가 술술 읽히는데, 난독화 후엔 막힌다"를 숫자와 화면으로 보여주는 연습 프로젝트.

내 Python 코드를 내가 보호하는 방어(난독화) 연습입니다. 원본 코드를 읽기 어렵게 바꾸고,
그 결과 사람·AI의 분석 난도가 얼마나 올라갔는지를 **지표**와 **AI 분석 정답률(before/after)** 로 보여줍니다.

## 파이프라인

```
원본 코드 (samples/target.py)
      │
      ▼
 obfuscate.py   이름 치환 · 주석/docstring 제거 · 문자열 인코딩
      │
      ├────────────▶ metrics.py   이름 가독성 · 복잡도 · 주석 비율 (전/후 수치)
      │
      ▼
 ai.py           LLM에게 "이 코드가 뭐 하는지" 질문 → 원본 대비 정답률 점수화
      │
      ▼
 main.py (Streamlit)   좌: 원본 / 우: 난독화 / 하단: 지표 + AI before&after
```

**핵심 지표:** AI가 원본은 잘 설명하는데 난독화 후엔 얼마나 틀리는가.
→ 성과는 "차단"이 아니라 **"분석에 드는 시간·정확도를 얼마나 떨어뜨렸는가"** 로 말합니다.

## 폴더 구조

```
AntiRea/
├── docs/anti-rea.md          기획 문서
├── samples/target.py         난독화 대상 샘플 코드
├── src/
│   ├── obfuscate.py          난독화 엔진
│   ├── metrics.py            가독성·복잡도 지표
│   ├── ai.py                 LLM 분석기 + 정답률 점수화
│   ├── main.py               Streamlit 비교 화면
│   └── components/           UI 조각
├── tests/                    pytest
└── .github/workflows/        CI (pytest + 난독화 리포트)
```

## 실행

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 키 입력 (AI 분석기 사용 시)
streamlit run src/main.py
```

## 브랜치 (1 브랜치 = 1 담당, main은 PR + Squash and Merge)

| 순서 | 브랜치 | 내용 |
|---|---|---|
| 0 | `docs/anti-rea` | 기획 문서 |
| 1 | `feat/contract` | 함수 시그니처 + 샘플 대상 코드 (먼저 머지) |
| 2 | `feat/obfuscator-core` | 이름 치환·주석 제거·문자열 인코딩 |
| 3 | `feat/metrics` | 가독성·복잡도·주석 비율 |
| 4 | `feat/ai-analyzer` | LLM 분석 호출 + 정답률 점수화 |
| 5 | `feat/ui-compare` | 좌우 비교 화면 |
| 6 | `feat/ci-report` | PR마다 pytest + 리포트 아티팩트 |

2·3·4는 독립이라 동시 진행 가능. 머지 순서: 0 → 1 → (2,3,4) → 5 → 6.

## 한계 (발표용)

- Python은 바이트코드 디컴파일이 쉬워 난독화 효과에 구조적 한계가 있음 → "차단"이 아닌 "분석 비용·정확도 저하"로 설명.
- 안티디버깅·Frida 탐지는 개념 설명까지만.
- 워터마킹 추적은 보류 카드.
