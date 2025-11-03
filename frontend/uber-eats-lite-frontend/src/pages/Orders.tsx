import { useEffect, useState } from "react";
import api from "../api/api";
import { Button } from "../components/Button";
import { Modal } from "../components/Modal";

interface Order {
  id: string;
  user_id: string;
  items: string | string[];
  total: number;
  status: string;
}

// TEMP MENU — will be replaced by dynamic API later
const MENU_ITEMS = [
  { name: "Burger", price: 8 },
  { name: "Fries", price: 4 },
  { name: "Coke", price: 3 },
  { name: "Pizza", price: 12 },
  { name: "Salad", price: 6 },
];

export default function Orders() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [selectedItems, setSelectedItems] = useState<string[]>([]);
  const [userId, setUserId] = useState("");
  const [loading, setLoading] = useState(false);

  // --------------------------
  // Fetch all orders
  // --------------------------
  const fetchOrders = async () => {
    try {
      const res = await api.get<Order[]>("/orders/orders");
      setOrders([...res.data].reverse()); // newest-first
      setError("");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to fetch orders";
      console.error(e);
      setError(message);
    }
  };

  useEffect(() => {
    fetchOrders();
  }, []);

  // --------------------------
  // Create new order
  // --------------------------
  const handleCreateOrder = async () => {
    if (!userId || selectedItems.length === 0) {
      alert("Please provide user ID and select at least one item");
      return;
    }

    setLoading(true);
    try {
      const total = MENU_ITEMS.filter((i) => selectedItems.includes(i.name))
        .reduce((sum, i) => sum + i.price, 0);

      const res = await api.post<Order>("/orders/orders", {
        user_id: userId,
        items: selectedItems,
        total,
      });

      setOrders((prev) => [res.data, ...prev]);
      setShowModal(false);
      setUserId("");
      setSelectedItems([]);
    } catch (err) {
      console.error(err);
      alert("Failed to create order");
    } finally {
      setLoading(false);
    }
  };

  // --------------------------
  // Delete order
  // --------------------------
  const handleDeleteOrder = async (id: string) => {
    if (!confirm("Are you sure you want to delete this order?")) return;
    try {
      await api.delete(`/orders/orders/${id}`);
      setOrders((prev) => prev.filter((o) => o.id !== id));
    } catch (err) {
      console.error(err);
      alert("Failed to delete order");
    }
  };

  // --------------------------
  // Render
  // --------------------------
  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">🧾 Orders</h1>
        <Button onClick={() => setShowModal(true)}>➕ Create Order</Button>
      </div>

      {error && <p className="text-red-500 mb-4">Error: {error}</p>}

      <div className="grid gap-3">
        {orders.length ? (
          orders.map((order) => {
            const items = Array.isArray(order.items)
              ? order.items
              : (() => {
                  try {
                    const parsed = JSON.parse(order.items);
                    return Array.isArray(parsed) ? parsed : [order.items];
                  } catch {
                    return [order.items];
                  }
                })();

            return (
              <div key={order.id} className="border rounded-lg p-4 bg-white shadow">
                <p>
                  <strong>User:</strong> {order.user_id}
                </p>
                <p>
                  <strong>Items:</strong> {items.join(", ")}
                </p>
                <p>
                  <strong>Total:</strong> ${order.total.toFixed(2)}
                </p>
                <p>
                  <strong>Status:</strong>{" "}
                  <span
                    className={`font-semibold ${
                      order.status === "pending"
                        ? "text-yellow-600"
                        : "text-green-600"
                    }`}
                  >
                    {order.status}
                  </span>
                </p>
                <Button
                  onClick={() => handleDeleteOrder(order.id)}
                  className="bg-red-500 hover:bg-red-600 text-white px-3 py-1 mt-3 rounded"
                >
                  🗑 Delete
                </Button>
              </div>
            );
          })
        ) : (
          <p>No orders found</p>
        )}
      </div>

      {/* Modal */}
      <Modal show={showModal} onClose={() => setShowModal(false)} title="Create New Order">
        <input
          type="text"
          placeholder="User ID"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          className="border p-2 w-full mb-4 rounded"
        />

        <div className="grid grid-cols-2 gap-2 mb-4">
          {MENU_ITEMS.map((item) => (
            <button
              key={item.name}
              onClick={() =>
                setSelectedItems((prev) =>
                  prev.includes(item.name)
                    ? prev.filter((i) => i !== item.name)
                    : [...prev, item.name]
                )
              }
              className={`border rounded p-2 text-sm ${
                selectedItems.includes(item.name)
                  ? "bg-green-500 text-white"
                  : "bg-gray-100"
              }`}
            >
              {item.name} – ${item.price}
            </button>
          ))}
        </div>

        <Button onClick={handleCreateOrder} loading={loading} className="w-full">
          Create Order
        </Button>
      </Modal>
    </div>
  );
}
