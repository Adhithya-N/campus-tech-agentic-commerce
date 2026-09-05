"""Baseline-vs-agent evaluation: for a fixed set of customer intents with a known
correct product, compare (a) raw keyword search with no AI interpretation against
(b) the actual conversational agent's autonomous product selection.

This does NOT fabricate a revenue number - it measures an honest proxy (does the
right product get surfaced / selected) that's realistic for a hackathon-scale
experiment, run against the real catalog and the real agent pipeline.

Requires GEMINI_API_KEY to be set (does not require the backend server running).
Each row costs 1-2 real Gemini API calls.

Usage: python evaluate_agent.py
"""
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.agent import _MODEL_CANDIDATES, propose_order, search_catalog
from app.database import get_connection

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

_EVAL_INSTRUCTION = (
    "You are a shopping assistant. Use search_catalog to find real products, then "
    "call propose_order for the single best match to the customer's request. "
    "Always call propose_order once you've identified the right product."
)

# (customer intent, expected correct product_id)
CASES = [
    ("I want some wireless earbuds", 1),
    ("something to charge my phone fast", 3),
    ("I need a case to protect my phone from drops", 2),
    ("a short cable to charge my laptop, about 1 meter", 4),
    ("I need to protect my 14 inch laptop while traveling", 5),
    ("notebooks for taking class notes", 6),
    ("a good mechanical keyboard for typing, budget is not a concern", 7),
    ("a quiet mouse that won't disturb my roommate", 8),
]

# (customer intent, expected correct product_id, over-budget/wrong distractor product_id)
# These specifically require budget or price-comparison reasoning that a keyword
# search has no mechanism for, even if it can find the relevant category of items.
CONSTRAINT_CASES = [
    ("I need to charge my phone, but I only have 250 rupees to spend", 4, 3),
    ("Between your mouse and your mechanical keyboard, which one is cheaper? Buy me that one.", 8, 7),
]


def baseline_finds_correct(intent: str, expected_id: int) -> bool:
    """Simulates a plain keyword search box - tries each individual word from the
    intent as a search box would, no LLM interpretation of the full sentence."""
    words = [w.strip(".,!?'") for w in intent.split() if len(w) > 3]
    for word in words:
        if f"#{expected_id} " in search_catalog(word):
            return True
    return False


def baseline_resolves_constraint(intent: str, expected_id: int, distractor_id: int) -> str:
    """For budget/comparison queries: does keyword search actually resolve the
    constraint (find the right item WITHOUT the wrong one), or does it just
    surface both options undifferentiated - leaving the real judgment to a human?"""
    words = [w.strip(".,!?'") for w in intent.split() if len(w) > 3]
    found_correct = False
    found_distractor = False
    for word in words:
        result = search_catalog(word)
        found_correct = found_correct or f"#{expected_id} " in result
        found_distractor = found_distractor or f"#{distractor_id} " in result
    if found_correct and not found_distractor:
        return "RESOLVED"
    if found_correct and found_distractor:
        return "AMBIGUOUS (shows both, can't tell which fits)"
    return "NOT FOUND"


def _run_with_fallback(intent: str) -> bool:
    """Try each model candidate in turn - the same resilience pattern as the main
    agent - so a per-minute rate limit on one model doesn't kill the whole eval."""
    config = types.GenerateContentConfig(
        system_instruction=_EVAL_INSTRUCTION,
        tools=[search_catalog, propose_order],
    )
    for model in _MODEL_CANDIDATES:
        try:
            chat = _client.chats.create(model=model, config=config)
            chat.send_message(intent)
            return True
        except Exception as e:
            if any(marker in str(e) for marker in ("RESOURCE_EXHAUSTED", "NOT_FOUND", "429", "404")):
                print(f"  ({model} unavailable right now, trying next model...)")
                continue
            raise
    return False


def agent_selects_correct(intent: str, expected_id: int) -> bool:
    """Runs the real conversational agent and checks which product it actually drafted."""
    conn = get_connection()
    before_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM orders").fetchone()[0]
    conn.close()

    if not _run_with_fallback(intent):
        print("  (all models unavailable for this case)")
        return False

    conn = get_connection()
    order = conn.execute(
        "SELECT product_id FROM orders WHERE id > ? ORDER BY id DESC LIMIT 1", (before_id,)
    ).fetchone()
    conn.close()
    return order is not None and order["product_id"] == expected_id


def main():
    baseline_correct = 0
    agent_correct = 0
    print(f"{'Intent':<55} {'Baseline':<10} {'Agent':<10}")
    for intent, expected_id in CASES:
        b_ok = baseline_finds_correct(intent, expected_id)
        a_ok = agent_selects_correct(intent, expected_id)
        baseline_correct += b_ok
        agent_correct += a_ok
        print(f"{intent:<55} {'PASS' if b_ok else 'FAIL':<10} {'PASS' if a_ok else 'FAIL':<10}")
        time.sleep(8)  # stay under the free-tier per-minute rate limit

    n = len(CASES)
    print(f"\nBaseline (raw keyword search surfaces correct product): {baseline_correct}/{n}")
    print(f"Agent (autonomously drafts the correct product):        {agent_correct}/{n}")

    print("\n--- Constraint cases (budget / price comparison) ---")
    for intent, expected_id, distractor_id in CONSTRAINT_CASES:
        baseline_result = baseline_resolves_constraint(intent, expected_id, distractor_id)
        a_ok = agent_selects_correct(intent, expected_id)
        print(f"{intent}")
        print(f"  Baseline: {baseline_result}")
        print(f"  Agent:    {'PASS - picked the right item' if a_ok else 'FAIL'}")
        time.sleep(8)


if __name__ == "__main__":
    main()
