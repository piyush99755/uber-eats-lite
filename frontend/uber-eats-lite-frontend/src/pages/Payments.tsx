import { useEffect, useState } from "react";
import api from "../api/api";

interface Payment {
  id: string;
  order_id: string;
  amount: number;
  status: string;
}

export default function Payments() {
  const [payments, setPayments] = useState<Payment[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<Payment[]>("/payments/payments")
      .then((res) => setPayments(res.data.reverse()))
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div className="text-center mt-10">
      <h1 className="text-3xl font-bold">💳 Payments</h1>
      {error && <p className="text-red-500 mt-4">Error: {error}</p>}
      <div className="mt-6 space-y-2">
        {payments.length ? (
          payments.map((payment, i) => (
            <div key={payment.id || i} className="border rounded-lg p-3 mx-auto w-1/2">
              <p><strong>Order:</strong> {payment.order_id}</p>
              <p><strong>Amount:</strong> ${Number(payment.amount ?? 0).toFixed(2)}</p>
              <p><strong>Status:</strong> {payment.status}</p>
            </div>
          ))
        ) : (
          <p>No payments found</p>
        )}
      </div>
    </div>
  );
}
