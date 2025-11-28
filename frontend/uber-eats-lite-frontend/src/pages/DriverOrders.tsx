import { useEffect, useState } from "react";
import api from "../api/api";

interface DeliveredOrder {
  id: string;         
  driver_id: string;
  status: string;
  created_at: string;
}

export default function DriverOrders() {
  const [orders, setOrders] = useState<DeliveredOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchDeliveredOrders = async () => {
      try {
        console.log(`Fetching delivered orders from: /drivers/deliveries/history`);
        const res = await api.get(`/drivers/deliveries/history`);

        // Map backend response to match DeliveredOrder interface
        const mappedOrders: DeliveredOrder[] = res.data.map((o: any) => ({
          id: o.order_id,
          driver_id: o.driver_id,
          status: o.status,
          created_at: o.created_at,
        }));

        setOrders(mappedOrders);
      } catch (err: any) {
        console.error("Failed to fetch delivered orders:", err);
        setError(err.response?.data?.detail || err.message || "Unknown error");
      } finally {
        setLoading(false);
      }
    };

    fetchDeliveredOrders();
  }, []);

  if (loading) return <p>Loading delivered orders...</p>;
  if (error) return <p className="text-red-600">Error: {error}</p>;
  if (orders.length === 0) return <p>No delivered orders yet.</p>;

  return (
    <div>
      <h1>🚚 Delivered Orders</h1>
      <ul>
        {orders.map((order) => (
          <li key={order.id}>
            <strong>Order #{order.id}</strong> - {order.status} - {new Date(order.created_at).toLocaleString()}
          </li>
        ))}
      </ul>
    </div>
  );
}
