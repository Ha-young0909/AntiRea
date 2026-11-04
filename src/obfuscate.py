"""난독화 엔진 — feat/contract에서 시그니처를 먼저 합의하고, feat/obfuscator-core에서 구현한다.

입력: 읽기 쉬운 Python 소스 코드(문자열).
출력: 같은 동작을 하지만 사람·AI가 분석하기 어려운 소스 코드(문자열)와,
      무엇을 바꿨는지 설명하는 리포트.

사용 전략 (구현 예정):
- 이름 치환: 변수·함수·인자 이름을 의미 없는 식별자로 바꾼다(ast 기반, 스코프를 추적).
- 주석/docstring 제거: 설명을 지워 의도 추론을 어렵게 한다.
- 문자열 인코딩: 리터럴 문자열을 base64 등으로 인코딩하고 런타임에 복원하는 코드로 감싼다.

구현 노트 (한계, 발표 때 같이 설명할 것):
- 이름 치환은 "안전하게 바꿀 수 있는 이름"만 바꾼다. 클래스 이름과 메서드 이름,
  클래스 속성(self.x 류)은 바꾸지 않는다 — 속성 접근(obj.attr)은 AST상 Name이 아니라
  Attribute이므로, 이름만 바꾸면 호출부가 깨진다(동작 보존 계약 위반). 그래서 실제로
  바뀌는 것은 지역 변수, 함수/메서드의 매개변수, 그리고 속성이 아닌 일반 함수 이름이다.
- 주석 보존(strip_comments=False)은 다른 AST 변환(이름 치환/docstring 제거/문자열 인코딩)이
  전혀 없을 때만 보장된다. 코드를 ast로 재생성(unparse)하는 순간 주석은 AST에 없는 정보라서
  함께 사라진다 — 그래서 removed_comments는 "옵션이 켜졌는가"가 아니라 "실제 출력에서
  주석이 몇 개 사라졌는가"를 비교해서 센다(계약의 "실제로 바뀐 만큼만 센다"를 그대로 따른 것).
- Python 바이트코드/소스는 디컴파일이 쉬워서, 이 난독화는 "분석을 막는 것"이 아니라
  "분석 비용(시간)과 AI 설명 정확도를 떨어뜨리는 것"이 목표다.
"""

from __future__ import annotations

import ast
import builtins
import io
import keyword as kwmod
import random
import string
import tokenize
from dataclasses import dataclass, field

_BUILTIN_NAMES = set(dir(builtins))
_KEYWORD_NAMES = set(kwmod.kwlist) | set(getattr(kwmod, "softkwlist", []))
_ALWAYS_EXCLUDE = {"self", "cls"}


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


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------


def _target_names(target: ast.expr) -> list[str]:
    """대입 대상(Name/Tuple/List/Starred)에서 치환 가능한 변수 이름을 뽑는다.

    Attribute(self.x)·Subscript(arr[0])는 새 이름을 만들지 않으므로 빈 리스트를 반환한다.
    """
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


def _count_comments(source: str) -> int:
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        return sum(1 for tok in tokens if tok.type == tokenize.COMMENT)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return 0


def _strip_comments_from_text(source: str) -> str:
    """다른 AST 변환이 없을 때, 주석만 토큰 단위로 제거한다(포맷은 최대한 보존)."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source
    kept = [tok for tok in tokens if tok.type != tokenize.COMMENT]
    try:
        return tokenize.untokenize(kept)
    except Exception:  # noqa: BLE001 - untokenize 실패 시 원본을 그대로 반환하는 방어적 fallback
        return source


# ---------------------------------------------------------------------------
# 이름 치환 대상 수집
# ---------------------------------------------------------------------------


def _collect_global_excludes(tree: ast.AST) -> set[str]:
    """어디서든 이름을 바꾸면 안 되는 식별자 집합(빌트인/키워드/던더/임포트/클래스명/
    global·nonlocal 대상/키워드 인자 이름 등)을 모은다."""
    excludes: set[str] = (
        set(_BUILTIN_NAMES) | set(_KEYWORD_NAMES) | set(_ALWAYS_EXCLUDE)
    )

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and node.id.startswith("__")
            and node.id.endswith("__")
        ):
            excludes.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("__") and node.name.endswith("__"):
                excludes.add(node.name)
        elif isinstance(node, ast.ClassDef):
            excludes.add(node.name)  # 클래스 이름은 치환하지 않는다
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                excludes.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            excludes.update(node.names)
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg:
                    excludes.add(
                        kw.arg
                    )  # 키워드 인자 이름은 호출부와 맞춰야 하므로 제외

    return excludes


def _collect_method_names(tree: ast.AST) -> set[str]:
    """클래스 본문에 '직접' 정의된 메서드 이름(속성으로 호출되므로 치환 불가)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(stmt.name)
    return names


def _collect_class_attr_names(tree: ast.AST) -> set[str]:
    """클래스 본문에 '직접' 대입된 이름(클래스/인스턴스 속성이 되므로 치환 불가)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        names.update(_target_names(t))
                elif (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    or isinstance(stmt, ast.AugAssign)
                    and isinstance(stmt.target, ast.Name)
                ):
                    names.add(stmt.target.id)
    return names


def _collect_renameable_function_defs(tree: ast.AST) -> set[str]:
    """메서드가 아닌 함수 정의 이름(모듈 최상위 함수, 함수/메서드 내부의 중첩 함수)."""
    names: set[str] = set()

    class _Walker(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # 메서드 "이름"은 건너뛰고, 메서드 내부는 계속 들어가서 본다.
                    self.generic_visit(stmt)
                else:
                    self.visit(stmt)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            names.add(node.name)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            names.add(node.name)
            self.generic_visit(node)

    _Walker().visit(tree)
    return names


class _LocalNameCollector(ast.NodeVisitor):
    """지역 변수·매개변수 이름(클래스 속성은 제외)을 모은다."""

    def __init__(self, global_excludes: set[str]) -> None:
        self.global_excludes = global_excludes
        self.names: set[str] = set()

    def _add(self, name: str | None) -> None:
        if name and name not in self.global_excludes:
            self.names.add(name)

    def _add_params(self, args: ast.arguments, is_method: bool) -> None:
        positional = list(args.posonlyargs) + list(args.args)
        for i, a in enumerate(positional):
            if is_method and i == 0 and a.arg in _ALWAYS_EXCLUDE:
                continue
            self._add(a.arg)
        for a in args.kwonlyargs:
            self._add(a.arg)
        if args.vararg:
            self._add(args.vararg.arg)
        if args.kwarg:
            self._add(args.kwarg.arg)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # 클래스 "속성" 대입은 건너뛰고, 메서드/중첩 클래스 정의만 계속 본다.
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.visit(stmt)

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool
    ) -> None:
        self._add_params(node.args, is_method)
        for d in list(node.args.defaults) + [
            d for d in node.args.kw_defaults if d is not None
        ]:
            self.visit(d)
        for stmt in node.body:
            self.visit(stmt)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_method=self._is_direct_method(node))

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_method=self._is_direct_method(node))

    @staticmethod
    def _is_direct_method(_node: ast.AST) -> bool:
        # visit_ClassDef에서만 메서드로 진입하므로, 호출 경로상 항상 메서드로 취급해도 안전하다.
        # (중첩 함수는 visit_FunctionDef 내부의 generic 재귀가 아니라 함수 본문 순회로 들어오며,
        #  그 경우도 self/cls 이름이 아니면 그대로 변수 취급되어 문제가 없다.)
        return True

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._add_params(node.args, is_method=False)
        self.visit(node.body)

    def visit_Assign(self, node: ast.Assign) -> None:
        for t in node.targets:
            for n in _target_names(t):
                self._add(n)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name):
            self._add(node.target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self._add(node.target.id)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        if isinstance(node.target, ast.Name):
            self._add(node.target.id)
        self.generic_visit(node)

    def _visit_for(self, node: ast.For | ast.AsyncFor) -> None:
        for n in _target_names(node.target):
            self._add(n)
        self.generic_visit(node)

    visit_For = _visit_for
    visit_AsyncFor = _visit_for

    def _visit_with(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            if item.optional_vars:
                for n in _target_names(item.optional_vars):
                    self._add(n)
        self.generic_visit(node)

    visit_With = _visit_with
    visit_AsyncWith = _visit_with

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._add(node.name)
        self.generic_visit(node)

    def _visit_comp(
        self,
        node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    ) -> None:
        for gen in node.generators:
            for n in _target_names(gen.target):
                self._add(n)
        self.generic_visit(node)

    visit_ListComp = _visit_comp
    visit_SetComp = _visit_comp
    visit_DictComp = _visit_comp
    visit_GeneratorExp = _visit_comp


def _generate_new_name(rng: random.Random, used: set[str]) -> str:
    alphabet = string.ascii_lowercase + string.digits
    while True:
        candidate = "_ob" + "".join(rng.choice(alphabet) for _ in range(6))
        if candidate not in used:
            return candidate


def _build_rename_mapping(tree: ast.AST, seed: int | None) -> dict[str, str]:
    global_excludes = _collect_global_excludes(tree)
    global_excludes |= _collect_method_names(tree)
    global_excludes |= _collect_class_attr_names(tree)

    collector = _LocalNameCollector(global_excludes)
    collector.visit(tree)
    local_names = collector.names

    function_names = _collect_renameable_function_defs(tree) - global_excludes

    eligible = (local_names | function_names) - global_excludes
    if not eligible:
        return {}

    rng = random.Random(seed)
    used: set[str] = set()
    mapping: dict[str, str] = {}
    for original in sorted(eligible):
        new_name = _generate_new_name(rng, used)
        used.add(new_name)
        mapping[original] = new_name
    return mapping


class _Renamer(ast.NodeTransformer):
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if node.id in self.mapping:
            node.id = self.mapping[node.id]
        return node

    def _rename_args(self, args: ast.arguments) -> None:
        for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            if a.arg in self.mapping:
                a.arg = self.mapping[a.arg]
        if args.vararg and args.vararg.arg in self.mapping:
            args.vararg.arg = self.mapping[args.vararg.arg]
        if args.kwarg and args.kwarg.arg in self.mapping:
            args.kwarg.arg = self.mapping[args.kwarg.arg]

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        if node.name in self.mapping:
            node.name = self.mapping[node.name]
        self._rename_args(node.args)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(
        self, node: ast.AsyncFunctionDef
    ) -> ast.AsyncFunctionDef:
        if node.name in self.mapping:
            node.name = self.mapping[node.name]
        self._rename_args(node.args)
        self.generic_visit(node)
        return node

    def visit_Lambda(self, node: ast.Lambda) -> ast.Lambda:
        self._rename_args(node.args)
        self.generic_visit(node)
        return node

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> ast.ExceptHandler:
        if node.name and node.name in self.mapping:
            node.name = self.mapping[node.name]
        self.generic_visit(node)
        return node


# ---------------------------------------------------------------------------
# docstring 제거
# ---------------------------------------------------------------------------


class _DocstringStripper(ast.NodeTransformer):
    def __init__(self) -> None:
        self.count = 0

    def _strip_body(self, body: list[ast.stmt]) -> list[ast.stmt]:
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            self.count += 1
            body = body[1:]
            if not body:
                body = [ast.Pass()]
        return body

    def visit_Module(self, node: ast.Module) -> ast.Module:
        self.generic_visit(node)
        node.body = self._strip_body(node.body)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        self.generic_visit(node)
        node.body = self._strip_body(node.body)
        return node

    def visit_AsyncFunctionDef(
        self, node: ast.AsyncFunctionDef
    ) -> ast.AsyncFunctionDef:
        self.generic_visit(node)
        node.body = self._strip_body(node.body)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        self.generic_visit(node)
        node.body = self._strip_body(node.body)
        return node


# ---------------------------------------------------------------------------
# 문자열 인코딩
# ---------------------------------------------------------------------------


def _collect_skip_string_node_ids(tree: ast.AST) -> set[int]:
    """docstring과 타입 힌트로 쓰인 문자열 리터럴은 인코딩 대상에서 뺀다.

    (docstring을 디코드 호출식으로 바꾸면 __doc__이 사라지고, 문자열 타입 힌트를
    바꾸면 평가 시점 동작이 달라질 수 있어 "동작 보존" 계약에 위배된다.)
    """
    skip_ids: set[int] = set()

    def mark(node: ast.expr | None) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            skip_ids.add(id(node))

    def mark_docstring(body: list[ast.stmt]) -> None:
        if body and isinstance(body[0], ast.Expr):
            mark(body[0].value)

    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            mark_docstring(node.body)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            mark(node.returns)
            all_args = (
                list(node.args.posonlyargs)
                + list(node.args.args)
                + list(node.args.kwonlyargs)
            )
            for a in all_args:
                mark(a.annotation)
            if node.args.vararg:
                mark(node.args.vararg.annotation)
            if node.args.kwarg:
                mark(node.args.kwarg.annotation)
        if isinstance(node, ast.AnnAssign):
            mark(node.annotation)

    return skip_ids


def _make_decode_call(encoded_ascii: str) -> ast.Call:
    """`__import__('base64').b64decode('<encoded>').decode('utf-8')` 노드를 만든다."""
    return ast.Call(
        func=ast.Attribute(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Call(
                        func=ast.Name(id="__import__", ctx=ast.Load()),
                        args=[ast.Constant(value="base64")],
                        keywords=[],
                    ),
                    attr="b64decode",
                    ctx=ast.Load(),
                ),
                args=[ast.Constant(value=encoded_ascii)],
                keywords=[],
            ),
            attr="decode",
            ctx=ast.Load(),
        ),
        args=[ast.Constant(value="utf-8")],
        keywords=[],
    )


class _StringEncoder(ast.NodeTransformer):
    def __init__(self, skip_ids: set[int]) -> None:
        self.skip_ids = skip_ids
        self._in_joinedstr = 0
        self.count = 0

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.JoinedStr:
        # f-string 내부의 리터럴 조각은 건드리지 않는다(문법적으로 안전하게 분리 불가).
        self._in_joinedstr += 1
        self.generic_visit(node)
        self._in_joinedstr -= 1
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.expr:
        if (
            self._in_joinedstr == 0
            and isinstance(node.value, str)
            and id(node) not in self.skip_ids
        ):
            encoded = (
                __import__("base64")
                .b64encode(node.value.encode("utf-8"))
                .decode("ascii")
            )
            new_node = _make_decode_call(encoded)
            ast.copy_location(new_node, node)
            self.count += 1
            return new_node
        return node


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def obfuscate_source(
    source: str, options: ObfuscationOptions | None = None
) -> tuple[str, ObfuscationReport]:
    """소스 코드 문자열을 받아 (난독화된 코드, 리포트)를 반환한다.

    계약(구현이 반드시 지킬 것):
    - 동작 보존: 난독화본을 실행했을 때의 결과(출력·반환값·예외)는 원본과 같아야 한다.
    - 재현성: options.seed가 같고 입력이 같으면 출력도 같아야 한다.
    - 입력이 올바른 Python 문법이 아니면 ValueError를 던진다.
    - 리포트의 개수(renamed_count 등)는 실제로 바뀐 만큼만 센다.
    """
    options = options or ObfuscationOptions()

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"유효한 Python 코드가 아닙니다: {exc}") from exc

    orig_comment_count = _count_comments(source)

    docstring_count = 0
    if options.strip_docstrings:
        stripper = _DocstringStripper()
        tree = stripper.visit(tree)
        docstring_count = stripper.count

    name_mapping: dict[str, str] = {}
    if options.rename_identifiers:
        name_mapping = _build_rename_mapping(tree, options.seed)
        if name_mapping:
            tree = _Renamer(name_mapping).visit(tree)

    encoded_count = 0
    if options.encode_strings:
        skip_ids = _collect_skip_string_node_ids(tree)
        encoder = _StringEncoder(skip_ids)
        tree = encoder.visit(tree)
        encoded_count = encoder.count

    needs_ast_rewrite = (
        options.strip_docstrings or options.rename_identifiers or options.encode_strings
    )

    if needs_ast_rewrite:
        ast.fix_missing_locations(tree)
        try:
            output = ast.unparse(tree)
        except Exception as exc:  # pragma: no cover - 방어적 처리
            raise ValueError(f"난독화 결과를 생성할 수 없습니다: {exc}") from exc
    elif options.strip_comments:
        output = _strip_comments_from_text(source)
    else:
        output = source

    final_comment_count = _count_comments(output)
    removed_comments = max(0, orig_comment_count - final_comment_count)

    report = ObfuscationReport(
        renamed_count=len(name_mapping),
        removed_comments=removed_comments,
        removed_docstrings=docstring_count,
        encoded_strings=encoded_count,
        name_mapping=name_mapping,
    )
    return output, report


def obfuscate_file(
    path: str, options: ObfuscationOptions | None = None
) -> tuple[str, ObfuscationReport]:
    """파일 경로를 받아 읽고 obfuscate_source를 호출하는 편의 함수."""
    with open(path, encoding="utf-8") as f:
        source = f.read()
    return obfuscate_source(source, options)
