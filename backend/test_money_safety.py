"""Automated money-safety checks: invalid input rejection, spend-cap enforcement,
and payment-signature verification.

Calls propose_order directly (bypassing the LLM) so these are deterministic, then
exercises the real HTTP endpoints for the parts that don't involve the LLM.

Requires the backend server running on localhost:8000.
Usage: python test_money_safety.py
"""
import requests

from app.agent import propose_order
from app.database import get_connection

BASE_URL = "http://localhost:8000"
results = []


def check(name: str, condition: bool) -> None:
    results.append((name, condition))
    print(f"{'PASS' if condition else 'FAIL'}: {name}")


def last_order_id() -> int:
    conn = get_connection()
    row = conn.execute("SELECT id FROM orders ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return row["id"]


def test_invalid_product_id():
    result = propose_order(product_id=99999, quantity=1)
    check("invalid product id is rejected, not drafted", "no product" in result.lower())


def test_over_stock_quantity():
    result = propose_order(product_id=1, quantity=999999)
    check("over-stock quantity is rejected", "only" in result.lower() and "in stock" in result.lower())


def test_over_cap_block():
    propose_order(product_id=7, quantity=1)  # Mechanical Keyboard, Rs.2999 - over the Rs.2000 cap
    order_id = last_order_id()
    confirm = requests.post(f"{BASE_URL}/api/orders/{order_id}/confirm")
    check("over-cap order is blocked at confirm time", confirm.status_code == 400)


def test_tampered_signature():
    propose_order(product_id=1, quantity=1)  # Wireless Earbuds, within cap
    order_id = last_order_id()
    confirm = requests.post(f"{BASE_URL}/api/orders/{order_id}/confirm")
    if confirm.status_code != 200:
        check("order confirmed (prerequisite for signature test)", False)
        return
    verify = requests.post(
        f"{BASE_URL}/api/orders/{order_id}/verify-payment",
        json={"razorpay_payment_id": "pay_fake123", "razorpay_signature": "tampered_signature_xyz"},
    )
    check("tampered payment signature is rejected", verify.status_code == 400)


if __name__ == "__main__":
    test_invalid_product_id()
    test_over_stock_quantity()
    test_over_cap_block()
    test_tampered_signature()
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{passed}/{len(results)} checks passed.")
