import { useEffect, useState } from "react";
import api from "../api/api";

interface ServiceHealth {
  name: string;
  endpoint: string;
}

const services: ServiceHealth[] = [
  { name: "User Service", endpoint: "/users/health" },
  { name: "Order Service", endpoint: "/orders/health" },
  { name: "Driver Service", endpoint: "/drivers/health" },
  { name: "Payment Service", endpoint: "/payments/health" },
  { name: "Notification Service", endpoint: "/notifications/health" },
];

export default function HealthCard() {
  const [status, setStatus] = useState<Record<string, boolean>>({});

  useEffect(() => {
    services.forEach(async (svc) => {
      try {
        const res = await api.get(svc.endpoint);
        setStatus(prev => ({ ...prev, [svc.name]: res.data.status === "ok" }));
      } catch {
        setStatus(prev => ({ ...prev, [svc.name]: false }));
      }
    });
  }, []);

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
      {services.map((svc) => (
        <div key={svc.name} className="border p-4 rounded-lg shadow text-center">
          <h3 className="font-bold mb-2">{svc.name}</h3>
          {status[svc.name] ? (
            <span className="text-green-600 font-semibold">🟢 Healthy</span>
          ) : (
            <span className="text-red-600 font-semibold">🔴 Down</span>
          )}
        </div>
      ))}
    </div>
  );
}
