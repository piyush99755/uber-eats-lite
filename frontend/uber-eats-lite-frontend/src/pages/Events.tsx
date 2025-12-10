import { useEffect, useState } from "react";
import api from "../api/api";

interface Notification {
  id: string;
  message: string;
  recipient: string;
  timestamp?: string;
}

export default function Notifications() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [error, setError] = useState("");

  // Normalize backend event into Notification
  const normalizeEvent = (data: any): Notification => {
    return {
      id: data.id || crypto.randomUUID(),
      message:
        data.message ||
        (data.type ? `${data.type} event` : JSON.stringify(data)),
      recipient: data.recipient || data.user_id || "unknown",
      timestamp: data.timestamp || new Date().toISOString(),
    };
  };

  useEffect(() => {
    let ws: WebSocket | null = null;

    const fetchInitialNotifications = async () => {
      try {
        // 1️⃣ Fetch saved notifications from backend
        const res = await api.get<Notification[]>("/notifications/notifications");
        setNotifications(res.data);
      } catch (err: any) {
        setError("Failed to load notifications: " + err.message);
      }
    };

    const connectWebSocket = () => {
      ws = new WebSocket("ws://localhost:8000/ws/notifications");

      ws.onopen = () => {
        console.log("[WS] Connected to notifications");
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const normalized = normalizeEvent(data.data || data);

          // Add to top of list
          setNotifications((prev) => [normalized, ...prev]);
        } catch (err) {
          console.error("[WS] Parse error:", err);
        }
      };

      ws.onclose = (e) => {
        console.warn("[WS] Disconnected. Reconnecting in 3s...", e.reason);
        setTimeout(connectWebSocket, 3000); // Auto-reconnect
      };

      ws.onerror = (err) => {
        console.error("[WS] Error:", err);
        setError("WebSocket connection failed");
        ws?.close();
      };
    };

    fetchInitialNotifications();
    connectWebSocket();

    return () => ws?.close();
  }, []);

  return (
    <div className="text-center mt-10">
      <h1 className="text-3xl font-bold">🔔 Notifications</h1>

      {error && <p className="text-red-500 mt-4">{error}</p>}

      <div className="mt-6 space-y-2">
        {notifications.length ? (
          notifications.map((n) => (
            <div key={n.id} className="border rounded-lg p-3 mx-auto w-1/2 text-left">
              <p className="font-medium">{n.message}</p>
              <p className="text-gray-500 text-sm">
                To: {n.recipient}{" "}
                {n.timestamp && (
                  <span className="ml-2 text-xs text-gray-400">
                    {new Date(n.timestamp).toLocaleString()}
                  </span>
                )}
              </p>
            </div>
          ))
        ) : (
          <p className="text-gray-500">No notifications found</p>
        )}
      </div>
    </div>
  );
}
