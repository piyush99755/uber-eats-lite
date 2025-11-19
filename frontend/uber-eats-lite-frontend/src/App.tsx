import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import Orders from "./pages/Orders";
import Users from "./pages/Users";
import Drivers from "./pages/Drivers";
import Payments from "./pages/Payments";
import Events from "./pages/Events";
import Login from "./components/Login";
import Signup from "./components/Signup";
import Sidebar from "./components/Sidebar";
import DriverOrders from "./pages/DriverOrders";
import DriverProfile from "./pages/DriverProfile";
import api from "./api/api";

export default function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem("token"));
  const [role, setRole] = useState<string | null>(null);

  useEffect(() => {
    if (token) {
      try {
        const payload = JSON.parse(atob(token.split(".")[1]));
        setRole(payload.role);
        api.defaults.headers.common["Authorization"] = `Bearer ${token}`;
      } catch {
        setToken(null);
        setRole(null);
        localStorage.removeItem("token");
      }
    }
  }, [token]);

  const handleLogin = (newToken: string) => {
    setToken(newToken);
    localStorage.setItem("token", newToken);
  };

  const handleLogout = () => {
    setToken(null);
    setRole(null);
    localStorage.removeItem("token");
  };

  return (
    <BrowserRouter>
      {!token ? (
        <div className="min-h-screen flex flex-col items-center justify-center">
          <h1 className="text-3xl font-bold mb-6">🍔 Uber Eats Lite</h1>
          <div className="flex gap-4">
            <Login onLogin={handleLogin} />
            <Signup />
          </div>
        </div>
      ) : (
        <div className="flex min-h-screen bg-gray-50">
          <Sidebar role={role} onLogout={handleLogout} />

          <main className="flex-1 p-6 overflow-auto">
            <Routes>
          {/* Redirect root based on role */}
          <Route
            path="/"
            element={
              role === "driver"
                ? <Navigate to="/driver/orders" replace />
                : role === "admin"
                ? <Navigate to="/users" replace />
                : <Navigate to="/orders" replace />
            }
          />

          {/* USER ROUTES */}
          {role === "user" && (
            <>
              <Route path="/orders" element={<Orders />} />
              <Route path="/payments" element={<Payments />} />
            </>
          )}

          {/* DRIVER ROUTES */}
          {role === "driver" && (
            <>
              <Route path="/driver/orders" element={<DriverOrders />} />
              <Route path="/driver/profile" element={<DriverProfile />} />
            </>
          )}

          {/* ADMIN ROUTES */}
          {role === "admin" && (
            <>
              <Route path="/users" element={<Users />} />
              <Route path="/drivers" element={<Drivers />} />
              <Route path="/events" element={<Events />} />
            </>
          )}
        </Routes>

          </main>
        </div>
      )}
    </BrowserRouter>
  );
}
