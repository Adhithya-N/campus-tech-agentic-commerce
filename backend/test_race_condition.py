"""Fire two simultaneous confirm requests at the same order to prove the race is closed.

Usage: python test_race_condition.py <order_id>
(order_id must currently be in 'pending_confirmation' status - propose one via the chat UI first)
"""
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

BASE_URL = "http://localhost:8000"


def confirm(order_id: int):
    return requests.post(f"{BASE_URL}/api/orders/{order_id}/confirm")


def main():
    if len(sys.argv) != 2:
        print("Usage: python test_race_condition.py <order_id>")
        sys.exit(1)

    order_id = int(sys.argv[1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(confirm, order_id) for _ in range(2)]
        results = [f.result() for f in futures]

    for i, r in enumerate(results, 1):
        print(f"Request {i}: HTTP {r.status_code} - {r.json()}")

    codes = sorted(r.status_code for r in results)
    # Timing decides whether the loser gets caught by the early status check (400)
    # or the atomic claim (409) - both are correct, the invariant that matters is
    # that exactly one request got a real razorpay_order_id back.
    if codes in ([200, 400], [200, 409]):
        print("\nPASS: exactly one request succeeded (200), the other was correctly rejected.")
    else:
        print(f"\nFAIL: expected one 200 and one rejection (400/409), got {codes} - the race may not be fixed.")


if __name__ == "__main__":
    main()
