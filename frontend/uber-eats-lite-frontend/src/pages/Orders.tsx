import { useEffect, useState } from "react";
import api from "../api/api";
import { Button } from "../components/Button";
import { Modal } from "../components/Modal";
import { ToastContainer, toast } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

export type OrderStatus = "pending" | "paid" | "assigned" | "delivered";

interface Order {
  id: string;
  user_id: string;
  items: string[];
  total: number;
  status: OrderStatus;
  driver_id?: string;
}

interface Driver {
  id: string;
  name: string;
}

interface EventLog {
  event_type: string;
  payload: any;
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
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [loading, setLoading] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState({
    user_id: "",
    items: [] as string[],
    driver_id: "",
    status: "pending" as OrderStatus,
  });

  // --- Fetch orders ---
  const fetchOrders = async () => {
    try {
      const res = await api.get<Order[]>("/orders/orders"); // API Gateway path
      setOrders([...res.data].reverse());
    } catch (err: unknown) {
      if (err instanceof Error) toast.error(err.message);
      else toast.error("Failed to fetch orders");
    }
  };

  // --- Fetch drivers ---
  const fetchDrivers = async () => {
    try {
      const res = await api.get<Driver[]>("/drivers/drivers"); // API Gateway path
      setDrivers(res.data);
    } catch {
      toast.error("Failed to fetch drivers");
    }
  };

  useEffect(() => {
    fetchOrders();
    fetchDrivers();
  }, []);

  // --- Event polling ---
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await api.get<EventLog[]>("/orders/events?limit=20");
        res.data.forEach((ev) => {
          const { event_type, payload } = ev;
          if (!payload?.order_id) return;

          setOrders((prev) =>
            prev.map((order) => {
              if (order.id !== payload.order_id) return order;
              switch (event_type) {
                case "payment.processed":
                  toast.success(`Payment received for order ${order.id}`);
                  return { ...order, status: "paid" };
                case "driver.assigned":
                  toast.info(`Driver assigned for order ${order.id}`);
                  return { ...order, status: "assigned", driver_id: payload.driver_id };
                case "order.delivered":
                  toast.success(`Order ${order.id} delivered`);
                  return { ...order, status: "delivered" };
                default:
                  return order;
              }
            })
          );
        });
      } catch (err) {
        console.error("Event polling error", err);
      }
    }, 3000);

    return () => clearInterval(interval);
  }, []);

  // --- Edit order ---
  const handleEdit = (order: Order) => {
    setForm({
      user_id: order.user_id,
      items: order.items,
      driver_id: order.driver_id ?? "",
      status: order.status,
    });
    setEditingId(order.id);
    setShowModal(true);
  };

  // --- Pay Now ---
  const handlePayment = async (order: Order) => {
    try {
      await api.post("/payments/pay", {
        order_id: order.id,
        user_id: order.user_id,
        amount: order.total,
      });
      toast.success(`Payment initiated for order ${order.id}`);
    } catch {
      toast.error(`Payment failed for order ${order.id}`);
    }
  };

  // --- Create / Update order ---
  const handleSubmit = async () => {
    if (!form.user_id || form.items.length === 0) {
      toast.error("Please provide user ID and select items");
      return;
    }

    setLoading(true);
    const total = MENU_ITEMS.filter((i) => form.items.includes(i.name)).reduce(
      (sum, i) => sum + i.price,
      0
    );

    try {
      if (editingId) {
        const res = await api.put<Order>(`/orders/orders/${editingId}`, {
          ...form,
          total,
        });
        setOrders((prev) =>
          prev.map((o) => (o.id === editingId ? res.data : o))
        );
        toast.success("Order updated successfully");
      } else {
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

      <div className="grid gap-3">
        {orders.length === 0 ? (
          <p>No orders found</p>
        ) : (
          orders.map((order) => (
            <div key={order.id} className="border rounded-lg p-4 bg-white shadow">
              <p><strong>User:</strong> {order.user_id}</p>
              <p><strong>Items:</strong> {order.items.join(", ")}</p>
              <p><strong>Total:</strong> ${order.total.toFixed(2)}</p>
              <p>
                <strong>Status:</strong>{" "}
                <span
                  className={`font-semibold ${
                    order.status === "pending"
                      ? "text-yellow-600"
                      : order.status === "paid"
                      ? "text-blue-600"
                      : order.status === "assigned"
                      ? "text-purple-600"
                      : "text-green-600"
                  }`}
                >
                  {order.status}
                </span>
              </p>
              <p><strong>Driver:</strong> {order.driver_id ?? "Unassigned"}</p>
              <div className="flex gap-2 mt-3">
                <Button
                  onClick={() => handleEdit(order)}
                  disabled={["paid", "assigned", "delivered"].includes(order.status)}
                >
                  ✏️ Edit
                </Button>
                {order.status === "pending" && (
                  <Button onClick={() => handlePayment(order)}>💳 Pay Now</Button>
                )}
                <Button onClick={() => handleDelete(order.id)}>🗑 Delete</Button>
              </div>
            </div>
          ))
        )}
      </div>

      <Modal
        show={showModal}
        onClose={() => setShowModal(false)}
        title={editingId ? "Edit Order" : "Create New Order"}
      >
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
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
        <Button onClick={handleSubmit} loading={loading} className="w-full">
          {editingId ? "Update Order" : "Create Order"}
        </Button>
      </Modal>
    </div>
  );
}
