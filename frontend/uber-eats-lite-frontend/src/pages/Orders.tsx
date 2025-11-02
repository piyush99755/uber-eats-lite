import { useEffect, useState } from "react";
import api from "../api/api";

interface Order {
  id: string;
  user_id: string;
  total: number;
  status: string;
}

export default function Orders() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Order[]>("/orders/orders")
      .then(res => setOrders(res.data))
      .catch(err => setError(err.message));
  }, []);

  return (
    <div className="text-center mt-10">
      <h1 className="text-3xl font-bold">🧾 Orders</h1>
      {error && <p className="text-red-500 mt-4">Error: {error}</p>}
      <div className="mt-6 space-y-2">
        {orders.length ? orders.map(order => (
          <div key={order.id} className="border rounded-lg p-3 mx-auto w-1/2">
            <p><strong>Status:</strong> {order.status}</p>
            <p><strong>Total:</strong> ${order.total}</p>
          </div>
        )) : <p>No orders found</p>}
      </div>
    </div>
  );
}
