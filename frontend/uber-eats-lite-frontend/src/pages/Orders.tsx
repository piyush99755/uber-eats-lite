/// src/pages/Orders.tsx
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "../api/api";
import { ToastContainer, toast } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

import { Button } from "../components/Button";
import { PaymentModal } from "../components/PaymentModal";
import OrderList from "../components/OrderList";
import OrderModal from "../components/OrderModal";
import type { Order, OrderStatus } from "../components/types";

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

  // Dedup / toast trackers
  const recentlyCreated = useRef<Set<string>>(new Set());
  const recentlyPaid = useRef<Set<string>>(new Set());
  const recentlyAssigning = useRef<Set<string>>(new Set());
  const recentlyAssigned = useRef<Set<string>>(new Set());

  const safeItemsToString = (items: any) => (Array.isArray(items) ? items.join(", ") : "");
  const normalizeId = (o: any) => o?.id ?? o?.order_id ?? o?.orderId ?? o?.orderID ?? null;

  // ---------- fetch initial orders ----------
  const fetchOrders = useCallback(async () => {
    try {
      const res = await api.get<Order[]>("/orders/orders", {
        headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
      });
      let fetched = Array.isArray(res.data) ? res.data : [];
      if (!isAdmin && currentUserId) fetched = fetched.filter((o) => o.user_id === currentUserId);

      const annotated = fetched.map((o) => ({
        ...o,
        items: Array.isArray(o.items) ? o.items : [],
        user_name: o.user_id === currentUserId ? "You" : o.user_id,
        assigning: o.status === "paid" && !o.driver_id,
      }));

      setOrders(annotated.reverse());
    } catch (err) {
      console.error("Failed fetching orders:", err);
      toast.error("Failed to fetch orders");
      setOrders([]);
    }
  }, [currentUserId, isAdmin]);

  useEffect(() => { fetchOrders(); }, [fetchOrders]);

  // ---------- fetch single order ----------
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
          assigning: o.status === "paid" && !o.driver_id,
        } as Order;
      } catch (err) {
        console.warn(`[fetchSingleOrder] couldn't fetch ${orderId}:`, err);
        return null;
      }
    },
    [currentUserId]
  );

  // ---------- pure upsert ----------
  const upsertOrderPure = useCallback(
    (prev: Order[], incoming: Partial<Order> & { id: string }) => {
      const map = new Map(prev.map((p) => [p.id, { ...p }]));
      const id = incoming.id;
      const existing = map.get(id);

      const computeAssigning = (existingVal?: Order, incomingVal?: Partial<Order>) => {
        if (incomingVal?.driver_id) return false;
        if ((incomingVal?.status ?? existingVal?.status) === "paid") {
          return !(incomingVal?.driver_id ?? existingVal?.driver_id);
        }
        return false;
      };

      const merged: Order = existing
        ? { ...existing, ...incoming, items: incoming.items ?? existing.items ?? [], user_name: incoming.user_id ? (incoming.user_id === currentUserId ? "You" : incoming.user_id) : existing.user_name, assigning: computeAssigning(existing, incoming) }
        : { id, user_id: incoming.user_id ?? "unknown", user_name: incoming.user_id === currentUserId ? "You" : incoming.user_id ?? "unknown", items: incoming.items ?? [], total: Number(incoming.total ?? 0), status: incoming.status ?? "pending", driver_id: incoming.driver_id ?? null, assigning: computeAssigning(undefined, incoming), ...incoming };

      map.set(id, merged);
      const prevIds = new Set(prev.map((p) => p.id));
      const all = Array.from(map.values());
      const newOnes: Order[] = [], existingOnes: Order[] = [];
      for (const o of all) prevIds.has(o.id) ? existingOnes.push(o) : newOnes.push(o);
      const orderedExisting = prev.map((p) => map.get(p.id)).filter(Boolean) as Order[];
      return [...newOnes.reverse(), ...orderedExisting];
    },
    [currentUserId]
  );

  // ---------- WebSocket ----------
  // ---------- WebSocket ----------
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
    ws.onclose = () => setTimeout(() => !stopped && connect(), 5000);
    ws.onerror = (err) => console.error("[WS] Error", err);

    ws.onmessage = async (msg) => {
  if (!msg.data) return;
  let parsed: any;
  try { parsed = JSON.parse(msg.data); } catch { return; }

  const eventType = (parsed?.event_type ?? parsed?.event ?? parsed?.type ?? "").toLowerCase();
  const payload = parsed?.payload ?? parsed?.data ?? parsed ?? {};
  const orderId = normalizeId(payload) ?? normalizeId(parsed) ?? payload?.order_id ?? payload?.id ?? null;
  if (!eventType || !orderId) return;

  const payloadIsPartial = !payload.user_id || !Array.isArray(payload.items) || payload.items.length === 0 || typeof payload.total !== "number";
  const resolveAuthoritative = async (): Promise<Order | null> => {
    if (!payloadIsPartial) return { ...(payload as any), id: orderId, items: Array.isArray(payload.items) ? payload.items : [] } as Order;
    return await fetchSingleOrder(orderId);
  };

  try {
    const authoritative = await resolveAuthoritative();
    if (!authoritative) return;

    setOrders((prev) => upsertOrderPure(prev, authoritative));

    // ---------- TOASTS ----------

    // New order
    if (eventType.startsWith("order.created") || eventType.includes("order_create") || eventType.includes("order.create")) {
      if (!recentlyCreated.current.has(orderId)) {
        toast.info(authoritative.user_id === currentUserId 
          ? `🆕 You created order ${orderId}` 
          : `🆕 New order: ${orderId}`);
        recentlyCreated.current.add(orderId);
        setTimeout(() => recentlyCreated.current.delete(orderId), 60_000);
      }
      return;
    }

    // Order updated / paid
    if (eventType.startsWith("order.updated") || eventType.includes("order_update") || eventType.includes("order.update")) {
      const before = orders.find((o) => o.id === orderId);
      if (before && before.status !== "paid" && authoritative.status === "paid") {
        if (!recentlyPaid.current.has(orderId)) {
          toast.success(authoritative.user_id === currentUserId
            ? `💳 Payment successful for your order ${orderId}`
            : `💳 Payment successful for order ${orderId}`);
          recentlyPaid.current.add(orderId);
          setTimeout(() => recentlyPaid.current.delete(orderId), 60_000);
        }
      }

      // Paid but no driver
      if (authoritative.status === "paid" && !authoritative.driver_id && !recentlyAssigning.current.has(orderId)) {
        setOrders((prev) =>
          prev.map((o) =>
            o.id === orderId ? { ...o, assigning: true } : o
          )
        );

        const driversAvailable = payload.drivers_available ?? true; // adjust if backend provides
        if (driversAvailable) {
          toast.info(`🔎 Assigning driver for your order ${orderId}…`);
        } else {
          toast.warn(`⚠️ No drivers available for your order ${orderId} at the moment`);
        }

        recentlyAssigning.current.add(orderId);
        setTimeout(() => recentlyAssigning.current.delete(orderId), 60_000);
      }
      return;
    }

    // Driver assigned
    if (eventType.startsWith("driver.assigned") || eventType.includes("driver_assigned")) {
      setOrders((prev) =>
        prev.map((o) =>
          o.id === orderId ? { ...o, assigning: false } : o
        )
      );

      if (!recentlyAssigned.current.has(orderId)) {
        toast.success(authoritative.user_id === currentUserId
          ? `🚗 Driver assigned to your order ${orderId}`
          : `🚗 Driver assigned to order ${orderId}`);
        recentlyAssigned.current.add(orderId);
        setTimeout(() => recentlyAssigned.current.delete(orderId), 60_000);
      }
      return;
    }

    // Driver pending (no drivers yet)
    if (eventType === "driver.pending") {
      setOrders((prev) =>
        prev.map((o) =>
          o.id === orderId ? { ...o, assigning: true } : o
        )
      );

      if (payload.reason === "no drivers available") {
        toast.warn(`⚠️ No drivers currently available for order ${orderId}`);
      }
      return;
    }

    // Driver failed (assignment failed after retries)
    if (eventType === "driver.failed") {
      setOrders((prev) =>
        prev.map((o) =>
          o.id === orderId ? { ...o, assigning: false } : o
        )
      );
      toast.error(`❌ Driver assignment failed for order ${orderId} after retries`);
      return;
    }

    // Order deleted
    if (eventType.startsWith("order.deleted") || eventType.includes("order_deleted")) {
      toast.warn(`🗑 Order ${orderId} deleted`);
      return;
    }

  } catch (err) {
    console.error("[WS] handler error:", err);
  }
};

  };

  connect();
  return () => { stopped = true; wsRef.current?.close(); };
}, [BASE_URL, fetchSingleOrder, upsertOrderPure, orders, currentUserId]);


  // ---------- handlers ----------
  const handleEdit = (order: Order) => {
    if (!isAdmin && order.user_id !== currentUserId) { toast.error("You can only edit your own orders"); return; }
    setForm({ user_id: order.user_id, items: Array.isArray(order.items) ? order.items : [], driver_id: order.driver_id ?? "", status: order.status });
    setEditingId(order.id);
    setShowModal(true);
  };

  const handlePayment = (order: Order) => {
    if (!isAdmin && order.user_id !== currentUserId) { toast.error("You can only pay for your own orders"); return; }
    setSelectedOrder(order);
    setShowPaymentModal(true);
  };

  const handleSubmit = async () => {
    if (!form.user_id || form.items.length === 0) { toast.error("Please provide user ID and select items"); return; }
    const total = MENU_ITEMS.filter((i) => form.items.includes(i.name)).reduce((sum, i) => sum + i.price, 0);
    setLoading(true);

    try {
      if (editingId) {
        const res = await api.put<Order>(`/orders/orders/${editingId}`, { ...form, total });
        setOrders((prev) => prev.map((o) => o.id === editingId ? { ...res.data, items: Array.isArray(res.data.items) ? res.data.items : [] } : o));
        toast.success("Order updated successfully");
      } else {
        const payload = { ...form, total, user_id: form.user_id || currentUserId || "" };
        const res = await api.post<Order>("/orders/orders", payload);
        setOrders((prev) => upsertOrderPure(prev, { ...(res.data as Order), id: res.data.id }));
        recentlyCreated.current.add(res.data.id);
        toast.success("Order created successfully");
        setSelectedOrder(res.data);
        setShowPaymentModal(true);
      }

      setShowModal(false);
      setEditingId(null);
      setForm({ user_id: currentUserId ?? "", items: [], driver_id: "", status: "pending" });
    } catch { toast.error(editingId ? "Failed to update order" : "Failed to create order"); }
    finally { setLoading(false); }
  };

  const handleDelete = async (id: string, ownerId?: string) => {
    if (!isAdmin && ownerId !== currentUserId) { toast.error("You can only delete your own orders"); return; }
    if (!confirm("Delete this order?")) return;
    try { await api.delete(`/orders/orders/${id}`); setOrders((prev) => prev.filter((o) => o.id !== id)); toast.success("Order deleted successfully"); }
    catch { toast.error("Failed to delete order"); }
  };

  // ---------- render ----------
  return (
    <div className="p-6">
      <ToastContainer position="top-right" />
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">🧾 Orders</h1>
        <Button onClick={() => { setForm({ user_id: currentUserId ?? "", items: [], driver_id: "", status: "pending" }); setEditingId(null); setShowModal(true); }}>
          ➕ Create Order
        </Button>
      </div>

      <OrderList orders={orders} onEdit={handleEdit} onPay={handlePayment} onDelete={handleDelete} />

      <OrderModal show={showModal} onClose={() => setShowModal(false)} form={form} setForm={setForm} onSubmit={handleSubmit} loading={loading} editingId={editingId} isAdmin={isAdmin} />

      {selectedOrder && (
        <PaymentModal show={showPaymentModal} onClose={() => setShowPaymentModal(false)} orderId={selectedOrder.id} amount={selectedOrder.total} />
      )}
    </div>
  );
}
