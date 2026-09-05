import contextvars
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.database import get_connection, log_audit
from app.payments import SPEND_CAP_PAISE

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")))

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Set by propose_order during a tool call, read back by run_chat once the model
# finishes responding - lets the frontend know an order needs payment without
# the LLM having to format that data itself.
_pending_order = contextvars.ContextVar("_pending_order", default=None)

# Tried in order - if one is rate-limited or deprecated, we fall back to the
# next rather than failing the whole conversation.
_MODEL_CANDIDATES = ["gemini-3.5-flash-lite", "gemini-2.0-flash", "gemini-2.5-flash"]
_model_index = 0

_SYSTEM_INSTRUCTION = (
    "You are a friendly shopping assistant for a campus tech essentials store. "
    "Use the search_catalog tool to find real products before recommending anything - "
    "never invent products or prices. Quote prices in rupees. Be concise. "
    "When the customer wants to buy something, call propose_order - this only drafts "
    "the order, it never charges money. The customer always pays through the checkout "
    "screen, never through this chat."
)

# session_id -> Chat object. In-memory only: fine for a single-process demo,
# resets on server restart.
_sessions = {}


def search_catalog(query: str) -> str:
    """Search the store's product catalog by keyword (matches name, description, or category).

    Args:
        query: Keyword to search for, e.g. "charger" or "audio".
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, description, price_paise, category, stock FROM products "
        "WHERE name LIKE ? OR description LIKE ? OR category LIKE ?",
        (f"%{query}%", f"%{query}%", f"%{query}%"),
    ).fetchall()
    conn.close()
    log_audit(actor="agent", action="tool_call:search_catalog", details=query)
    if not rows:
        return "No matching products found."
    return "\n".join(
        f"#{r['id']} {r['name']} - Rs.{r['price_paise'] / 100:.2f} ({r['stock']} in stock): {r['description']}"
        for r in rows
    )


def propose_order(product_id: int, quantity: int) -> str:
    """Draft an order for the customer to review. This never charges any money -
    it only creates a pending order that the customer must explicitly confirm and
    pay for on the checkout screen.

    Args:
        product_id: The id of the product, from search_catalog results.
        quantity: How many units the customer wants.
    """
    conn = get_connection()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        conn.close()
        return f"No product with id {product_id} exists."
    if quantity < 1 or quantity > product["stock"]:
        conn.close()
        return f"Cannot propose that quantity - only {product['stock']} in stock."

    amount_paise = product["price_paise"] * quantity
    cursor = conn.execute(
        "INSERT INTO orders (product_id, quantity, amount_paise, status) VALUES (?, ?, ?, 'pending_confirmation')",
        (product_id, quantity, amount_paise),
    )
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()

    over_cap = amount_paise > SPEND_CAP_PAISE
    log_audit(
        actor="agent",
        action="propose_order",
        details=f"order#{order_id}: {quantity}x {product['name']} = Rs.{amount_paise / 100:.2f}"
        + (" [EXCEEDS spend cap]" if over_cap else ""),
        order_id=order_id,
    )
    _pending_order.set(
        {
            "order_id": order_id,
            "amount_paise": amount_paise,
            "product_name": product["name"],
            "quantity": quantity,
        }
    )
    cap_note = (
        f" Note: this exceeds the Rs.{SPEND_CAP_PAISE / 100:.0f} auto-approval limit, "
        "so checkout will require extra confirmation."
        if over_cap
        else ""
    )
    return (
        f"Order #{order_id} drafted: {quantity}x {product['name']} = Rs.{amount_paise / 100:.2f}. "
        f"Please confirm on the checkout screen to pay.{cap_note}"
    )


def _create_chat(model: str):
    return _client.chats.create(
        model=model,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            tools=[search_catalog, propose_order],
        ),
    )


def get_chat(session_id: str):
    if session_id not in _sessions:
        _sessions[session_id] = _create_chat(_MODEL_CANDIDATES[_model_index])
    return _sessions[session_id]


def run_chat(session_id: str, message: str) -> dict:
    global _model_index
    _pending_order.set(None)
    while _model_index < len(_MODEL_CANDIDATES):
        try:
            chat = get_chat(session_id)
            response = chat.send_message(message)
            return {"reply": response.text, "pending_order": _pending_order.get()}
        except Exception as e:
            if any(marker in str(e) for marker in ("RESOURCE_EXHAUSTED", "NOT_FOUND", "429", "404")):
                _model_index += 1
                _sessions.pop(session_id, None)
                next_model = _MODEL_CANDIDATES[_model_index] if _model_index < len(_MODEL_CANDIDATES) else "none left"
                log_audit(actor="system", action="model_fallback", details=f"switched to {next_model}")
                continue
            raise
    return {"reply": "The assistant is temporarily unavailable - please try again shortly.", "pending_order": None}
