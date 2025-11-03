import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useEffect, useState } from "react";
import Home from "./pages/Home";
import Orders from "./pages/Orders";
import Users from "./pages/Users";
import Drivers from "./pages/Drivers";
import Notifications from "./pages/Notifications";
import Payments from "./pages/Payments";
import Events from "./pages/Events";
import api from "./api/api";
import Sidebar from "./components/Sidebar";

// --- Health Panel ---
interface ServiceHealth {
  name: string;
  endpoint: string;
  status: "healthy" | "down";
}

function HealthPanel() {
  const [services, setServices] = useState<ServiceHealth[]>([]);

  useEffect(() => {
    const checkHealth = async () => {
      const endpoints = [
        { name: "API Gateway", endpoint: "/health" },
        { name: "User Service", endpoint: "/users/health" },
        { name: "Order Service", endpoint: "/orders/health" },
        { name: "Driver Service", endpoint: "/drivers/health" },
        { name: "Payment Service", endpoint: "/payments/health" },
        { name: "Notification Service", endpoint: "/notifications/health" },
      ];

      const results: ServiceHealth[] = await Promise.all(
        endpoints.map(async (svc) => {
          try {
            await api.get(svc.endpoint);
            return { ...svc, status: "healthy" as const };
          } catch {
            return { ...svc, status: "down" as const };
          }
        })
      );

      setServices(results);
    };

    checkHealth();
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 mb-6">
      {services.map((svc) => (
        <div
          key={svc.name}
          className="border rounded-xl p-4 bg-white shadow flex items-center justify-between"
        >
          <span className="font-semibold">{svc.name}</span>
          <span
            className={`text-sm font-bold px-3 py-1 rounded-full ${
              svc.status === "healthy"
                ? "bg-green-100 text-green-700"
                : "bg-red-100 text-red-700"
            }`}
          >
            {svc.status === "healthy" ? "🟢 Healthy" : "🔴 Down"}
          </span>
        </div>
      ))}
    </div>
  );
}

// --- App Layout with Responsive Sidebar ---
function AppLayout() {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex flex-col md:flex-row min-h-screen bg-gray-50">
      {/* Mobile Header */}
      <div className="md:hidden flex justify-between items-center p-4 bg-gray-900 text-white">
        <h1 className="text-lg font-bold">Uber Eats Lite</h1>
        <button onClick={() => setOpen(!open)} className="text-xl">
          ☰
        </button>
      </div>

      {/* Sidebar */}
      <div className={`${open ? "block" : "hidden"} md:block`}>
        <Sidebar onNavigate={() => setOpen(false)} />
      </div>

      {/* Main Content */}
      <main className="flex-1 p-6 overflow-auto">
        <HealthPanel />
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/users" element={<Users />} />
          <Route path="/drivers" element={<Drivers />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/payments" element={<Payments />} />
          <Route path="/events" element={<Events />} />
        </Routes>
      </main>
    </div>
  );
}

// --- Root App ---
export default function App() {
  return (
    <BrowserRouter>
      <AppLayout />
    </BrowserRouter>
  );
}
