"""feat/metrics에서 measure/compare를 구현한 뒤 채울 테스트."""

import pytest

from src.metrics import measure


def test_measure_not_implemented_yet():
    """계약 단계에서는 NotImplementedError가 나는 것이 정상이다."""
    with pytest.raises(NotImplementedError):
        measure("x = 1")
