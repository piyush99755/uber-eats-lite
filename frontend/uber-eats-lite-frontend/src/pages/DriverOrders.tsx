import { useEffect, useState } from "react";
import api from "../api/api";

export default function DriverOrders() {
  const [orders, setOrders] = useState([]);

  useEffect(() => {
    api.get("/drivers/my-orders").then((res) => {
      setOrders(res.data);
    });
  }, []);

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">My Delivered Orders</h2>

      <ul>
        {orders.map((o: any) => (
          <li key={o.id} className="p-3 border rounded mb-2">
            <p><strong>Order ID:</strong> {o.id}</p>
            <p><strong>Delivered At:</strong> {o.delivered_at}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
