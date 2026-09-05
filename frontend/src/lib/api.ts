const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type PendingOrder = {
  order_id: number;
  amount_paise: number;
  product_name: string;
  quantity: number;
};

export async function sendChatMessage(
  sessionId: string,
  message: string
): Promise<{ reply: string; pending_order: PendingOrder | null }> {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!res.ok) {
    throw new Error(`Chat request failed: ${res.status}`);
  }
  return res.json();
}

export async function confirmOrder(orderId: number): Promise<{
  razorpay_order_id: string;
  amount_paise: number;
  currency: string;
  key_id: string;
}> {
  const res = await fetch(`${API_URL}/api/orders/${orderId}/confirm`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail ?? `Confirm failed: ${res.status}`);
  }
  return data;
}

export async function reportPaymentFailure(orderId: number, reason: string): Promise<void> {
  await fetch(`${API_URL}/api/orders/${orderId}/payment-failed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export type AuditLogEntry = {
  id: number;
  timestamp: string;
  actor: string;
  action: string;
  details: string;
  order_id: number | null;
};

export async function getAuditLog(): Promise<AuditLogEntry[]> {
  const res = await fetch(`${API_URL}/api/audit-log`);
  if (!res.ok) {
    throw new Error(`Audit log request failed: ${res.status}`);
  }
  return res.json();
}

export async function verifyPayment(
  orderId: number,
  paymentId: string,
  signature: string
): Promise<{ status: string }> {
  const res = await fetch(`${API_URL}/api/orders/${orderId}/verify-payment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ razorpay_payment_id: paymentId, razorpay_signature: signature }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail ?? `Verify failed: ${res.status}`);
  }
  return data;
}
