// src/pages/Orders.tsx
import { useEffect, useState, useMemo } from "react";
import api from "../api/api";
import { Button } from "../components/Button";
import { Modal } from "../components/Modal";
import { ToastContainer, toast } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";
import { PaymentModal } from "../components/PaymentModal";

export type OrderStatus = "pending" | "paid" | "assigned" | "delivered";

interface Order {
  id: string;
  user_id: string;
  user_name?: string; // for display
  items: string[];
  total: number;
  status: OrderStatus;
  driver_id?: string | null;
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

function getTokenPayload() {
  const t = localStorage.getItem("token");
  if (!t) return null;
  try {
    return JSON.parse(atob(t.split(".")[1]));
  } catch {
    return null;
  }
}

export default function Orders() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [showPaymentModal, setShowPaymentModal] = useState(false);
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);
  const [loading, setLoading] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState({
    user_id: "",
    items: [] as string[],
    driver_id: "",
    status: "pending" as OrderStatus,
  });

  // current user info
  const tokenPayload = useMemo(() => getTokenPayload(), []);
  const currentUserId = tokenPayload?.sub ?? null;
  const currentUserRole = tokenPayload?.role ?? null;
  const isAdmin = currentUserRole === "admin";

  // Fetch orders (skip fetching users)
  useEffect(() => {
    const fetchOrders = async () => {
      try {
        const res = await api.get<Order[]>("/orders/orders");
        let fetched = Array.isArray(res.data) ? res.data : [];

        if (!isAdmin && currentUserId) {
          fetched = fetched.filter((o) => o.user_id === currentUserId);
        }

        // temporary user_name for testing
        fetched = fetched.map((o) => ({ ...o, user_name: currentUserId ? "You" : o.user_id }));

        setOrders([...fetched].reverse());
      } catch (err) {
        console.error("Failed to fetch orders:", err);
        toast.error("Failed to fetch orders");
        setOrders([]);
      }
    };

    fetchOrders();
  }, [currentUserId, isAdmin]);

  // Poll recent events for live updates
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await api.get<EventLog[]>("/orders/events?limit=20");
        const events = Array.isArray(res.data) ? res.data : [];
        if (!events.length) return;

        setOrders((prev) => {
          let updated = [...prev];
          events.forEach((ev) => {
            const { event_type, payload } = ev;
            const orderIndex = updated.findIndex((o) => o.id === payload?.order_id);
            if (orderIndex === -1) return;

            const order = updated[orderIndex];
            switch (event_type) {
              case "payment.processed":
              case "payment.completed":
                toast.success(`💰 Payment completed for order ${order.id}`);
                updated[orderIndex] = { ...order, status: "paid", driver_id: order.driver_id ?? "Unassigned" };
                break;
              case "driver.assigned":
                toast.info(`🚗 Driver assigned for order ${order.id}`);
                updated[orderIndex] = { ...order, status: "assigned", driver_id: payload.driver_id ?? "Unassigned" };
                break;
              case "order.delivered":
                toast.success(`✅ Order ${order.id} delivered`);
                updated[orderIndex] = { ...order, status: "delivered" };
                break;
              default:
                break;
            }
          });
          return updated;
        });
      } catch (err) {
        console.debug("Event polling error (non-fatal):", err);
      }
    }, 3000);

    return () => clearInterval(interval);
  }, []);

  // Edit order
  const handleEdit = (order: Order) => {
    if (!isAdmin && currentUserId !== order.user_id) {
      toast.error("You can only edit your own orders");
      return;
    }
    setForm({
      user_id: order.user_id,
      items: order.items,
      driver_id: order.driver_id ?? "",
      status: order.status,
    });
    setEditingId(order.id);
    setShowModal(true);
  };

  const handlePayment = (order: Order) => {
    if (!isAdmin && currentUserId !== order.user_id) {
      toast.error("You can only pay for your own orders");
      return;
    }
    setSelectedOrder(order);
    setShowPaymentModal(true);
  };

  const handleSubmit = async () => {
    if (!form.user_id || form.items.length === 0) {
      toast.error("Please provide user ID and select items");
      return;
    }
    if (!isAdmin && currentUserId && form.user_id !== currentUserId) {
      toast.error("You can only create orders for yourself");
      return;
    }

    setLoading(true);
    const total = MENU_ITEMS.filter((i) => form.items.includes(i.name)).reduce((sum, i) => sum + i.price, 0);

    try {
      if (editingId) {
        const res = await api.put<Order>(`/orders/orders/${editingId}`, { ...form, total });
        setOrders((prev) => prev.map((o) => (o.id === editingId ? res.data : o)));
        toast.success("Order updated successfully");
      } else {
        const payload = { ...form, total, user_id: form.user_id || currentUserId || "" };
        const res = await api.post<Order>("/orders/orders", payload);
        const created = res.data;
        if (isAdmin || created.user_id === currentUserId) {
          setOrders((prev) => [created, ...prev]);
        }
        toast.success("Order created successfully");

        setTimeout(() => {
          setSelectedOrder(created);
          setShowPaymentModal(true);
        }, 400);
      }
      setShowModal(false);
      setForm({ user_id: currentUserId ?? "", items: [], driver_id: "", status: "pending" });
      setEditingId(null);
    } catch (err) {
      console.error("Create/update error:", err);
      toast.error(editingId ? "Failed to update order" : "Failed to create order");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string, ownerId?: string) => {
    if (!isAdmin && ownerId !== currentUserId) {
      toast.error("You can only delete your own orders");
      return;
    }
    if (!confirm("Delete this order?")) return;
    try {
      await api.delete(`/orders/orders/${id}`);
      setOrders((prev) => prev.filter((o) => o.id !== id));
      toast.success("Order deleted successfully");
    } catch (err) {
      console.error("Delete error:", err);
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
            setForm({ user_id: currentUserId ?? "", items: [], driver_id: "", status: "pending" });
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
              <p>
                <strong>User:</strong> {order.user_name || order.user_id}
              </p>
              <p>
                <strong>Items:</strong> {order.items.join(", ")}
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
              <p>
                <strong>Driver:</strong> {order.driver_id ?? "Unassigned"}
              </p>

              <div className="flex gap-2 mt-3">
                <Button
                  onClick={() => handleEdit(order)}
                  disabled={["assigned", "delivered"].includes(order.status)}
                >
                  ✏️ Edit
                </Button>

                {order.status === "pending" && (
                  <Button onClick={() => handlePayment(order)}>💳 Pay Now</Button>
                )}

                <Button variant="danger" onClick={() => handleDelete(order.id, order.user_id)}>
                  🗑 Delete
                </Button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Create/Edit Order Modal */}
      <Modal show={showModal} onClose={() => setShowModal(false)} title={editingId ? "Edit Order" : "Create New Order"}>
        <input
          type="text"
          placeholder="User ID"
          value={form.user_id}
          onChange={(e) => setForm({ ...form, user_id: e.target.value })}
          className="border p-2 w-full mb-3 rounded"
          disabled={!isAdmin}
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

        <Button onClick={handleSubmit} loading={loading} className="w-full">
          {editingId ? "Update Order" : "Create Order"}
        </Button>
      </Modal>

      {/* Stripe Payment Modal */}
      {selectedOrder && (
        <PaymentModal
          show={showPaymentModal}
          onClose={() => setShowPaymentModal(false)}
          orderId={selectedOrder.id}
          amount={selectedOrder.total}
        />
      )}
    </div>
  );
}
