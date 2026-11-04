"""난독화 엔진 — feat/contract에서 시그니처를 먼저 합의하고, feat/obfuscator-core에서 구현한다.

입력: 읽기 쉬운 Python 소스 코드(문자열).
출력: 같은 동작을 하지만 사람·AI가 분석하기 어려운 소스 코드(문자열)와,
      무엇을 바꿨는지 설명하는 리포트.

사용 전략 (구현 예정):
- 이름 치환: 변수·함수·인자 이름을 의미 없는 식별자로 바꾼다(ast 기반, 스코프를 추적).
- 주석/docstring 제거: 설명을 지워 의도 추론을 어렵게 한다.
- 문자열 인코딩: 리터럴 문자열을 base64 등으로 인코딩하고 런타임에 복원하는 코드로 감싼다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ObfuscationReport:
    """난독화 과정에서 무엇을 바꿨는지 기록한다."""

    renamed_count: int = 0
    removed_comments: int = 0
    removed_docstrings: int = 0
    encoded_strings: int = 0
    name_mapping: dict[str, str] = field(default_factory=dict)


@dataclass
class ObfuscationOptions:
    """어떤 전략을 켤지 선택한다. 기본값은 모두 켜짐."""

    rename_identifiers: bool = True
    strip_comments: bool = True
    strip_docstrings: bool = True
    encode_strings: bool = True
    seed: int | None = None  # 이름 치환 재현을 위한 시드(선택)


def obfuscate_source(source: str, options: ObfuscationOptions | None = None) -> tuple[str, ObfuscationReport]:
    """소스 코드 문자열을 받아 (난독화된 코드, 리포트)를 반환한다.

    계약(구현이 반드시 지킬 것):
    - 동작 보존: 난독화본을 실행했을 때의 결과(출력·반환값·예외)는 원본과 같아야 한다.
    - 재현성: options.seed가 같고 입력이 같으면 출력도 같아야 한다.
    - 입력이 올바른 Python 문법이 아니면 ValueError를 던진다.
    - 리포트의 개수(renamed_count 등)는 실제로 바뀐 만큼만 센다.

    구현은 feat/obfuscator-core 브랜치에서 채운다. 지금은 시그니처만 고정한다.
    """
    raise NotImplementedError("feat/obfuscator-core에서 구현합니다.")


def obfuscate_file(path: str, options: ObfuscationOptions | None = None) -> tuple[str, ObfuscationReport]:
    """파일 경로를 받아 읽고 obfuscate_source를 호출하는 편의 함수."""
    with open(path, encoding="utf-8") as f:
        source = f.read()
    return obfuscate_source(source, options)
