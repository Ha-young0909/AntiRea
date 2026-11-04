"""AI 분석기 — feat/ai-analyzer에서 구현한다.

LLM에게 "이 코드가 뭘 하는지 설명해봐"라고 묻고, 원본 설명과 난독화본 설명이
얼마나 다른지를 점수화한다. 핵심 지표: AI가 원본은 잘 설명하는데
난독화 후엔 얼마나 틀리는가.

API 키는 .env의 ANTHROPIC_API_KEY에서 읽는다 (.env.example 참고, 커밋하지 않음).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnalysisResult:
    """LLM이 코드 한 벌을 보고 내놓은 설명과, 그 설명이 얼마나 정확한지."""

    explanation: str
    correctness_score: float  # 0~1, 원본 의도와 얼마나 일치하는지


@dataclass
class AnalysisComparison:
    """원본/난독화본에 대한 AI 분석 결과 비교."""

    before: AnalysisResult
    after: AnalysisResult

    @property
    def accuracy_drop(self) -> float:
        """난독화로 인해 AI 설명 정확도가 얼마나 떨어졌는지 (0~1, 클수록 효과적)."""
        return max(0.0, self.before.correctness_score - self.after.correctness_score)


def analyze_code(source: str, *, reference_explanation: str | None = None) -> AnalysisResult:
    """LLM에게 코드를 분석시키고 결과를 반환한다.

    reference_explanation이 주어지면(보통 원본에 대한 설명) 그것과 비교해
    correctness_score를 매긴다. 구현은 feat/ai-analyzer 브랜치에서 채운다.

    계약(구현이 반드시 지킬 것):
    - correctness_score는 0~1이며, 1에 가까울수록 AI가 코드의 의도를 정확히 파악한 것이다.
      (난독화가 효과적이면 after 점수가 before보다 낮아진다. 발표 핵심 지표.)
    - reference_explanation이 없으면(원본 분석) 기준 설명이 없으므로 점수는 1.0으로 둔다.
    - API 키는 환경변수(.env의 ANTHROPIC_API_KEY)에서만 읽고, 없으면 RuntimeError를 던진다.
    - 테스트에서 LLM 호출을 모킹할 수 있도록 호출부를 별도 함수로 분리한다.
    """
    raise NotImplementedError("feat/ai-analyzer에서 구현합니다.")


def compare_analysis(before_source: str, after_source: str) -> AnalysisComparison:
    """원본과 난독화본을 각각 AI로 분석하고 비교 결과를 반환한다."""
    before = analyze_code(before_source)
    after = analyze_code(after_source, reference_explanation=before.explanation)
    return AnalysisComparison(before=before, after=after)
