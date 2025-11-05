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
  const [filteredEvents, setFilteredEvents] = useState<EventRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("");

  // Fetch events
  const loadEvents = async () => {
    try {
      setLoading(true);
      const data = await fetchEvents();
      setEvents(data);
      applyFilter(data, filter);
    } catch (err) {
      console.error("Failed to fetch events", err);
    } finally {
      setLoading(false);
    }
  };

  const applyFilter = (data: EventRecord[], selected: string) => {
    if (!selected) setFilteredEvents(data);
    else setFilteredEvents(data.filter((ev) => ev.event_type === selected));
  };

  useEffect(() => {
    loadEvents();
    const interval = setInterval(loadEvents, 3000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    applyFilter(events, filter);
  }, [filter, events]);

  const eventTypes = Array.from(new Set(events.map((e) => e.event_type)));

  return (
    <div className="p-4 sm:p-6">
      {/* Header Row */}
      <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-3 mb-4">
        <h1 className="text-xl sm:text-2xl font-semibold">🧠 Event Dashboard</h1>
        <button
          onClick={loadEvents}
          disabled={loading}
          className={`px-4 py-2 text-sm border rounded-lg ${
            loading
              ? "opacity-50 cursor-not-allowed"
              : "hover:bg-gray-100 active:bg-gray-200"
          }`}
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {/* Filter Dropdown - always visible */}
      <div className="mb-5 flex flex-col sm:flex-row items-start sm:items-center gap-2">
        <label className="text-sm font-medium text-gray-700">
          Filter by Event Type:
        </label>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="border rounded-lg px-3 py-2 text-sm w-full sm:w-auto focus:ring-2 focus:ring-blue-300"
        >
          <option value="">All</option>
          {eventTypes.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
      </div>

      {/* Table View (visible on all screens) */}
      <div className="overflow-x-auto">
        <table className="min-w-full bg-white border border-gray-200 rounded-lg shadow-sm text-sm">
          <thead>
            <tr className="bg-gray-100 text-left text-sm text-gray-600">
              <th className="p-3">Event Type</th>
              <th className="p-3">Source</th>
              <th className="p-3">Payload</th>
              <th className="p-3">Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {filteredEvents.map((ev) => (
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
                        : ev.event_type.includes("notification")
                        ? "bg-pink-500"
                        : "bg-gray-400"
                    }`}
                  >
                    {ev.event_type}
                  </span>
                </td>
                <td className="p-3 text-gray-700">{ev.source_service}</td>
                <td className="p-3 text-xs text-gray-600 whitespace-pre-wrap break-words max-w-[250px] sm:max-w-lg overflow-x-auto">
                  {JSON.stringify(ev.payload, null, 2)}
                </td>
                <td className="p-3 text-gray-500">
                  {new Date(ev.occurred_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {filteredEvents.length === 0 && !loading && (
          <p className="text-center text-gray-500 mt-6">No events found</p>
        )}
      </div>
    </div>
  );
}
