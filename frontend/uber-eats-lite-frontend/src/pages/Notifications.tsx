import { useEffect, useState } from "react";
import api from "../api/api";

interface Notification {
  id: string;
  message: string;
  recipient: string;
}

export default function Notifications() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Notification[]>("/notifications/notifications")
      .then(res => setNotifications(res.data))
      .catch(err => setError(err.message));
  }, []);

  return (
    <div className="text-center mt-10">
      <h1 className="text-3xl font-bold">🔔 Notifications</h1>
      {error && <p className="text-red-500 mt-4">Error: {error}</p>}
      <div className="mt-6 space-y-2">
        {notifications.length ? notifications.map(n => (
          <div key={n.id} className="border rounded-lg p-3 mx-auto w-1/2">
            <p>{n.message}</p>
            <p className="text-gray-500 text-sm">To: {n.recipient}</p>
          </div>
        )) : <p>No notifications found</p>}
      </div>
    </div>
  );
}

