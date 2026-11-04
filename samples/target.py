"""난독화 연습용 샘플 대상 코드.

의도적으로 사람이 읽기 쉬운 상태로 둡니다(이름이 의미를 담고, 주석과 docstring이 있음).
obfuscate.py가 이 파일을 입력으로 받아 "꼬인 코드"를 만들어내는 대상입니다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ShoppingCart:
    """장바구니: 상품과 수량을 담고 총액을 계산한다."""

    items: dict[str, tuple[float, int]]

    def add_item(self, name: str, price: float, quantity: int = 1) -> None:
        """상품을 장바구니에 추가한다. 이미 있으면 수량을 더한다."""
        if name in self.items:
            existing_price, existing_quantity = self.items[name]
            self.items[name] = (existing_price, existing_quantity + quantity)
        else:
            self.items[name] = (price, quantity)

    def remove_item(self, name: str) -> None:
        """상품을 장바구니에서 제거한다."""
        self.items.pop(name, None)

    def total_price(self) -> float:
        """부가세 없이 총액을 계산한다."""
        return sum(price * quantity for price, quantity in self.items.values())

    def apply_discount(self, percent: float) -> float:
        """할인율(percent, 0~100)을 적용한 총액을 반환한다."""
        if not 0 <= percent <= 100:
            raise ValueError("할인율은 0에서 100 사이여야 합니다.")
        total = self.total_price()
        return total * (1 - percent / 100)


def summarize_cart(cart: ShoppingCart) -> str:
    """장바구니 내용을 사람이 읽을 수 있는 문자열로 요약한다."""
    lines = [f"- {name}: {qty}개 x {price:.2f}" for name, (price, qty) in cart.items.items()]
    lines.append(f"총액: {cart.total_price():.2f}")
    return "\n".join(lines)


if __name__ == "__main__":
    cart = ShoppingCart(items={})
    cart.add_item("notebook", 1200.0, 2)
    cart.add_item("pen", 300.0, 5)
    print(summarize_cart(cart))
    print(f"10% 할인 후: {cart.apply_discount(10):.2f}")
