// Payments.tsx
import { useEffect, useState } from "react";
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
  const fetchPayments = async () => {
    if (!token) {
      toast.error("You must be logged in to view payments.");
      setLoading(false);
      return;
    }

    setLoading(true);
    setError("");

    try {
      const res = await api.get<Payment[]>("/payments/list", {
        headers: { Authorization: `Bearer ${token}` },
      });
      const list = Array.isArray(res.data) ? res.data.reverse() : [];
      setPayments(list);
    } catch (err: any) {
      console.error("[Payments] Fetch failed:", err);
      const msg = err.response?.data?.error || err.message || "Unknown error";
      setError(msg);
      toast.error(`Failed to load payments: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  /** 💳 Simulate payment */
  const handleSimulatedPayment = async (orderId: string, amount: number) => {
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

      toast.success(`✅ Payment completed for order ${orderId}`);
      await fetchPayments();
    } catch (err: any) {
      console.error("[Payments] Manual payment failed:", err);
      const msg = err.response?.data?.error || "Manual payment failed";
      toast.error(msg);
    }
  };

  useEffect(() => {
    fetchPayments();
  }, []);

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <ToastContainer position="top-right" />
      <h1 className="text-3xl font-bold mb-6 text-center">💳 Payments</h1>

      {loading ? (
        <p className="text-gray-500 text-center mt-10">Loading payments...</p>
      ) : error ? (
        <div className="text-center mt-10">
          <p className="text-red-500 mb-3">⚠️ {error}</p>
          <Button onClick={fetchPayments}>Retry</Button>
        </div>
      ) : payments.length === 0 ? (
        <p className="text-gray-500 text-center mt-10">No payments found.</p>
      ) : (
        <div className="space-y-4">
          {payments.map((payment) => (
            <div
              key={payment.id}
              className="border rounded-lg p-4 bg-white shadow flex flex-col sm:flex-row justify-between sm:items-center"
            >
              <div className="text-left">
                <p>
                  <strong>Order:</strong> {payment.order_id}
                </p>
                <p>
                  <strong>Amount:</strong> ${payment.amount.toFixed(2)}
                </p>
                <p>
                  <strong>Status:</strong>{" "}
                  <span
                    className={`font-semibold ${
                      payment.status === "paid"
                        ? "text-green-600"
                        : payment.status === "pending"
                        ? "text-yellow-600"
                        : "text-red-600"
                    }`}
                  >
                    {payment.status}
                  </span>
                </p>
              </div>

              {payment.status !== "paid" && (
                <Button
                  className="mt-3 sm:mt-0"
                  onClick={() =>
                    handleSimulatedPayment(payment.order_id, payment.amount)
                  }
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
