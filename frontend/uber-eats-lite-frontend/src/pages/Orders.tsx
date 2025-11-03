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
      // Reverse for newest-first
      const sorted = [...res.data].reverse();
      setOrders(sorted);
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
  // Handle menu toggle
  // --------------------------
  const toggleItem = (itemName: string) => {
    setSelectedItems((prev) =>
      prev.includes(itemName)
        ? prev.filter((i) => i !== itemName)
        : [...prev, itemName]
    );
  };

  const total = MENU_ITEMS.filter((i) => selectedItems.includes(i.name))
    .reduce((sum, i) => sum + i.price, 0);

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
      const res = await api.post<Order>("/orders/orders", {
        user_id: userId,
        items: selectedItems,
        total,
      });

      // Add new order to top
      setOrders((prev) => [res.data, ...prev]);

      // Reset form
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
  // Render UI
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
            const itemList =
              typeof order.items === "string"
                ? (() => {
                    try {
                      const parsed = JSON.parse(order.items);
                      return Array.isArray(parsed) ? parsed : [order.items];
                    } catch {
                      return [order.items];
                    }
                  })()
                : order.items;

            return (
              <div
                key={order.id}
                className="border rounded-lg p-4 bg-white shadow"
              >
                <p>
                  <strong>User:</strong> {order.user_id}
                </p>
                <p>
                  <strong>Items:</strong> {itemList.join(", ")}
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
              </div>
            );
          })
        ) : (
          <p>No orders found</p>
        )}
      </div>

      {/* Modal */}
      <Modal
        show={showModal}
        onClose={() => setShowModal(false)}
        title="Create New Order"
      >
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
              onClick={() => toggleItem(item.name)}
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

        <p className="mb-3 font-semibold">Total: ${total.toFixed(2)}</p>

        <Button
          onClick={handleCreateOrder}
          loading={loading}
          className="w-full"
        >
          Create Order
        </Button>
      </Modal>
    </div>
  );
}
