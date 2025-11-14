import { NavLink } from "react-router-dom";
import { LayoutDashboard, Users, Truck, CreditCard, Bell, ShoppingBag } from "lucide-react";

interface SidebarProps {
  role: string | null;
  onLogout?: () => void;
}

export default function Sidebar({ role, onLogout }: SidebarProps) {
  const links = [
    { name: "Dashboard", path: "/" },
    { name: "Orders", path: "/orders" },
    { name: "Payments", path: "/payments" },
  ];

  if (role === "admin") {
    links.push(
      { name: "Users", path: "/users" },
      { name: "Drivers", path: "/drivers" },
      { name: "Events", path: "/events" }
    );
  }

  return (
    <div className="w-60 h-screen bg-gray-900 text-white flex flex-col p-4 space-y-4">
      <h2 className="text-xl font-bold mb-6">🍔 Uber Eats Lite</h2>
      {links.map((link) => (
        <NavLink
          key={link.path}
          to={link.path}
          className={({ isActive }) =>
            `block p-2 rounded-md flex items-center gap-2 ${
              isActive
                ? "bg-green-600 text-white"
                : "text-gray-300 hover:bg-gray-700 hover:text-white"
            }`
          }
        >
          {link.name === "Dashboard" && <LayoutDashboard size={18} />}
          {link.name === "Orders" && <ShoppingBag size={18} />}
          {link.name === "Payments" && <CreditCard size={18} />}
          {link.name === "Users" && <Users size={18} />}
          {link.name === "Drivers" && <Truck size={18} />}
          {link.name === "Events" && <Bell size={18} />}
          <span>{link.name}</span>
        </NavLink>
      ))}
      <button
        onClick={onLogout}
        className="mt-auto bg-red-500 hover:bg-red-600 text-white p-2 rounded"
      >
        Logout
      </button>
    </div>
  );
}
