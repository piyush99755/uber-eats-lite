import { useEffect, useState } from "react";
import api from "../api/api";
import { Button } from "../components/Button";
import { Modal } from "../components/Modal";
import { ToastContainer, toast } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

interface Order {
  id: string;
  user_id: string;
  items: string[];
  total?: number;
  status?: "pending" | "paid" | "completed" | "delivered";
  driver_id?: string;
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
  const [drivers, setDrivers] = useState<{ id: string; name: string }[]>([]);
  const [error, setError] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [loading, setLoading] = useState(false);

  const [form, setForm] = useState({
    user_id: "",
    items: [] as string[],
    driver_id: "",
    status: "pending" as Order["status"],
  });

  const [editingId, setEditingId] = useState<string | null>(null);

  // --- Fetch orders and drivers ---
  const fetchOrders = async () => {
    try {
      const res = await api.get<Order[]>("/orders/orders");
      setOrders([...res.data].reverse());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch orders");
      toast.error("Failed to fetch orders");
    }
  };

  const fetchDrivers = async () => {
    try {
      const res = await api.get<{ id: string; name: string }[]>("/drivers/drivers");
      setDrivers(res.data);
    } catch {
      toast.error("Failed to fetch drivers");
    }
  };

  useEffect(() => {
    fetchOrders();
    fetchDrivers();
  }, []);

  // --- Open modal for editing ---
  const handleEdit = (order: Order) => {
    setForm({
      user_id: order.user_id,
      items: order.items,
      driver_id: order.driver_id || "",
      status: order.status || "pending",
    });
    setEditingId(order.id);
    setShowModal(true);
  };

  // --- Create or update order ---
  const handleSubmit = async () => {
    if (!form.user_id || form.items.length === 0) {
      toast.error("Please provide user ID and select items");
      return;
    }

    setLoading(true);
    const total = MENU_ITEMS.filter((i) => form.items.includes(i.name))
      .reduce((sum, i) => sum + i.price, 0);

    try {
      if (editingId) {
        // Update order
        const res = await api.put<Order>(`/orders/orders/${editingId}`, {
          ...form,
          total,
        });
        setOrders((prev) =>
          prev.map((o) => (o.id === editingId ? res.data : o))
        );
        toast.success("Order updated successfully");
      } else {
        // Create new order
        const res = await api.post<Order>("/orders/orders", {
          ...form,
          total,
        });
        setOrders((prev) => [res.data, ...prev]);
        toast.success("Order created successfully");
      }
      setShowModal(false);
      setForm({ user_id: "", items: [], driver_id: "", status: "pending" });
      setEditingId(null);
    } catch {
      toast.error(editingId ? "Failed to update order" : "Failed to create order");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this order?")) return;
    try {
      await api.delete(`/orders/orders/${id}`);
      setOrders((prev) => prev.filter((o) => o.id !== id));
      toast.success("Order deleted successfully");
    } catch {
      toast.error("Failed to delete order");
    }
  };

  return (
    <div className="p-6">
      <ToastContainer position="top-right" />
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">🧾 Orders</h1>
        <Button
          onClick={() => {
            setEditingId(null);
            setForm({ user_id: "", items: [], driver_id: "", status: "pending" });
            setShowModal(true);
          }}
        >
          ➕ Create Order
        </Button>
      </div>

      {error && <p className="text-red-500 mb-4">Error: {error}</p>}

      <div className="grid gap-3">
        {orders.length ? (
          orders.map((order, i) => (
            <div key={order.id || i} className="border rounded-lg p-4 bg-white shadow">
              <p><strong>User:</strong> {order.user_id}</p>
              <p><strong>Items:</strong> {order.items.join(", ")}</p>
              <p><strong>Total:</strong> ${Number(order.total ?? 0).toFixed(2)}</p>
              <p>
                <strong>Status:</strong>{" "}
                <span
                  className={`font-semibold ${
                    order.status === "pending"
                      ? "text-yellow-600"
                      : order.status === "paid"
                      ? "text-blue-600"
                      : order.status === "completed"
                      ? "text-green-600"
                      : "text-gray-500"
                  }`}
                >
                  {order.status || "unknown"}
                </span>
              </p>
              <p><strong>Driver:</strong> {order.driver_id || "Unassigned"}</p>
              <div className="flex gap-2 mt-3">
                <Button
                  onClick={() => handleEdit(order)}
                  className="bg-blue-500 hover:bg-blue-600 text-white px-3 py-1 rounded"
                >
                  ✏️ Edit
                </Button>
                <Button
                  onClick={() => handleDelete(order.id)}
                  className="bg-red-500 hover:bg-red-600 text-white px-3 py-1 rounded"
                >
                  🗑 Delete
                </Button>
              </div>
            </div>
          ))
        ) : (
          <p>No orders found</p>
        )}
      </div>

      <Modal show={showModal} onClose={() => setShowModal(false)} title={editingId ? "Edit Order" : "Create New Order"}>
        <input
          type="text"
          placeholder="User ID"
          value={form.user_id}
          onChange={(e) => setForm({ ...form, user_id: e.target.value })}
          className="border p-2 w-full mb-3 rounded"
        />
        <div className="grid grid-cols-2 gap-2 mb-3">
          {MENU_ITEMS.map((item) => (
            <button
              key={item.name}
              onClick={() =>
                setForm((prev) => ({
                  ...prev,
                  items: prev.items.includes(item.name)
                    ? prev.items.filter((i) => i !== item.name)
                    : [...prev.items, item.name],
                }))
              }
              className={`border rounded p-2 text-sm ${
                form.items.includes(item.name) ? "bg-green-500 text-white" : "bg-gray-100"
              }`}
            >
              {item.name} – ${item.price}
            </button>
          ))}
        </div>
        <select
          value={form.driver_id}
          onChange={(e) => setForm({ ...form, driver_id: e.target.value })}
          className="border p-2 w-full mb-3 rounded"
        >
          <option value="">Assign Driver (optional)</option>
          {drivers.map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
        <select
          value={form.status}
          onChange={(e) => setForm({ ...form, status: e.target.value as Order["status"] })}
          className="border p-2 w-full mb-4 rounded"
        >
          <option value="pending">Pending</option>
          <option value="paid">Paid</option>
          <option value="completed">Completed</option>
          <option value="delivered">Delivered</option>
        </select>
        <Button onClick={handleSubmit} loading={loading} className="w-full">
          {editingId ? "Update Order" : "Create Order"}
        </Button>
      </Modal>
    </div>
  );
}
