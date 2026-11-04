"""feat/obfuscator-core에서 obfuscate_source를 구현한 뒤 채울 테스트."""

import pytest

from src.obfuscate import ObfuscationOptions, obfuscate_source


def test_obfuscate_source_not_implemented_yet():
    """계약 단계에서는 NotImplementedError가 나는 것이 정상이다."""
    with pytest.raises(NotImplementedError):
        obfuscate_source("x = 1", ObfuscationOptions())
