import { useEffect, useState } from "react";
import api from "../api/api";

export default function DriverOrders() {
  const [orders, setOrders] = useState<any[]>([]);

  useEffect(() => {
    api.get("/drivers/deliveries/history").then((res) => {
      setOrders(res.data);
    });
  }, []);

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">My Delivered Orders</h2>

      {orders.length === 0 ? (
        <p>No delivered orders yet.</p>
      ) : (
        <ul>
          {orders.map((o) => (
            <li key={o.id} className="p-3 border rounded mb-2">
              <p><strong>Order ID:</strong> {o.order_id}</p>
              <p><strong>Delivered At:</strong> {o.delivered_at}</p>
              <p><strong>Items:</strong> {o.items?.join(", ") || "N/A"}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
