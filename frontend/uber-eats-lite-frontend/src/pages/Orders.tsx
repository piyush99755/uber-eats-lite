// src/pages/Orders.tsx
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

  const toastSeen = useRef<Map<string, number>>(new Map());
  const lastFetchMs = useRef<Map<string, number>>(new Map());
  const FETCH_THROTTLE_MS = 2000;

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
        assigning: (o.status === "paid" || o.payment_status === "paid") && !o.driver_id,
        driver_name: (o as any).driver_name ?? null,
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
          assigning: (o.status === "paid" || o.payment_status === "paid") && !o.driver_id,
          driver_name: (o as any).driver_name ?? null,
        } as Order;
      } catch (err) {
        console.warn(`[fetchSingleOrder] couldn't fetch ${orderId}:`, err);
        return null;
      }
    },
    [currentUserId]
  );

  // ---------- safe merge/upsert ----------
 const upsertOrderPure = useCallback(
  (prev: Order[], incoming: Partial<Order> & { id: string }) => {
    const id = incoming.id;
    const map = new Map(prev.map((p) => [p.id, { ...p }]));

    const existing = map.get(id);

    const hasValue = <T,>(v: T | undefined | null) => typeof v !== "undefined" && v !== null;
    const safeNumber = (v: any, fallback: number) => {
      if (!hasValue(v)) return fallback;
      const n = Number(v);
      return Number.isFinite(n) ? n : fallback;
    };

    // Status precedence higher => more "final"
    const statusRank: Record<string, number> = {
      delivered: 5,
      assigned: 4,
      paid: 3,
      pending: 1,
      unknown: 0,
    };

    const pickStatus = (existingStatus?: string | null, incomingStatus?: string | null) => {
      // If incoming lacks a status, keep existing (or default pending)
      if (!hasValue(incomingStatus)) return existingStatus ?? "pending";
      if (!hasValue(existingStatus)) return incomingStatus ?? "pending";

      const inc = (incomingStatus || "unknown").toLowerCase();
      const ex = (existingStatus || "unknown").toLowerCase();

      // If incoming would downgrade (lower rank), ignore it
      const incRank = statusRank[inc] ?? 0;
      const exRank = statusRank[ex] ?? 0;
      if (incRank < exRank) return existingStatus; // keep the more final status

      // otherwise accept incoming
      return incomingStatus;
    };

    const mergeItems = (existingItems: any[] | undefined, incomingItems: any[] | undefined) => {
      // If incoming items is explicitly a non-empty array, use it
      if (Array.isArray(incomingItems) && incomingItems.length > 0) return incomingItems;
      // If incoming is empty array, avoid clobbering existing non-empty items
      if (Array.isArray(incomingItems) && incomingItems.length === 0) {
        return existingItems ?? [];
      }
      // incoming undefined/null -> keep existing or empty
      return Array.isArray(existingItems) ? existingItems : [];
    };

    const computeAssigning = (existingVal?: Order, incomingVal?: Partial<Order>) => {
      const status = (incomingVal?.status ?? existingVal?.status) as string | undefined;
      const payment = (incomingVal as any)?.payment_status ?? existingVal?.payment_status;
      const driver_id = incomingVal?.driver_id ?? existingVal?.driver_id;
      if (driver_id) return false;
      if (status === "paid" || payment === "paid") return true;
      return false;
    };

    const merged: Order = existing
      ? {
          ...existing,
          id,
          // user_id / user_name: prefer incoming when present
          user_id: hasValue(incoming.user_id) ? (incoming.user_id as string) : existing.user_id,
          user_name: hasValue(incoming.user_name) ? (incoming.user_name as string) : existing.user_name,
          // items: don't overwrite a good existing with an empty incoming array
          items: mergeItems(existing.items, incoming.items),
          // total: safe number merge (avoid NaN)
          total: safeNumber(incoming.total ?? existing.total, existing.total ?? 0),
          // status: use precedence-aware pick
          status: pickStatus(existing.status, incoming.status),
          // driver info: accept only meaningful incoming values
          driver_id: hasValue(incoming.driver_id) ? incoming.driver_id : existing.driver_id ?? null,
          driver_name: hasValue((incoming as any).driver_name) ? (incoming as any).driver_name : existing.driver_name ?? null,
          // payment_status: accept incoming only if present
          payment_status: hasValue((incoming as any).payment_status) ? (incoming as any).payment_status : existing.payment_status ?? "pending",
          assigning: computeAssigning(existing, incoming),
          // preserve any other incoming fields (but after the careful picks above)
          ...incoming,
        }
      : {
          // New entry: be defensive with defaults
          id,
          user_id: incoming.user_id ?? "unknown",
          user_name: incoming.user_id === currentUserId ? "You" : incoming.user_name ?? incoming.user_id ?? "unknown",
          items: Array.isArray(incoming.items) ? incoming.items : [],
          total: safeNumber(incoming.total, 0),
          status: incoming.status ?? "pending",
          driver_id: incoming.driver_id ?? null,
          driver_name: (incoming as any).driver_name ?? null,
          payment_status: (incoming as any).payment_status ?? "pending",
          assigning: computeAssigning(undefined, incoming),
          ...incoming,
        };

    map.set(id, merged);

    // Keep ordering logic: new ones first, preserve previous order for existing ones
    const prevIds = new Set(prev.map((p) => p.id));
    const all = Array.from(map.values());
    const newOnes: Order[] = [];
    const existingOnes: Order[] = [];
    for (const o of all) (prevIds.has(o.id) ? existingOnes : newOnes).push(o);
    const orderedExisting = prev.map((p) => map.get(p.id)).filter(Boolean) as Order[];
    return [...newOnes.reverse(), ...orderedExisting];
  },
  [currentUserId]
);


  // ---------- normalize event type ----------
  const normalizeEventType = (raw: any) => {
    if (!raw) return "";
    const s = String(raw).toLowerCase();
    if (s.includes("order.created") || s.includes("order_create")) return "order.created";
    if (s.includes("order.updated") || s.includes("order_update")) return "order.updated";
    if (s.includes("payment.completed") || s.includes("payment_complete") || s.includes("paymentcompleted"))
      return "payment.completed";
    if (s.includes("driver.assigned") || s.includes("driver_assigned")) return "driver.assigned";
    if (s.includes("driver.pending")) return "driver.pending";
    if (s.includes("driver.failed")) return "driver.failed";
    if (s.includes("delivery.completed") || s.includes("delivery_complete") || s.includes("order.delivered"))
      return "delivery.completed";
    if (s.includes("order.deleted") || s.includes("order_deleted")) return "order.deleted";
    return s;
  };

  const pushDedupToast = (key: string, fn: () => void, ttlMs = 6000) => {
  const existing = sessionStorage.getItem(key);
  const now = Date.now();

  if (existing && now - Number(existing) < ttlMs) return;

  sessionStorage.setItem(key, now.toString());
  fn();
};


  // ---------- WebSocket ----------

useEffect(() => {
  const token = localStorage.getItem("token");
  if (!token) return;

  const WS_URL = `${BASE_URL.replace(/^http/, "ws")}/ws/orders?token=${token}`;

  let isStopped = false;
  let reconnectTimer: number | null = null;

  const connect = () => {
    if (isStopped) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("[WS] Connected:", WS_URL);
    };

    ws.onerror = (err) => {
      console.error("[WS] Error:", err);
    };

    ws.onclose = () => {
      console.log("[WS] Closed — reconnecting in 3s…");
      if (!isStopped) reconnectTimer = window.setTimeout(connect, 3000);
    };

    ws.onmessage = async (event) => {
      if (!event.data) return;

      // 1️⃣ Parse safely
      let raw: any;
      try {
        raw = JSON.parse(event.data);
      } catch {
        console.warn("[WS] Invalid JSON:", event.data);
        return;
      }

      // 2️⃣ Normalize event
      const eventType = normalizeEventType(
        raw.type ?? raw.event ?? raw.event_type ?? raw.data?.type
      );

      if (!eventType) return;

      // 3️⃣ Normalize payload
      const payload = raw.data ?? raw.payload ?? raw;
      const orderId = payload.order_id ?? payload.id;
      if (!orderId) return;

      // 4️⃣ Optional: Fetch missing fields (throttled)
      let fullOrder: Order | null = null;
      const now = Date.now();
      const lastFetch = lastFetchMs.current.get(orderId) ?? 0;

      const missingData =
        payload.items === undefined || payload.status === undefined;

      if (missingData && now - lastFetch > FETCH_THROTTLE_MS) {
        lastFetchMs.current.set(orderId, now);
        fullOrder = await fetchSingleOrder(orderId);
      }

      // 5️⃣ Unified order object
      const unified: Partial<Order> & { id: string } = {
        id: orderId,
        user_id: payload.user_id ?? fullOrder?.user_id,
        user_name: payload.user_name ?? fullOrder?.user_name ?? "Unknown",
        items:
          Array.isArray(payload.items) && payload.items.length > 0
            ? payload.items
            : fullOrder?.items ?? [],
        total:
          Number(payload.total ?? payload.total_amount) ??
          fullOrder?.total ??
          0,
        status: payload.status ?? fullOrder?.status ?? "pending",
        payment_status:
          payload.payment_status ?? fullOrder?.payment_status ?? "pending",
        driver_id: payload.driver_id ?? fullOrder?.driver_id ?? null,
        driver_name: payload.driver_name ?? fullOrder?.driver_name ?? null,
      };

      // 6️⃣ Merge into state
      setOrders((prev) => upsertOrderPure(prev, unified));

      // 7️⃣ Toasts (dedup)
      const isSelf = unified.user_id === currentUserId;
      const toastKey = `WS:${orderId}:${eventType}`;

      switch (eventType) {
        case "order.created":
          pushDedupToast(toastKey, () =>
            toast.info(
              isSelf
                ? `🆕 You created order ${orderId}`
                : `🆕 New order received (${orderId})`
            )
          );
          break;

        case "payment.completed":
          pushDedupToast(toastKey, () =>
            toast.success(`💳 Payment completed for order ${orderId}`)
          );
          break;

        case "order.updated":
          pushDedupToast(toastKey, () =>
            toast.info(`🔄 Order ${orderId} updated`)
          );
          break;

        case "driver.assigned":
          pushDedupToast(toastKey, () =>
            toast.success(`🚗 Driver assigned to order ${orderId}`)
          );
          break;

        case "driver.pending":
          pushDedupToast(toastKey, () =>
            toast.warn(`⚠️ No drivers available for ${orderId}`)
          );
          break;

        case "driver.failed":
          pushDedupToast(toastKey, () =>
            toast.error(`❌ Driver assignment failed for order ${orderId}`)
          );
          break;

        case "delivery.completed":
          pushDedupToast(toastKey, () =>
            toast.success(`📦 Order ${orderId} delivered`)
          );
          break;

        case "order.deleted":
          pushDedupToast(toastKey, () =>
            toast.warn(`🗑 Order ${orderId} deleted`)
          );
          setOrders((prev) => prev.filter((o) => o.id !== orderId));
          break;

        default:
          console.log("[WS] Unhandled event:", eventType, payload);
      }
    };
  };

  connect();

  return () => {
    isStopped = true;
    wsRef.current?.close();
    if (reconnectTimer) clearTimeout(reconnectTimer);
  };
}, [BASE_URL, fetchSingleOrder, upsertOrderPure, currentUserId]);



  // ---------- handlers ----------
  const handleEdit = (order: Order) => {
    if (!isAdmin && order.user_id !== currentUserId) {
      toast.error("You can only edit your own orders");
      return;
    }
    setForm({ user_id: order.user_id, items: Array.isArray(order.items) ? order.items : [], driver_id: order.driver_id ?? "", status: order.status });
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
        setOrders((prev) => prev.map((o) => (o.id === editingId ? { ...res.data, items: Array.isArray(res.data.items) ? res.data.items : [] } : o)));
        toast.success("Order updated successfully");
      } else {
        const payload = { ...form, total, user_id: form.user_id || currentUserId || "" };
        const res = await api.post<Order>("/orders/orders", payload);
        setOrders((prev) => upsertOrderPure(prev, { ...(res.data as Order), id: res.data.id }));
        pushDedupToast(`${res.data.id}:created`, () => {
          toast.success("Order created successfully");
        });
        setSelectedOrder(res.data);
        setShowPaymentModal(true);
      }

      setShowModal(false);
      setEditingId(null);
      setForm({ user_id: currentUserId ?? "", items: [], driver_id: "", status: "pending" });
    } catch (err) {
      console.error("submit error", err);
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
    } catch {
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

      <OrderList orders={orders} onEdit={handleEdit} onPay={handlePayment} onDelete={handleDelete} />

      <OrderModal show={showModal} onClose={() => setShowModal(false)} form={form} setForm={setForm} onSubmit={handleSubmit} loading={loading} editingId={editingId} isAdmin={isAdmin} />

      {selectedOrder && (
        <PaymentModal show={showPaymentModal} onClose={() => setShowPaymentModal(false)} orderId={selectedOrder.id} amount={selectedOrder.total} />
      )}
    </div>
  );
}
