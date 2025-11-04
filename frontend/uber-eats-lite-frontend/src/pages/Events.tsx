import { useEffect, useState } from "react";

// Define the event interface based on your backend schema
interface EventLog {
  id: string;
  event_type: string;
  source_service: string;
  payload: Record<string, unknown>;
  occurred_at: string;
  metadata?: Record<string, unknown>;
}

export default function Events() {
  const [events, setEvents] = useState<EventLog[]>([]);
  const [loading, setLoading] = useState(false);

  const loadEvents = async () => {
    try {
      setLoading(true);

      // ✅ Corrected route (goes through API Gateway)
      const res = await fetch("http://localhost:8000/notifications/events?limit=50");



      if (!res.ok) throw new Error("Failed to fetch events");
      const data: EventLog[] = await res.json();
      setEvents(data);
    } catch (error) {
      console.error("Error fetching events:", error);
    } finally {
      setLoading(false);
    }
  };

  // Auto-refresh every 5 seconds
  useEffect(() => {
    loadEvents();
    const interval = setInterval(loadEvents, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">🧠 Event Dashboard</h1>
        <button
          onClick={loadEvents}
          disabled={loading}
          className={`px-3 py-1 border rounded text-sm ${
            loading
              ? "bg-gray-200 cursor-not-allowed"
              : "hover:bg-gray-100 active:bg-gray-200"
          }`}
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full bg-white border border-gray-200 rounded-lg shadow-sm">
          <thead>
            <tr className="bg-gray-100 text-left text-sm text-gray-600">
              <th className="p-3">Event Type</th>
              <th className="p-3">Source</th>
              <th className="p-3">Payload</th>
              <th className="p-3">Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {events.length > 0 ? (
              events.map((ev) => (
                <tr key={ev.id} className="border-t hover:bg-gray-50">
                  <td className="p-3">
                    <span
                      className={`px-2 py-1 rounded text-white text-xs ${
                        ev.event_type.includes("order")
                          ? "bg-blue-500"
                          : ev.event_type.includes("driver")
                          ? "bg-yellow-500"
                          : ev.event_type.includes("payment")
                          ? "bg-green-500"
                          : ev.event_type.includes("notification")
                          ? "bg-purple-500"
                          : ev.event_type.includes("user")
                          ? "bg-pink-500"
                          : "bg-gray-500"
                      }`}
                    >
                      {ev.event_type}
                    </span>
                  </td>
                  <td className="p-3 text-sm text-gray-700">
                    {ev.source_service}
                  </td>
                  <td className="p-3 text-xs text-gray-600 whitespace-pre-wrap max-w-lg overflow-x-auto">
                    {JSON.stringify(ev.payload, null, 2)}
                  </td>
                  <td className="p-3 text-sm text-gray-500">
                    {new Date(ev.occurred_at).toLocaleString()}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={4} className="p-6 text-center text-gray-500">
                  No events found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
