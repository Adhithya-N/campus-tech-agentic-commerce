"""Autonomous AI buyer agent - demonstrates that this merchant is transactable
by an AI agent, not just a human in a browser. It uses its own Gemini reasoning
to interpret a goal, pick a product, and drive a purchase through the exact same
tools, API, and safety gate a human customer's session uses - no browser, no
human click involved in the decision or order creation.

Completing payment (entering card/UPI details) still requires Razorpay's
Checkout widget in a browser, since a valid payment signature can only be
produced by a real payment event on Razorpay's side - that is a real payment-
network constraint, not a limitation of this agent. What this script proves is
the autonomous decision + order-creation path, protected by the identical
server-side spend cap that protects the human UI.

Usage: python buyer_agent.py "<natural language purchasing goal>"
Example (within cap, should succeed):
    python buyer_agent.py "I need something to keep my laptop safe, budget under 1000 rupees"
Example (over cap, should get blocked):
    python buyer_agent.py "Buy me the mechanical keyboard, price doesn't matter"
"""
import os
import sys

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.agent import _MODEL_CANDIDATES, propose_order, search_catalog
from app.database import get_connection

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

BASE_URL = "http://localhost:8000"

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

_BUYER_INSTRUCTION = (
    "You are an autonomous AI buyer agent acting on behalf of a customer, with a "
    "purchasing goal. Use search_catalog to find real options, then call "
    "propose_order for the single best match. You are authorized to decide and "
    "purchase autonomously within your goal - do not ask for confirmation."
)


def run_buyer(goal: str) -> None:
    chat = _client.chats.create(
        model=_MODEL_CANDIDATES[0],
        config=types.GenerateContentConfig(
            system_instruction=_BUYER_INSTRUCTION,
            tools=[search_catalog, propose_order],
        ),
    )
    print(f"[buyer agent] goal: {goal}")
    response = chat.send_message(goal)
    print(f"[buyer agent] reasoning summary: {response.text}")

    conn = get_connection()
    order = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if order is None:
        print("[buyer agent] no order was drafted - stopping.")
        return

    order_id = order["id"]
    print(
        f"[buyer agent] attempting to autonomously confirm order #{order_id} "
        f"(Rs.{order['amount_paise'] / 100:.2f})..."
    )
    confirm = requests.post(f"{BASE_URL}/api/orders/{order_id}/confirm")
    if confirm.status_code == 200:
        data = confirm.json()
        print(f"[buyer agent] SUCCESS: real Razorpay test order created autonomously - {data['razorpay_order_id']}")
        print(
            "[buyer agent] (completing payment still requires Razorpay's Checkout widget in a "
            "browser - a valid payment signature can only be produced by a real payment event)"
        )
    else:
        detail = confirm.json().get("detail")
        print(f"[buyer agent] BLOCKED by the spend-cap gate (HTTP {confirm.status_code}): {detail}")
        print("[buyer agent] the same deterministic gate that protects the human UI just blocked an autonomous AI buyer too.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python buyer_agent.py "<purchasing goal>"')
        sys.exit(1)
    run_buyer(" ".join(sys.argv[1:]))
