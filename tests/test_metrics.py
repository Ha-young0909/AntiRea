"""feat/metrics의 measure/compare 구현에 대한 테스트."""

from __future__ import annotations

import textwrap

import pytest

from src.metrics import compare, measure
from src.obfuscate import ObfuscationOptions, obfuscate_source

READABLE_SOURCE = textwrap.dedent(
    '''\
    """장바구니 모듈."""


    def apply_discount(total_price, percent):
        """할인율을 적용한 금액을 반환한다."""
        # 0~100 범위만 허용한다
        if not 0 <= percent <= 100:
            raise ValueError("할인율은 0에서 100 사이여야 합니다.")
        return total_price * (1 - percent / 100)
    '''
)

STRAIGHT_LINE_SOURCE = "x = 1\ny = 2\nz = x + y\n"

BRANCHING_SOURCE = textwrap.dedent(
    """\
    def classify(n):
        if n < 0:
            return "negative"
        elif n == 0:
            return "zero"
        else:
            return "positive"
    """
)


def test_measure_rejects_invalid_syntax():
    with pytest.raises(ValueError):
        measure("def f(:\n  pass")


def test_measure_is_pure_and_deterministic():
    m1 = measure(READABLE_SOURCE)
    m2 = measure(READABLE_SOURCE)
    assert m1 == m2


def test_measure_ratios_are_within_0_and_1():
    m = measure(READABLE_SOURCE)
    assert 0.0 <= m.identifier_readability <= 1.0
    assert 0.0 <= m.comment_ratio <= 1.0


def test_measure_line_count_matches_source():
    m = measure(STRAIGHT_LINE_SOURCE)
    assert m.line_count == 3


def test_measure_straight_line_code_has_baseline_complexity():
    m = measure(STRAIGHT_LINE_SOURCE)
    assert m.cyclomatic_complexity == 1.0


def test_measure_branching_code_has_higher_complexity_than_straight_line():
    branching = measure(BRANCHING_SOURCE)
    straight = measure(STRAIGHT_LINE_SOURCE)
    assert branching.cyclomatic_complexity > straight.cyclomatic_complexity


def test_measure_detects_comments_and_docstrings():
    commented = measure(READABLE_SOURCE)
    bare = measure(
        "def apply_discount(total_price, percent):\n    return total_price * (1 - percent / 100)\n"
    )
    assert commented.comment_ratio > bare.comment_ratio


def test_measure_scores_readable_names_higher_than_obfuscated_names():
    readable = measure(
        "def apply_discount(total_price, percent):\n    return total_price * (1 - percent / 100)\n"
    )
    obfuscated_source, report = obfuscate_source(
        "def apply_discount(total_price, percent):\n    return total_price * (1 - percent / 100)\n",
        ObfuscationOptions(seed=1),
    )
    assert report.renamed_count > 0
    obfuscated = measure(obfuscated_source)
    assert obfuscated.identifier_readability < readable.identifier_readability


def test_compare_returns_before_and_after():
    result = compare(READABLE_SOURCE, STRAIGHT_LINE_SOURCE)
    assert result.before == measure(READABLE_SOURCE)
    assert result.after == measure(STRAIGHT_LINE_SOURCE)


def test_comparison_readability_drop_is_nonnegative_and_floored_at_zero():
    # 일부러 가독성이 더 떨어지는 방향으로 compare — drop이 양수여야 한다.
    before = "def apply_discount(total_price, percent):\n    return total_price * (1 - percent / 100)\n"
    after, _ = obfuscate_source(before, ObfuscationOptions(seed=1))
    result = compare(before, after)
    assert result.readability_drop > 0.0

    # 반대로 비교하면(가독성이 '좋아지는' 방향) 0 아래로는 안 내려가야 한다.
    reversed_result = compare(after, before)
    assert reversed_result.readability_drop == 0.0


def test_measure_on_real_sample_shows_obfuscation_hurts_readability():
    with open("samples/target.py", encoding="utf-8") as f:
        original = f.read()
    obfuscated, _ = obfuscate_source(original, ObfuscationOptions(seed=1))

    before_metrics = measure(original)
    after_metrics = measure(obfuscated)

    assert after_metrics.identifier_readability < before_metrics.identifier_readability
    assert after_metrics.comment_ratio <= before_metrics.comment_ratio
