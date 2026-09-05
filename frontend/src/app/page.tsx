"use client";

import { useEffect, useRef, useState } from "react";
import {
  confirmOrder,
  getAuditLog,
  reportPaymentFailure,
  sendChatMessage,
  verifyPayment,
  type AuditLogEntry,
  type PendingOrder,
} from "@/lib/api";
import { openRazorpayCheckout } from "@/lib/razorpay";

type Message = {
  role: "user" | "assistant";
  content: string;
  pendingOrder?: PendingOrder | null;
  resolutionText?: string;
};

function badgeStyle(action: string): string {
  if (action.includes("blocked") || action.includes("failed")) return "bg-rose-600 text-white";
  if (action.includes("created") || action.includes("verified")) return "bg-emerald-600 text-white";
  return "bg-slate-600 text-white";
}

function entryStyle(action: string): string {
  if (action.includes("blocked") || action.includes("failed")) return "border-rose-200 bg-rose-50";
  if (action.includes("created") || action.includes("verified")) return "border-emerald-200 bg-emerald-50";
  return "border-slate-200 bg-slate-50";
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Hi! I can help you find products and check out. What are you looking for today?",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [payingOrderId, setPayingOrderId] = useState<number | null>(null);
  const [auditLog, setAuditLog] = useState<AuditLogEntry[]>([]);
  const sessionId = useRef(crypto.randomUUID()).current;

  async function refreshAuditLog() {
    try {
      setAuditLog(await getAuditLog());
    } catch {
      // non-critical - panel just stays stale until the next successful refresh
    }
  }

  useEffect(() => {
    refreshAuditLog();
  }, []);

  async function handleSend() {
    const text = input.trim();
    if (!text || loading) return;
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setLoading(true);
    try {
      const data = await sendChatMessage(sessionId, text);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.reply, pendingOrder: data.pending_order },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Something went wrong reaching the assistant. Please try again." },
      ]);
    } finally {
      setLoading(false);
      refreshAuditLog();
    }
  }

  function setResolution(msgIndex: number, text: string) {
    // First message wins - a later ondismiss shouldn't overwrite an already-reported failure
    setMessages((prev) =>
      prev.map((m, i) => (i === msgIndex && !m.resolutionText ? { ...m, resolutionText: text } : m))
    );
  }

  async function handlePay(msgIndex: number, order: PendingOrder) {
    setPayingOrderId(order.order_id);
    try {
      const confirmed = await confirmOrder(order.order_id);
      refreshAuditLog();
      await openRazorpayCheckout(
        {
          key: confirmed.key_id,
          amount: confirmed.amount_paise,
          currency: confirmed.currency,
          name: "Campus Tech Essentials",
          description: `${order.quantity}x ${order.product_name}`,
          order_id: confirmed.razorpay_order_id,
          handler: async (response) => {
            try {
              await verifyPayment(order.order_id, response.razorpay_payment_id, response.razorpay_signature);
              setResolution(msgIndex, "Payment verified - thank you!");
            } catch {
              setResolution(msgIndex, "Payment could not be verified. No charge was confirmed.");
            } finally {
              refreshAuditLog();
            }
          },
          modal: {
            ondismiss: () => setResolution(msgIndex, "Checkout closed - order not paid."),
          },
        },
        (failure) => {
          setResolution(msgIndex, "Payment failed. You can ask to try again.");
          reportPaymentFailure(order.order_id, failure.error?.description || "Payment declined").finally(
            refreshAuditLog
          );
        }
      );
    } catch (err) {
      setResolution(msgIndex, err instanceof Error ? err.message : "Could not start checkout.");
      refreshAuditLog();
    } finally {
      setPayingOrderId(null);
    }
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-gradient-to-br from-slate-100 via-indigo-50 to-slate-100">
      <header className="shrink-0 bg-slate-900 px-6 py-4 shadow-md">
        <h1 className="text-xl font-bold text-white">Campus Tech Essentials</h1>
        <p className="text-sm text-indigo-200">AI shopping assistant - agentic commerce, live</p>
      </header>

      <div className="flex min-h-0 flex-1 justify-center gap-4 p-6">
        <main className="flex min-h-0 w-full max-w-2xl flex-col rounded-2xl border border-slate-200 bg-white shadow-xl">
          <div className="flex-1 space-y-3 overflow-y-auto p-5">
            {messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
                <span
                  className={
                    "inline-block max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm shadow-sm " +
                    (m.role === "user"
                      ? "bg-indigo-600 text-white"
                      : "border border-indigo-100 bg-indigo-50 text-slate-800")
                  }
                >
                  {m.content}
                </span>
                {m.pendingOrder && !m.resolutionText && (
                  <div className="mt-2">
                    <button
                      className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50"
                      onClick={() => handlePay(i, m.pendingOrder!)}
                      disabled={payingOrderId === m.pendingOrder.order_id}
                    >
                      {payingOrderId === m.pendingOrder.order_id
                        ? "Processing..."
                        : `Confirm & Pay Rs.${(m.pendingOrder.amount_paise / 100).toFixed(2)}`}
                    </button>
                  </div>
                )}
                {m.resolutionText && (
                  <div className="mt-1 text-xs font-semibold text-slate-500">{m.resolutionText}</div>
                )}
              </div>
            ))}
            {loading && <div className="text-sm font-medium text-indigo-400">Thinking...</div>}
          </div>

          <div className="flex gap-2 rounded-b-2xl border-t border-slate-200 bg-slate-50 p-4">
            <input
              className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
              placeholder="e.g. do you have anything for charging my phone?"
            />
            <button
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-50"
              onClick={handleSend}
              disabled={loading}
            >
              Send
            </button>
          </div>
        </main>

        <aside className="flex min-h-0 w-full max-w-sm flex-col rounded-2xl border border-slate-200 bg-white shadow-xl">
          <header className="flex items-center justify-between rounded-t-2xl bg-slate-900 px-4 py-4">
            <div>
              <h2 className="text-sm font-bold text-white">Audit Trail</h2>
              <p className="text-xs text-indigo-200">Every money action, logged</p>
            </div>
            <button
              className="rounded-md border border-slate-600 px-2 py-1 text-xs font-medium text-white hover:bg-slate-800"
              onClick={refreshAuditLog}
            >
              Refresh
            </button>
          </header>
          <div className="flex-1 space-y-2 overflow-y-auto p-3">
            {auditLog.length === 0 && <p className="text-xs text-slate-400">No actions logged yet.</p>}
            {auditLog.map((entry) => (
              <div key={entry.id} className={"rounded-lg border p-2.5 " + entryStyle(entry.action)}>
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={
                      "rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide " +
                      badgeStyle(entry.action)
                    }
                  >
                    {entry.action}
                  </span>
                  <span className="whitespace-nowrap text-[10px] font-medium text-slate-400">{entry.timestamp}</span>
                </div>
                <p className="mt-1.5 text-xs font-medium text-slate-700">{entry.details}</p>
                {entry.order_id !== null && (
                  <p className="mt-0.5 text-[10px] text-slate-400">
                    order #{entry.order_id} · by {entry.actor}
                  </p>
                )}
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}



