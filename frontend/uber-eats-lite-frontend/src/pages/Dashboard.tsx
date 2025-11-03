import { useEffect, useState } from "react";
import api from "../api/api";

export default function Dashboard() {
  const [health, setHealth] = useState<Record<string, string>>({});

  useEffect(() => {
    const fetchHealth = async () => {
      const services = ["users", "orders", "drivers", "payments", "notifications"];
      const res: Record<string, string> = {};
      for (const s of services) {
        try {
          const r = await api.get(`/${s}/health`);
          res[s] = r.data.status?.includes("ok") || r.data.status?.includes("healthy") ? "ok" : "down";
        } catch {
          res[s] = "down";
        }
      }
      setHealth(res);
    };

    fetchHealth();
    const interval = setInterval(fetchHealth, 10000); // refresh every 10s
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="p-6">
      <h1 className="text-3xl font-bold mb-6 text-center">🩺 Service Health Dashboard</h1>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Object.entries(health).map(([service, status]) => (
          <div
            key={service}
            className={`p-4 rounded-xl shadow-md border flex items-center justify-between ${
              status === "ok" ? "bg-green-50 border-green-400" : "bg-red-50 border-red-400"
            }`}
          >
            <span className="capitalize font-medium">{service}-service</span>
            <span className={`font-bold ${status === "ok" ? "text-green-700" : "text-red-700"}`}>
              {status === "ok" ? "🟢 Healthy" : "🔴 Down"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
