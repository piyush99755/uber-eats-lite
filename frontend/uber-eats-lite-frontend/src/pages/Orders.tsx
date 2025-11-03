import { useEffect, useState } from "react";
import api from "../api/api";
import { Button } from "../components/Button";
import { Modal } from "../components/Modal";

interface Order {
  id: string;
  user_id: string;
  items: string;
  total: number;
  status: string;
}

export default function Orders() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [loading, setLoading] = useState(false);

  const [form, setForm] = useState({
    user_id: "",
    items: "",
    total: "",
  });

  const fetchOrders = async () => {
    try {
      const res = await api.get<Order[]>("/orders/orders");
      setOrders(res.data);
      setError("");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    }
  };

  useEffect(() => {
    fetchOrders();
  }, []);

  const handleCreateOrder = async () => {
    if (!form.user_id || !form.items || !form.total) {
      alert("Please fill all fields");
      return;
    }

    setLoading(true);
    try {
      await api.post("/orders/orders", {
        user_id: form.user_id,
        items: form.items,
        total: parseFloat(form.total),
      });
      await fetchOrders();
      setShowModal(false);
      setForm({ user_id: "", items: "", total: "" });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      alert("Failed to create order: " + message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">🧾 Orders</h1>
        <Button onClick={() => setShowModal(true)}>➕ Create Order</Button>
      </div>

      {error && <p className="text-red-500 mb-4">Error: {error}</p>}

      <div className="grid gap-3">
        {orders.length ? (
          orders.map((order) => (
            <div key={order.id} className="border rounded-lg p-4 bg-white shadow">
              <p><strong>Status:</strong> {order.status}</p>
              <p><strong>Total:</strong> ${order.total}</p>
              <p className="text-sm text-gray-500"><strong>User ID:</strong> {order.user_id}</p>
            </div>
          ))
        ) : (
          <p>No orders found</p>
        )}
      </div>

      {/* Modal */}
      <Modal show={showModal} onClose={() => setShowModal(false)} title="Create New Order">
        <input
          type="text"
          placeholder="User ID"
          value={form.user_id}
          onChange={(e) => setForm({ ...form, user_id: e.target.value })}
          className="border p-2 w-full mb-3 rounded"
        />
        <input
          type="text"
          placeholder="Items (comma separated)"
          value={form.items}
          onChange={(e) => setForm({ ...form, items: e.target.value })}
          className="border p-2 w-full mb-3 rounded"
        />
        <input
          type="number"
          placeholder="Total"
          value={form.total}
          onChange={(e) => setForm({ ...form, total: e.target.value })}
          className="border p-2 w-full mb-4 rounded"
        />
        <Button onClick={handleCreateOrder} loading={loading} className="w-full">
          Create Order
        </Button>
      </Modal>
    </div>
  );
}
