import time
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.agent import run_chat
from app.database import get_connection, init_db, log_audit
from app.payments import RAZORPAY_KEY_ID, SPEND_CAP_PAISE, create_razorpay_order, verify_payment_signature

RATE_LIMIT_MAX_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60
_rate_limit_state: dict[str, list[float]] = defaultdict(list)


def rate_limit(request: Request) -> None:
    """Simple in-memory fixed-window rate limit per client IP, applied to the
    money-moving endpoints. Not distributed/production-grade, but demonstrates
    the guardrail against a burst of automated requests hitting a single process."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    timestamps = _rate_limit_state[client_ip]
    while timestamps and timestamps[0] < window_start:
        timestamps.pop(0)
    if len(timestamps) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(status_code=429, detail="Too many requests - please slow down")
    timestamps.append(now)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AI Buildathon - Agentic Commerce", lifespan=lifespan)

# Next.js dev server needs explicit CORS allowance to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str


class VerifyPaymentRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_signature: str


class PaymentFailedRequest(BaseModel):
    reason: str


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat")
def chat(payload: ChatRequest):
    return run_chat(payload.session_id, payload.message)


@app.post("/api/orders/{order_id}/confirm", dependencies=[Depends(rate_limit)])
def confirm_order(order_id: int):
    conn = get_connection()
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")
    if order["status"] != "pending_confirmation":
        conn.close()
        raise HTTPException(status_code=400, detail=f"Order is '{order['status']}', not confirmable")

    # Deterministic re-check - never trust the agent's proposal alone for real money movement
    if order["amount_paise"] > SPEND_CAP_PAISE:
        log_audit(
            actor="system",
            action="blocked_over_cap",
            details=f"order#{order_id} amount Rs.{order['amount_paise'] / 100:.2f} exceeds cap",
            order_id=order_id,
        )
        conn.close()
        raise HTTPException(
            status_code=400,
            detail=f"Amount exceeds Rs.{SPEND_CAP_PAISE / 100:.0f} spend cap - blocked",
        )

    # Atomically claim the order before calling Razorpay - if two requests race here,
    # only one UPDATE can match 'pending_confirmation' and change rowcount to 1
    claim = conn.execute(
        "UPDATE orders SET status = 'confirming', updated_at = datetime('now') "
        "WHERE id = ? AND status = 'pending_confirmation'",
        (order_id,),
    )
    conn.commit()
    if claim.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=409, detail="Order is already being confirmed or was already processed")

    try:
        razorpay_order = create_razorpay_order(order["amount_paise"], receipt=f"order{order_id}")
    except Exception as e:
        conn.execute(
            "UPDATE orders SET status = 'pending_confirmation', updated_at = datetime('now') WHERE id = ?",
            (order_id,),
        )
        conn.commit()
        conn.close()
        log_audit(actor="system", action="razorpay_order_create_failed", details=str(e), order_id=order_id)
        raise HTTPException(status_code=502, detail="Could not reach Razorpay - please try again")

    conn.execute(
        "UPDATE orders SET razorpay_order_id = ?, status = 'created', updated_at = datetime('now') WHERE id = ?",
        (razorpay_order["id"], order_id),
    )
    conn.commit()
    conn.close()
    log_audit(actor="system", action="order_created", details=razorpay_order["id"], order_id=order_id)

    return {
        "razorpay_order_id": razorpay_order["id"],
        "amount_paise": order["amount_paise"],
        "currency": "INR",
        "key_id": RAZORPAY_KEY_ID,
    }


@app.post("/api/orders/{order_id}/verify-payment", dependencies=[Depends(rate_limit)])
def verify_payment(order_id: int, payload: VerifyPaymentRequest):
    conn = get_connection()
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None or order["razorpay_order_id"] is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found or not yet created")

    valid = verify_payment_signature(
        order["razorpay_order_id"], payload.razorpay_payment_id, payload.razorpay_signature
    )
    new_status = "paid" if valid else "failed"
    conn.execute(
        "UPDATE orders SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (new_status, order_id),
    )
    conn.commit()
    conn.close()
    log_audit(
        actor="system",
        action="payment_verified" if valid else "payment_verification_failed",
        details=payload.razorpay_payment_id,
        order_id=order_id,
    )
    if not valid:
        raise HTTPException(status_code=400, detail="Payment signature verification failed")
    return {"status": "paid"}


@app.post("/api/orders/{order_id}/payment-failed")
def payment_failed(order_id: int, payload: PaymentFailedRequest):
    conn = get_connection()
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    conn.close()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    log_audit(actor="system", action="payment_failed", details=payload.reason, order_id=order_id)
    return {"status": "logged"}


@app.get("/api/catalog")
def list_catalog():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM products").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get("/api/catalog/{product_id}")
def get_product(product_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return dict(row)


@app.get("/api/audit-log")
def get_audit_log():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]
