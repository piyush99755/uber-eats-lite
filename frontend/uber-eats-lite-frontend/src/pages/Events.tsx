import { useEffect, useState } from "react";
import api from "../api/api";

interface EventLog {
  id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export default function Events() {
  const [events, setEvents] = useState<EventLog[]>([]);

  useEffect(() => {
    api.get<EventLog[]>("/orders/events")
      .then(res => setEvents(res.data.slice(0, 20)))
      .catch(() => console.error("Failed to fetch events"));
  }, []);

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-4">🧩 Recent Events</h1>
      <div className="overflow-x-auto">
        <table className="min-w-full bg-white border rounded-lg">
          <thead>
            <tr className="bg-gray-100 text-left">
              <th className="p-3">Event Type</th>
              <th className="p-3">Payload</th>
              <th className="p-3">Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {events.map(ev => (
              <tr key={ev.id} className="border-t hover:bg-gray-50">
                <td className="p-3">
                  <span className={`px-2 py-1 rounded text-white text-sm ${
                    ev.event_type.includes("order") ? "bg-blue-500"
                    : ev.event_type.includes("driver") ? "bg-yellow-500"
                    : ev.event_type.includes("payment") ? "bg-green-500"
                    : "bg-gray-400"
                  }`}>
                    {ev.event_type}
                  </span>
                </td>
                <td className="p-3 text-sm text-gray-600">
                  {JSON.stringify(ev.payload as object)}
                </td>
                <td className="p-3 text-gray-500">
                  {new Date(ev.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
