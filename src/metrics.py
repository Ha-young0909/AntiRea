"""지표 모듈 — feat/metrics에서 구현한다.

obfuscate.py가 만든 전/후 코드를 비교해 "얼마나 읽기 어려워졌는지"를 수치화한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReadabilityMetrics:
    """코드 한 벌(원본 또는 난독화본)에 대한 지표."""

    identifier_readability: float  # 0~1, 식별자가 사전 단어에 가까운 정도
    cyclomatic_complexity: float  # radon 등으로 계산한 평균 복잡도
    comment_ratio: float  # 전체 라인 중 주석/docstring 비율 (0~1)
    line_count: int


@dataclass
class ComparisonResult:
    """원본과 난독화본의 지표 차이."""

    before: ReadabilityMetrics
    after: ReadabilityMetrics

    @property
    def readability_drop(self) -> float:
        """식별자 가독성이 얼마나 떨어졌는지 (0~1, 클수록 더 어려워짐)."""
        return max(0.0, self.before.identifier_readability - self.after.identifier_readability)


def measure(source: str) -> ReadabilityMetrics:
    """소스 코드 한 벌의 가독성 지표를 계산한다.

    구현은 feat/metrics 브랜치에서 채운다(radon으로 복잡도, 사전 기반으로 식별자 평가 등).
    """
    raise NotImplementedError("feat/metrics에서 구현합니다.")


def compare(before_source: str, after_source: str) -> ComparisonResult:
    """원본과 난독화본을 각각 측정해 비교 결과를 반환한다."""
    return ComparisonResult(before=measure(before_source), after=measure(after_source))
