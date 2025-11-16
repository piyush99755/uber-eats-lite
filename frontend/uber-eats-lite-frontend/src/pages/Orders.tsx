/// src/pages/Orders.tsx
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "../api/api";
import { Button } from "../components/Button";
import { Modal } from "../components/Modal";
import { PaymentModal } from "../components/PaymentModal";
import { ToastContainer, toast } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

export type OrderStatus = "pending" | "paid" | "assigned" | "delivered";

interface Order {
  id: string;
  user_id: string;
  user_name?: string;
  items: string[];
  total: number;
  status: OrderStatus;
  driver_id?: string | null;
  payment_status?: string;
  [k: string]: any;
}

interface RawEvent {
  event?: string;
  event_type?: string;
  type?: string;
  order_id?: string;
  payload?: any;
  data?: any;
  id?: string; // envelope id
}

const MENU_ITEMS = [
  { name: "Burger", price: 8 },
  { name: "Fries", price: 4 },
  { name: "Coke", price: 3 },
  { name: "Pizza", price: 12 },
  { name: "Salad", price: 6 },
];

function parseTokenPayload() {
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
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [form, setForm] = useState({
    user_id: "",
    items: [] as string[],
    driver_id: "",
    status: "pending" as OrderStatus,
  });

  const tokenPayload = useMemo(() => parseTokenPayload(), []);
  const currentUserId = tokenPayload?.sub ?? null;
  const currentUserRole = tokenPayload?.role ?? null;
  const isAdmin = currentUserRole === "admin";

  const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
  const wsRef = useRef<WebSocket | null>(null);

  const recentlyCreated = useRef<Set<string>>(new Set());
  const recentlyPaid = useRef<Set<string>>(new Set());

  const safeItemsToString = (items: any) => (Array.isArray(items) ? items.join(", ") : "");
  const normalizeId = (o: any) => o?.id ?? o?.order_id ?? o?.orderId ?? o?.orderID ?? null;

  // ---------------- fetch initial orders ----------------
  const fetchOrders = useCallback(async () => {
    try {
      const res = await api.get<Order[]>("/orders/orders", {
        headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
      });
      let fetched = Array.isArray(res.data) ? res.data : [];
      if (!isAdmin && currentUserId) {
        fetched = fetched.filter((o) => o.user_id === currentUserId);
      }
      const annotated = fetched.map((o) => ({
        ...o,
        items: Array.isArray(o.items) ? o.items : [],
        user_name: o.user_id === currentUserId ? "You" : o.user_id,
      }));
      setOrders(annotated.reverse());
    } catch (err) {
      console.error("Failed fetching orders:", err);
      toast.error("Failed to fetch orders");
      setOrders([]);
    }
  }, [currentUserId, isAdmin]);

  useEffect(() => {
    fetchOrders();
  }, [fetchOrders]);

  // ---------------- fetch single order ----------------
  const fetchSingleOrder = useCallback(
    async (orderId: string) => {
      try {
        const res = await api.get<Order>(`/orders/orders/${orderId}`, {
          headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
        });
        const o = res.data;
        return {
          ...o,
          items: Array.isArray(o.items) ? o.items : [],
          user_name: o.user_id === currentUserId ? "You" : o.user_id,
        } as Order;
      } catch (err) {
        console.warn(`[fetchSingleOrder] couldn't fetch ${orderId}:`, err);
        return null;
      }
    },
    [currentUserId]
  );

  // ---------------- pure upsert (returns new array) ----------------
  const upsertOrderPure = useCallback((prev: Order[], incoming: Partial<Order> & { id: string }) => {
    // Build map of existing
    const map = new Map(prev.map((p) => [p.id, { ...p }]));

    const id = incoming.id;
    const existing = map.get(id);

    const merged: Order =
      existing != null
        ? {
            ...existing,
            ...incoming,
            items:
              incoming.items !== undefined
                ? Array.isArray(incoming.items)
                  ? incoming.items
                  : existing.items ?? []
                : existing.items ?? [],
            user_name:
              incoming.user_id !== undefined
                ? incoming.user_id === currentUserId
                  ? "You"
                  : incoming.user_id
                : existing.user_name,
          }
        : {
            id,
            user_id: incoming.user_id ?? (incoming as any).userId ?? "unknown",
            user_name:
              (incoming.user_id ?? (incoming as any).userId) === currentUserId
                ? "You"
                : incoming.user_id ?? (incoming as any).userId ?? "unknown",
            items: Array.isArray(incoming.items) ? incoming.items : [],
            total:
              typeof incoming.total === "number"
                ? incoming.total
                : incoming.total
                ? Number(incoming.total)
                : 0,
            status: (incoming.status as OrderStatus) ?? "pending",
            driver_id: incoming.driver_id ?? null,
            ...incoming,
          };

    map.set(id, merged);

    // keep new items at front, preserve previous order for existing
    const prevIds = new Set(prev.map((p) => p.id));
    const all = Array.from(map.values());

    const newOnes: Order[] = [];
    const existingOnes: Order[] = [];
    for (const o of all) {
      if (!prevIds.has(o.id)) newOnes.push(o);
      else existingOnes.push(o);
    }
    const orderedExisting = prev.map((p) => map.get(p.id)).filter(Boolean) as Order[];

    return [...newOnes.reverse(), ...orderedExisting];
  }, [currentUserId]);

  // ---------------- WebSocket: robust hybrid handler ----------------
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;

    const WS_URL = `${BASE_URL.replace(/^http/, "ws")}/ws/orders?token=${token}`;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => console.log("[WS] Connected");
      ws.onclose = () => {
        console.warn("[WS] Disconnected — reconnecting in 5s...");
        setTimeout(() => {
          if (!stopped) connect();
        }, 5000);
      };
      ws.onerror = (err) => console.error("[WS] Error", err);

      ws.onmessage = async (msg) => {
        console.log("🔥 RAW WS MESSAGE:", msg.data);
        if (!msg.data) return;

        let parsed: RawEvent | null = null;
        try {
          parsed = JSON.parse(msg.data);
        } catch (err) {
          console.error("[WS] Invalid JSON:", msg.data);
          return;
        }

        const eventType = (
          parsed?.event_type ??
          parsed?.event ??
          parsed?.type ??
          ""
        ).toLowerCase();

        const payload = parsed?.payload ?? parsed?.data ?? parsed ?? {};
        const orderId = normalizeId(payload) ?? normalizeId(parsed) ?? payload?.order_id ?? payload?.id ?? null;

        if (!eventType || !orderId) {
          // If envelope has id but not order id, ignore (we saw events using envelope id).
          return;
        }

        // Consider payload partial if it lacks essential fields
        const payloadIsPartial =
          !payload.user_id ||
          !Array.isArray(payload.items) ||
          payload.items.length === 0 ||
          typeof payload.total !== "number";

        // Resolve authoritative order (hybrid C)
        const resolveAuthoritative = async (): Promise<Order | null> => {
          if (!payloadIsPartial) {
            return { ...(payload as any), id: orderId, items: Array.isArray(payload.items) ? payload.items : [] } as Order;
          }
          // payload partial -> attempt fetch
          const full = await fetchSingleOrder(orderId);
          if (full) return full;
          // fetch failed -> return null
          return null;
        };

        try {
          // ---------- order.created ----------
          if (eventType.startsWith("order.created") || eventType.startsWith("order_create") || eventType.startsWith("order.create")) {
            const authoritative = await resolveAuthoritative();
            if (!authoritative) {
              console.warn("[WS] Ignoring partial order.created (no authoritative data)", payload);
              return;
            }

            setOrders((prev) => {
              // single setOrders call using pure upsert
              return upsertOrderPure(prev, authoritative);
            });

            if (!recentlyCreated.current.has(orderId)) {
              toast.info(`🆕 New order: ${orderId}`);
            }
            recentlyCreated.current.add(orderId);
            setTimeout(() => recentlyCreated.current.delete(orderId), 60_000);
            return;
          }

          // ---------- order.updated ----------
          if (eventType.startsWith("order.updated") || eventType.startsWith("order_update") || eventType.startsWith("order.update")) {
            // try to get authoritative
            const authoritative = await resolveAuthoritative();

            if (authoritative) {
              // we have full data -> upsert
              setOrders((prev) => upsertOrderPure(prev, authoritative));

              // toast if payment transitioned
              setOrders((prev) => {
                const before = prev.find((p) => p.id === orderId);
                if (before && before.status !== "paid" && authoritative.status === "paid") {
                  if (!recentlyPaid.current.has(orderId)) {
                    toast.success(`💳 Payment successful for order ${orderId}`);
                    recentlyPaid.current.add(orderId);
                    setTimeout(() => recentlyPaid.current.delete(orderId), 60_000);
                  }
                }
                return prev;
              });

              return;
            }

            // authoritative fetch failed -> hybrid: if order exists locally, merge partial; else ignore
            setOrders((prev) => {
              const exists = prev.some((p) => p.id === orderId);
              if (!exists) {
                console.warn("[WS] Ignoring partial update for unknown order", payload);
                return prev;
              }

              // merge partial into existing (single state update)
              const incoming: Partial<Order> & { id: string } = { id: orderId, ...(payload || {}) };
              const newArr = upsertOrderPure(prev, incoming);

              // detect payment transition by comparing before/after
              const before = prev.find((p) => p.id === orderId)!;
              const after = newArr.find((p) => p.id === orderId)!;
              if (before.status !== "paid" && after.status === "paid") {
                if (!recentlyPaid.current.has(orderId)) {
                  toast.success(`💳 Payment successful for order ${orderId}`);
                  recentlyPaid.current.add(orderId);
                  setTimeout(() => recentlyPaid.current.delete(orderId), 60_000);
                }
              }

              return newArr;
            });

            return;
          }

          // ---------- driver.assigned ----------
          if (eventType.startsWith("driver.assigned") || eventType.includes("driver_assigned")) {
            const authoritative = await resolveAuthoritative();
            if (!authoritative) {
              // if no authoritative and not present locally -> ignore
              setOrders((prev) => {
                const exists = prev.some((p) => p.id === orderId);
                if (!exists) {
                  console.warn("[WS] Ignoring driver.assigned for unknown order", payload);
                  return prev;
                }
                // merge partial driver_id
                const incoming: Partial<Order> & { id: string } = {
                  id: orderId,
                  driver_id: payload.driver_id ?? payload.driverId,
                  status: "assigned",
                };
                return upsertOrderPure(prev, incoming);
              });
              return;
            }

            // we have authoritative -> merge assignment
            setOrders((prev) => {
              const incoming: Partial<Order> & { id: string } = {
                ...authoritative,
                driver_id: payload.driver_id ?? payload.driverId ?? authoritative.driver_id,
                status: authoritative.status === "paid" ? "paid" : "assigned",
              };
              return upsertOrderPure(prev, incoming);
            });

            toast.info(`🚗 Driver assigned to order ${orderId}`);
            return;
          }

          // ---------- order.deleted ----------
          if (eventType.startsWith("order.deleted") || eventType.startsWith("order_deleted")) {
            setOrders((prev) => prev.filter((o) => o.id !== orderId));
            toast.warn(`🗑 Order ${orderId} deleted`);
            return;
          }

          // unknown event -> ignore
        } catch (err) {
          console.error("[WS] handler error:", err);
        }
      };
    };

    connect();
    return () => {
      stopped = true;
      wsRef.current?.close();
    };
  }, [BASE_URL, fetchSingleOrder, upsertOrderPure]);

  // ---------- handlers: edit / payment / create / delete ----------
  const handleEdit = (order: Order) => {
    if (!isAdmin && order.user_id !== currentUserId) {
      toast.error("You can only edit your own orders");
      return;
    }
    setForm({
      user_id: order.user_id,
      items: Array.isArray(order.items) ? order.items : [],
      driver_id: order.driver_id ?? "",
      status: order.status,
    });
    setEditingId(order.id);
    setShowModal(true);
  };

  const handlePayment = (order: Order) => {
    if (!isAdmin && order.user_id !== currentUserId) {
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

    const total = MENU_ITEMS.filter((i) => form.items.includes(i.name)).reduce((sum, i) => sum + i.price, 0);
    setLoading(true);

    try {
      if (editingId) {
        const res = await api.put<Order>(`/orders/orders/${editingId}`, { ...form, total });
        // update single order
        setOrders((prev) => prev.map((o) => (o.id === editingId ? { ...res.data, items: Array.isArray(res.data.items) ? res.data.items : [] } : o)));
        toast.success("Order updated successfully");
      } else {
        const payload = { ...form, total, user_id: form.user_id || currentUserId || "" };
        const res = await api.post<Order>("/orders/orders", payload);

        // insert created order locally (single setOrders)
        setOrders((prev) => upsertOrderPure(prev, { ...(res.data as Order), id: res.data.id }));

        recentlyCreated.current.add(res.data.id);
        toast.success("Order created successfully");

        setSelectedOrder(res.data);
        setShowPaymentModal(true);
      }

      setShowModal(false);
      setEditingId(null);
      setForm({ user_id: currentUserId ?? "", items: [], driver_id: "", status: "pending" });
    } catch (err) {
      console.error("Submit error:", err);
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

  // ---------- render ----------
  return (
    <div className="p-6">
      <ToastContainer position="top-right" />
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">🧾 Orders</h1>
        <Button
          onClick={() => {
            setForm({ user_id: currentUserId ?? "", items: [], driver_id: "", status: "pending" });
            setEditingId(null);
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
              <p><strong>User:</strong> {order.user_name || order.user_id}</p>
              <p><strong>Items:</strong> {safeItemsToString(order.items)}</p>
              <p><strong>Total:</strong> ${typeof order.total === "number" ? order.total.toFixed(2) : Number(order.total || 0).toFixed(2)}</p>
              <p>
                <strong>Status:</strong>{" "}
                <span className={`font-semibold ${
                  order.status === "pending" ? "text-yellow-600" :
                  order.status === "paid" ? "text-blue-600" :
                  order.status === "assigned" ? "text-purple-600" : "text-green-600"
                }`}>
                  {order.status}
                </span>
              </p>
              <p><strong>Driver:</strong> {order.driver_id ?? "Unassigned"}</p>

              <div className="flex gap-2 mt-3">
                <Button onClick={() => handleEdit(order)} disabled={["assigned", "delivered"].includes(order.status)}>✏️ Edit</Button>
                {order.status === "pending" && <Button onClick={() => handlePayment(order)}>💳 Pay Now</Button>}
                <Button variant="danger" onClick={() => handleDelete(order.id, order.user_id)}>🗑 Delete</Button>
              </div>
            </div>
          ))
        )}
      </div>

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
              className={`border rounded p-2 text-sm ${form.items.includes(item.name) ? "bg-green-500 text-white" : "bg-gray-100"}`}
            >
              {item.name} – ${item.price}
            </button>
          ))}
        </div>
        <Button onClick={handleSubmit} loading={loading} className="w-full">{editingId ? "Update Order" : "Create Order"}</Button>
      </Modal>

      {selectedOrder && (
        <PaymentModal show={showPaymentModal} onClose={() => setShowPaymentModal(false)} orderId={selectedOrder.id} amount={selectedOrder.total} />
      )}
    </div>
  );
}
