import { useEffect, useState } from "react";
import { fetchEvents } from "../api/notifications";

interface EventRecord {
  id: string;
  event_type: string;
  source_service: string;
  occurred_at: string;
  payload: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export default function EventTable() {
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [loading, setLoading] = useState(false);

  const loadEvents = async () => {
    try {
      setLoading(true);
      const data = await fetchEvents();
      setEvents(data);
    } catch (err) {
      console.error("Failed to fetch events", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEvents();
    const interval = setInterval(loadEvents, 3000); // refresh every 3 sec
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-semibold">🧠 Event Dashboard</h1>
        <button
          onClick={loadEvents}
          disabled={loading}
          className={`px-3 py-1 border rounded ${
            loading ? "opacity-50 cursor-not-allowed" : "hover:bg-gray-100"
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
            {events.map((ev) => (
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
                        : ev.event_type.includes("user")
                        ? "bg-purple-500"
                        : "bg-gray-400"
                    }`}
                  >
                    {ev.event_type}
                  </span>
                </td>
                <td className="p-3 text-sm text-gray-700">{ev.source_service}</td>
                <td className="p-3 text-xs text-gray-600 whitespace-pre-wrap max-w-lg overflow-x-auto">
                  {JSON.stringify(ev.payload, null, 2)}
                </td>
                <td className="p-3 text-sm text-gray-500">
                  {new Date(ev.occurred_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {events.length === 0 && !loading && (
          <p className="text-center text-gray-500 mt-6">No events found</p>
        )}
      </div>
    </div>
  );
}
