import { BrowserRouter, Routes, Route, Link, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import Home from "./pages/Home";
import Orders from "./pages/Orders";
import Users from "./pages/Users";
import Drivers from "./pages/Drivers";
import Notifications from "./pages/Notifications";
import Payments from "./pages/Payments";
import Events from "./pages/Events"; // create this page next
import api from "./api/api";

interface ServiceHealth {
  name: string;
  endpoint: string;
  status: "healthy" | "down";
}

function Sidebar() {
  const location = useLocation();
  const links = [
    { path: "/", label: "🏠 Home" },
    { path: "/users", label: "👥 Users" },
    { path: "/orders", label: "🧾 Orders" },
    { path: "/drivers", label: "🚗 Drivers" },
    { path: "/payments", label: "💳 Payments" },
    { path: "/notifications", label: "🔔 Notifications" },
    { path: "/events", label: "📊 Events" },
  ];

  return (
    <div className="w-56 bg-gray-900 text-white min-h-screen p-5 flex flex-col gap-4">
      <h1 className="text-xl font-bold mb-4 text-green-400">Uber Eats Lite</h1>
      {links.map(({ path, label }) => (
        <Link
          key={path}
          to={path}
          className={`px-3 py-2 rounded-lg transition ${
            location.pathname === path
              ? "bg-green-600 text-white"
              : "hover:bg-gray-700"
          }`}
        >
          {label}
        </Link>
      ))}
    </div>
  );
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
    const interval = setInterval(checkHealth, 10000); // refresh every 10s
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

function AppLayout() {
  return (
    <div className="flex bg-gray-50">
      <Sidebar />
      <main className="flex-1 p-6">
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

export default function App() {
  return (
    <BrowserRouter>
      <AppLayout />
    </BrowserRouter>
  );
}
