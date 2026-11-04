"""feat/obfuscator-core의 obfuscate_source 구현에 대한 테스트."""

from __future__ import annotations

import io
import textwrap
from contextlib import redirect_stdout

import pytest

from src.obfuscate import ObfuscationOptions, obfuscate_file, obfuscate_source


def _run(source: str) -> str:
    """소스를 실행하고 stdout을 문자열로 반환한다(동작 비교용).

    __name__을 "__main__"으로 둬서 `if __name__ == "__main__":` 블록도 실행되게 한다.
    """
    buf = io.StringIO()
    namespace: dict = {"__name__": "__main__"}
    with redirect_stdout(buf):
        exec(compile(source, "<test>", "exec"), namespace)  # noqa: S102 - 동작 비교용 테스트 하네스
    return buf.getvalue()


SAMPLE = textwrap.dedent(
    '''\
    """샘플 모듈 docstring."""

    from dataclasses import dataclass


    @dataclass
    class ShoppingCart:
        """장바구니."""

        items: dict

        def add_item(self, name, price, quantity=1):
            """상품 추가."""
            if name in self.items:
                existing_price, existing_quantity = self.items[name]
                self.items[name] = (existing_price, existing_quantity + quantity)
            else:
                self.items[name] = (price, quantity)

        def total_price(self):
            # 부가세 없음
            return sum(price * qty for price, qty in self.items.values())


    def summarize_cart(cart):
        """장바구니를 요약한다."""
        lines = [f"- {name}: {qty}" for name, (price, qty) in cart.items.items()]
        lines.append(f"총액: {cart.total_price():.2f}")
        return "\\n".join(lines)


    if __name__ == "__main__":
        cart = ShoppingCart(items={})
        cart.add_item("notebook", 1200.0, 2)
        cart.add_item("pen", 300.0, 5)
        print(summarize_cart(cart))
    '''
)


def test_obfuscate_source_preserves_behavior():
    obfuscated, _ = obfuscate_source(SAMPLE, ObfuscationOptions(seed=1))
    assert _run(obfuscated) == _run(SAMPLE)


def test_obfuscate_source_is_reproducible_with_same_seed():
    out1, report1 = obfuscate_source(SAMPLE, ObfuscationOptions(seed=42))
    out2, report2 = obfuscate_source(SAMPLE, ObfuscationOptions(seed=42))
    assert out1 == out2
    assert report1.name_mapping == report2.name_mapping


def test_obfuscate_source_rejects_invalid_syntax():
    with pytest.raises(ValueError):
        obfuscate_source("def f(:\n  pass", ObfuscationOptions())


def test_obfuscate_source_renames_locals_but_not_class_or_attrs():
    obfuscated, report = obfuscate_source(SAMPLE, ObfuscationOptions(seed=7))
    assert report.renamed_count > 0
    # 클래스 이름과 속성/메서드 이름은 그대로 유지되어야 한다 (속성 접근은 바꾸면 안 됨).
    assert "class ShoppingCart" in obfuscated
    assert ".add_item(" in obfuscated
    assert ".total_price(" in obfuscated
    assert "self.items" in obfuscated
    # 매개변수 이름(name/price/quantity 등)은 키워드 인자로 쓰이지 않으므로 치환 대상이다.
    assert "name" in report.name_mapping
    assert "price" in report.name_mapping
    assert "quantity" in report.name_mapping


def test_obfuscate_source_can_disable_renaming():
    options = ObfuscationOptions(
        rename_identifiers=False,
        strip_comments=False,
        strip_docstrings=False,
        encode_strings=False,
    )
    obfuscated, report = obfuscate_source(SAMPLE, options)
    assert report.renamed_count == 0
    assert report.name_mapping == {}
    assert obfuscated == SAMPLE


def test_obfuscate_source_strips_docstrings_when_enabled():
    options = ObfuscationOptions(
        rename_identifiers=False,
        strip_comments=False,
        strip_docstrings=True,
        encode_strings=False,
    )
    obfuscated, report = obfuscate_source(SAMPLE, options)
    assert report.removed_docstrings > 0
    assert "샘플 모듈 docstring" not in obfuscated
    assert "장바구니를 요약한다" not in obfuscated


def test_obfuscate_source_keeps_docstrings_when_disabled():
    options = ObfuscationOptions(
        rename_identifiers=False,
        strip_comments=False,
        strip_docstrings=False,
        encode_strings=False,
    )
    obfuscated, report = obfuscate_source(SAMPLE, options)
    assert report.removed_docstrings == 0
    assert "샘플 모듈 docstring" in obfuscated


def test_obfuscate_source_encodes_string_literals():
    source = "greeting = 'hello world'\nprint(greeting)\n"
    options = ObfuscationOptions(
        rename_identifiers=False,
        strip_comments=False,
        strip_docstrings=False,
        encode_strings=True,
    )
    obfuscated, report = obfuscate_source(source, options)
    assert report.encoded_strings == 1
    assert "hello world" not in obfuscated
    assert "b64decode" in obfuscated
    assert _run(obfuscated) == "hello world\n"


def test_obfuscate_source_encoded_strings_preserve_behavior_for_fstrings():
    obfuscated, report = obfuscate_source(SAMPLE, ObfuscationOptions(seed=3))
    assert report.encoded_strings > 0
    assert _run(obfuscated) == _run(SAMPLE)


def test_obfuscate_source_counts_only_actual_comment_removal():
    source = "x = 1  # 주석\ny = 2\n"
    options = ObfuscationOptions(
        rename_identifiers=False,
        strip_comments=True,
        strip_docstrings=False,
        encode_strings=False,
    )
    obfuscated, report = obfuscate_source(source, options)
    assert report.removed_comments == 1
    assert "#" not in obfuscated


def test_obfuscate_source_does_not_report_comment_removal_when_disabled_and_no_other_rewrite():
    source = "x = 1  # 주석\n"
    options = ObfuscationOptions(
        rename_identifiers=False,
        strip_comments=False,
        strip_docstrings=False,
        encode_strings=False,
    )
    obfuscated, report = obfuscate_source(source, options)
    assert report.removed_comments == 0
    assert "# 주석" in obfuscated


def test_obfuscate_file_reads_and_delegates(tmp_path):
    p = tmp_path / "sample.py"
    p.write_text(SAMPLE, encoding="utf-8")
    obfuscated, report = obfuscate_file(str(p), ObfuscationOptions(seed=5))
    assert report.renamed_count > 0
    assert _run(obfuscated) == _run(SAMPLE)
