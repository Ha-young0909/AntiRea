"""지표 모듈 — feat/metrics에서 구현한다.

obfuscate.py가 만든 전/후 코드를 비교해 "얼마나 읽기 어려워졌는지"를 수치화한다.

구현 노트:
- identifier_readability는 외부 사전 파일 없이(순수 함수 계약을 지키기 위해) 구조적
  신호만으로 "이름이 단어처럼 보이는 정도"를 추정한다: (1) snake_case/camelCase로
  쪼갠 조각이 전부 알파벳이고 모음을 포함하는가, (2) 모음 비율, (3) 숫자가 섞여
  있는가. `obfuscate.py`가 만드는 `_ob4yng5b` 같은 이름은 숫자가 섞여 있고 조각이
  알파벳 전용이 아니라서 낮은 점수를 받고, `existing_price` 같은 이름은 높은
  점수를 받는다 — 완벽한 "영어 사전" 판정은 아니지만, 두 벌의 코드를 같은 기준으로
  비교하는 용도로는 충분하다.
- cyclomatic_complexity는 radon의 함수/메서드 단위 복잡도 평균이다. 분기문이 없는
  순수 스크립트(함수가 없는 코드)는 radon이 아무 블록도 반환하지 않으므로, 이 경우
  McCabe 복잡도의 관례대로 1.0(직선 코드)으로 둔다.
- comment_ratio는 (주석 줄 수 + docstring이 차지하는 줄 수) / 전체 줄 수 다.
"""

from __future__ import annotations

import ast
import builtins
import io
import keyword as kwmod
import re
import tokenize
from dataclasses import dataclass

from radon.complexity import cc_visit

_VOWELS = set("aeiou")
_BUILTIN_NAMES = set(dir(builtins))
_KEYWORD_NAMES = set(kwmod.kwlist) | set(getattr(kwmod, "softkwlist", []))
_CAMEL_SPLIT_RE = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")


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
        return max(
            0.0, self.before.identifier_readability - self.after.identifier_readability
        )


# ---------------------------------------------------------------------------
# 식별자 이름 수집 (사용자가 정한 이름만 — 빌트인/키워드/던더 제외)
# ---------------------------------------------------------------------------


def _target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            names.extend(_target_names(elt))
        return names
    return []


def _collect_identifier_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()

    def add(name: str | None) -> None:
        if not name or name in _BUILTIN_NAMES or name in _KEYWORD_NAMES:
            return
        if name.startswith("__") and name.endswith("__"):
            return
        names.add(name)

    def add_params(args: ast.arguments) -> None:
        for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            add(a.arg)
        if args.vararg:
            add(args.vararg.arg)
        if args.kwarg:
            add(args.kwarg.arg)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(node.name)
            add_params(node.args)
        elif isinstance(node, ast.Lambda):
            add_params(node.args)
        elif isinstance(node, ast.ClassDef):
            add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for n in _target_names(t):
                    add(n)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            if isinstance(node.target, ast.Name):
                add(node.target.id)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            for n in _target_names(node.target):
                add(n)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars:
                    for n in _target_names(item.optional_vars):
                        add(n)
        elif isinstance(node, ast.ExceptHandler):
            add(node.name)
        elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            add(node.target.id)
        elif isinstance(
            node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        ):
            for gen in node.generators:
                for n in _target_names(gen.target):
                    add(n)

    return names


# ---------------------------------------------------------------------------
# 식별자 하나의 "단어다움" 점수
# ---------------------------------------------------------------------------


def _split_segments(name: str) -> list[str]:
    """snake_case/camelCase 식별자를 단어 조각으로 나눈다."""
    stripped = name.strip("_")
    if not stripped:
        return []
    parts: list[str] = []
    for chunk in stripped.split("_"):
        if not chunk:
            continue
        found = _CAMEL_SPLIT_RE.findall(chunk)
        parts.extend(found if found else [chunk])
    return parts


def _score_identifier(name: str) -> float:
    segments = _split_segments(name)
    if not segments:
        return 0.0

    word_like = sum(
        1 for s in segments if s.isalpha() and any(c in _VOWELS for c in s.lower())
    )
    word_like_ratio = word_like / len(segments)

    letters = [c for c in name if c.isalpha()]
    vowel_ratio = (
        (sum(1 for c in letters if c.lower() in _VOWELS) / len(letters))
        if letters
        else 0.0
    )

    digit_ratio = (sum(1 for c in name if c.isdigit()) / len(name)) if name else 0.0

    score = 0.5 * word_like_ratio + 0.3 * vowel_ratio + 0.2 * (1 - digit_ratio)
    return max(0.0, min(1.0, score))


def _identifier_readability(tree: ast.AST) -> float:
    names = _collect_identifier_names(tree)
    if not names:
        return 1.0  # 판단할 이름이 없으면 중립값
    return sum(_score_identifier(n) for n in names) / len(names)


# ---------------------------------------------------------------------------
# 주석/docstring 비율
# ---------------------------------------------------------------------------


def _comment_line_numbers(source: str) -> set[int]:
    lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                lines.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return lines


def _docstring_line_count(tree: ast.AST) -> int:
    total = 0
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                doc = body[0]
                end = getattr(doc, "end_lineno", doc.lineno) or doc.lineno
                total += max(1, end - doc.lineno + 1)
    return total


def _comment_ratio(source: str, tree: ast.AST, line_count: int) -> float:
    if line_count <= 0:
        return 0.0
    ratio = (
        len(_comment_line_numbers(source)) + _docstring_line_count(tree)
    ) / line_count
    return max(0.0, min(1.0, ratio))


# ---------------------------------------------------------------------------
# 순환 복잡도
# ---------------------------------------------------------------------------


def _cyclomatic_complexity(source: str) -> float:
    try:
        blocks = cc_visit(source)
    except Exception:  # noqa: BLE001 - ast.parse로 이미 문법 검증을 마쳤음; radon 자체 실패에 대한 방어적 처리
        return 1.0
    if not blocks:
        return 1.0  # 분기 없는 직선 코드의 관례적 McCabe 복잡도
    return sum(b.complexity for b in blocks) / len(blocks)


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def measure(source: str) -> ReadabilityMetrics:
    """소스 코드 한 벌의 가독성 지표를 계산한다.

    계약(구현이 반드시 지킬 것):
    - 순수 함수: 파일·네트워크 접근 없이 입력 문자열만으로 계산한다.
    - 입력이 올바른 Python 문법이 아니면 ValueError를 던진다.
    - identifier_readability, comment_ratio는 항상 0~1 범위다.
    - 원본과 난독화본에 같은 함수를 그대로 호출한다(비교 기준이 같아야 한다).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"유효한 Python 코드가 아닙니다: {exc}") from exc

    line_count = len(source.splitlines())

    return ReadabilityMetrics(
        identifier_readability=_identifier_readability(tree),
        cyclomatic_complexity=_cyclomatic_complexity(source),
        comment_ratio=_comment_ratio(source, tree, line_count),
        line_count=line_count,
    )


def compare(before_source: str, after_source: str) -> ComparisonResult:
    """원본과 난독화본을 각각 측정해 비교 결과를 반환한다."""
    return ComparisonResult(before=measure(before_source), after=measure(after_source))
