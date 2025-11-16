// Payments.tsx (Final Polished Version)
import { useEffect, useState, useCallback } from "react";
import api from "../api/api";
import { ToastContainer, toast } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";
import { Button } from "../components/Button";

interface Payment {
  id: string;
  order_id: string;
  amount: number;
  status: "pending" | "paid" | "failed";
}

export default function Payments() {
  const [payments, setPayments] = useState<Payment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const token = localStorage.getItem("token");

  /** 🔁 Load all payments */
  const fetchPayments = useCallback(async () => {
    if (!token) {
      setLoading(false);
      toast.error("You must be logged in to view payments.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const res = await api.get<Payment[]>("/payments/payments", {
        headers: { Authorization: `Bearer ${token}` },
      });

      const list = Array.isArray(res.data) ? res.data : [];
      setPayments([...list].reverse());
    } catch (err: any) {
      const msg = err.response?.data?.error || "Failed to load payments.";
      console.error("[Payments] Fetch error:", err);

      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [token]);

  /** 💳 Manual (simulated) payment */
  const completePayment = async (orderId: string, amount: number) => {
    if (!token) {
      toast.error("You must be logged in to make a payment.");
      return;
    }

    try {
      toast.info("Processing payment...");

      await api.post(
        "/payments/pay",
        { order_id: orderId, amount },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      toast.success(`Payment completed for order ${orderId}`);
      fetchPayments();
    } catch (err: any) {
      const msg = err.response?.data?.error || "Payment failed.";
      console.error("[Payments] Payment error:", err);
      toast.error(msg);
    }
  };

  /** Load on mount */
  useEffect(() => {
    fetchPayments();
  }, [fetchPayments]);

  const statusColor = {
    paid: "text-green-600",
    pending: "text-yellow-600",
    failed: "text-red-600",
  };

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <ToastContainer position="top-right" />
      <h1 className="text-3xl font-bold mb-6 text-center">💳 Payments</h1>

      {/* ---------------- LOADING ---------------- */}
      {loading && (
        <div className="space-y-4 mt-6">
          {[...Array(3)].map((_, i) => (
            <div
              key={i}
              className="animate-pulse bg-gray-200 h-24 rounded-lg"
            ></div>
          ))}
        </div>
      )}

      {/* ---------------- ERROR ---------------- */}
      {!loading && error && (
        <div className="text-center mt-10">
          <p className="text-red-500 mb-3">⚠️ {error}</p>
          <Button onClick={fetchPayments}>Retry</Button>
        </div>
      )}

      {/* ---------------- EMPTY ---------------- */}
      {!loading && !error && payments.length === 0 && (
        <p className="text-gray-500 text-center mt-10">No payments found.</p>
      )}

      {/* ---------------- PAYMENT LIST ---------------- */}
      {!loading && !error && payments.length > 0 && (
        <div className="space-y-4">
          {payments.map((p) => (
            <div
              key={p.id}
              className="border rounded-lg p-4 bg-white shadow flex flex-col sm:flex-row justify-between sm:items-center transition hover:shadow-md"
            >
              <div>
                <p className="font-semibold text-lg">Order #{p.order_id}</p>
                <p>
                  <strong>Amount:</strong> ${p.amount.toFixed(2)}
                </p>
                <p>
                  <strong>Status:</strong>{" "}
                  <span className={`${statusColor[p.status]} font-semibold`}>
                    {p.status}
                  </span>
                </p>
              </div>

              {p.status !== "paid" && (
                <Button
                  className="mt-3 sm:mt-0"
                  onClick={() => completePayment(p.order_id, p.amount)}
                >
                  💳 Complete Payment
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
