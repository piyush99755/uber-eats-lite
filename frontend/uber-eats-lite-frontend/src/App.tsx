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

// --------------------------------------------------
// ProtectedRoute
// Allows admin to access all routes
// --------------------------------------------------
interface ProtectedRouteProps {
  role: string | null;
  allowedRoles: string[];
  children: JSX.Element;
}

function ProtectedRoute({ role, allowedRoles, children }: ProtectedRouteProps) {
  if (!role) return <Navigate to="/" replace />;
  if (role !== "admin" && !allowedRoles.includes(role)) return <Navigate to="/" replace />;
  return children;
}

// --------------------------------------------------
// App
// --------------------------------------------------
export default function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem("token"));
  const [role, setRole] = useState<string | null>(null);

  // Decode JWT to get role
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
              <Route
                path="/orders"
                element={
                  <ProtectedRoute role={role} allowedRoles={["user"]}>
                    <Orders />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/payments"
                element={
                  <ProtectedRoute role={role} allowedRoles={["user"]}>
                    <Payments />
                  </ProtectedRoute>
                }
              />

              {/* DRIVER ROUTES */}
              <Route
                path="/driver/orders"
                element={
                  <ProtectedRoute role={role} allowedRoles={["driver"]}>
                    <DriverOrders />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/driver/profile"
                element={
                  <ProtectedRoute role={role} allowedRoles={["driver"]}>
                    <DriverProfile />
                  </ProtectedRoute>
                }
              />

              {/* ADMIN ROUTES */}
              <Route
                path="/users"
                element={
                  <ProtectedRoute role={role} allowedRoles={["admin"]}>
                    <Users />
                  </ProtectedRoute>
                }
              />
              <Route
                  path="/drivers"
                  element={
                    <ProtectedRoute role={role} allowedRoles={["admin"]}>
                      <Drivers role={role} />
                    </ProtectedRoute>
                  }
              />

              <Route
                path="/orders"
                element={
                  <ProtectedRoute role={role} allowedRoles={["user", "admin"]}>
                    <Orders /> {/* ✅ no role prop needed */}
                  </ProtectedRoute>
                }
              />
              <Route
                path="/events"
                element={
                  <ProtectedRoute role={role} allowedRoles={["admin"]}>
                    <Events />
                  </ProtectedRoute>
                }
              />
            </Routes>
          </main>
        </div>
      )}
    </BrowserRouter>
  );
}
